"""
Steam Review Forensics, Player Feedback Telemetry, Bot Scrubbing, and Sentiment Synthesis.
"""

from collections import Counter
import concurrent.futures
from datetime import datetime
import json
import platform
import re
import statistics
import time
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
import requests
from thefuzz import fuzz

from core.ai_tools import aiCall, clean_json_for_ai, get_summarizer_model
from core.safe_tool import safe_tool
import core.settings as settings
from core.game_intelligence.store import (
    get_global_game_info,
    get_reviews,
    get_reviews_summary,
    get_steam_app_info,
)
import core.vault as vault
from core.vault import calculate_status


def get_current_os_for_steam():
    """
    Detects the local operating system and maps it to the
    Steam API's expected 'os' parameter format.
    """
    sys_name = platform.system().lower()

    if sys_name == "linux":
        # This catches standard Linux desktop and SteamOS (Steam Deck)
        return "linux"
    elif sys_name == "darwin":
        # Python registers macOS as 'darwin'
        return "mac"
    elif sys_name == "windows":
        return "windows"
    else:
        # Fallback for unsupported/other OS types
        return "all"


def _normalize_review_record(raw_review: dict) -> dict:
    """Flatten nested Steam `author` review metrics onto top-level keys without mutating input."""
    r = dict(raw_review)
    author = r.get("author") if isinstance(r.get("author"), dict) else {}
    if "playtime_at_review" not in r:
        r["playtime_at_review"] = author.get("playtime_at_review")
    if "playtime_forever" not in r:
        r["playtime_forever"] = author.get("playtime_forever")
    if "author_num_reviews" not in r:
        r["author_num_reviews"] = author.get("num_reviews")
    if "author_games_owned" not in r and author.get("num_games_owned") is not None:
        r["author_games_owned"] = author.get("num_games_owned")
    return r


def _compute_review_telemetry(appid, sample_size: int = 60) -> dict:
    """
    Sweep the most recent global reviews via `IUserReviewsService` and compute
    neutral composition metrics (purchase type, hours at review, reviewer history, daily cluster).
    """
    resp = get_reviews(
        str(appid),
        {
            "filter": "recent",
            "review_type": "all",
            "purchase_type": "all",
            "language": "all",
            "filter_offtopic_activity": 0,
            "num_per_page": min(max(int(sample_size), 1), 100),
        },
    )
    reviews = resp.get("reviews", []) if isinstance(resp, dict) else []
    n = len(reviews)
    if n == 0:
        return {"sample_size": 0}

    pos_count = 0
    steam_purchase_count = 0
    non_steam_or_free_count = 0
    free_copy_count = 0
    refunded_count = 0
    early_access_count = 0
    playtimes_hours = []
    under_1h_count = 0
    low_history_count = 0
    day_counts: Counter = Counter()

    for rev in reviews:
        if rev.get("voted_up"):
            pos_count += 1
        steam_buy = bool(rev.get("steam_purchase"))
        free_copy = bool(rev.get("received_for_free"))
        if steam_buy:
            steam_purchase_count += 1
        if (not steam_buy) or free_copy:
            non_steam_or_free_count += 1
        if free_copy:
            free_copy_count += 1
        if rev.get("refunded"):
            refunded_count += 1
        if rev.get("written_during_early_access"):
            early_access_count += 1

        author = rev.get("author") if isinstance(rev.get("author"), dict) else {}
        pt_mins = author.get("playtime_at_review")
        if isinstance(pt_mins, (int, float)):
            playtimes_hours.append(pt_mins / 60.0)
            if pt_mins < 60:
                under_1h_count += 1

        num_rev = author.get("num_reviews")
        if isinstance(num_rev, int) and num_rev <= 2:
            low_history_count += 1

        ts = rev.get("timestamp_created")
        if isinstance(ts, (int, float)) and ts > 0:
            day_counts[datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")] += 1

    telemetry = {
        "sample_size": n,
        "sample_positive_pct": round((pos_count / n) * 100.0, 1),
        "steam_purchase_pct": round((steam_purchase_count / n) * 100.0, 1),
        "non_steam_or_free_pct": round((non_steam_or_free_count / n) * 100.0, 1),
        "received_for_free_pct": round((free_copy_count / n) * 100.0, 1),
        "low_playtime_under_1h_pct": round((under_1h_count / len(playtimes_hours)) * 100.0, 1) if playtimes_hours else None,
        "median_playtime_at_review_hours": round(statistics.median(playtimes_hours), 1) if playtimes_hours else None,
        "low_history_accounts_pct": round((low_history_count / n) * 100.0, 1),
        "refunded_pct": round((refunded_count / n) * 100.0, 1),
        "early_access_pct": round((early_access_count / n) * 100.0, 1),
    }
    if n >= 10 and day_counts:
        peak_day, peak_count = day_counts.most_common(1)[0]
        telemetry["peak_day"] = {"date": peak_day, "count": peak_count}
    return telemetry


@safe_tool
def get_n_reviews(appid, n, review_type="all", filter_os=True):
    reviews = []
    # Use a set for O(1) duplicate lookups
    seen_ids = set()
    cursor = '*'

    params = {
        'filter': 'all',
        'language': 'english',  # Usually safer to specify, or Steam defaults to user's IP locale
        'review_type': review_type,
        'purchase_type': 'all',
        'filter_offtopic_activity': 1,
        'num_per_page': 100,

    }

    if filter_os:
        params['os'] = get_current_os_for_steam()

    last_cursor = ""

    while len(reviews) < n:
        params['cursor'] = cursor

        # Call your helper function (assuming it returns the json dict)
        response = get_reviews(str(appid), params)

        # Check for API failure or empty response
        if not response or response.get('success') != 1:
            print("API request failed or finished.")
            break

        query_summary = response.get('query_summary', {})
        if query_summary.get('num_reviews', 0) == 0:
            print("No more reviews found.")
            break

        # Process the new batch
        fetched_reviews = response.get('reviews', [])

        for r in fetched_reviews:
            # Use Steam's unique recommendationid
            rid = r.get('recommendationid')

            # Only add if we haven't seen this ID and we haven't reached the limit
            if rid not in seen_ids:
                reviews.append(r)
                seen_ids.add(rid)

            # optimization: break inner loop immediately if we hit limit
            if len(reviews) >= n:
                break

        cursor = response.get('cursor')

        print(f"{len(reviews)}/{n} reviews collected.")

        # Safety break for infinite loops (Steam API quirk)
        if last_cursor == cursor:
            print("Cursor stuck, stopping.")
            break

        last_cursor = cursor

    print(f"Finished with {len(reviews)} reviews")
    return reviews


@safe_tool
def get_steam_reviews(appid, count):
    """
    Gets a hybrid mix of OS-specific and general reviews alongside global summary
    and neutral recent-sample composition telemetry.
    """
    os_count = count // 2
    all_count = count - os_count

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        f_pos_os = executor.submit(get_n_reviews, appid, os_count, "positive", True)
        f_neg_os = executor.submit(get_n_reviews, appid, os_count, "negative", True)
        f_pos_all = executor.submit(get_n_reviews, appid, all_count, "positive", False)
        f_neg_all = executor.submit(get_n_reviews, appid, all_count, "negative", False)
        f_summary = executor.submit(get_reviews_summary, appid)
        f_telemetry = executor.submit(_compute_review_telemetry, appid, 60)

        pos_os = f_pos_os.result() or []
        neg_os = f_neg_os.result() or []
        pos_all = f_pos_all.result() or []
        neg_all = f_neg_all.result() or []
        summary = f_summary.result() or {}
        telemetry = f_telemetry.result() or {"sample_size": 0}

    def merge_and_dedupe(list1, list2):
        merged = {}
        for review in list1 + list2:
            rid = review.get('recommendationid')
            if rid not in merged:
                merged[rid] = _normalize_review_record(review)
        return list(merged.values())

    positive = merge_and_dedupe(pos_os, pos_all)
    negative = merge_and_dedupe(neg_os, neg_all)
    reviews = positive + negative

    summary = clean_json_for_ai(
        summary,
        ['review_score', 'review_score_desc', 'total_negative', 'total_positive', 'total_reviews'],
    )

    return {
        'reviews': reviews,
        'summary': summary,
        'telemetry': telemetry,
        'fetch_positive': len(positive),
        'fetch_negative': len(negative),
    }


def _summarize_reviews_with_llm(game_name: str, summary: dict, reviews: list) -> tuple:
    """Condense sampled Steam reviews into a tight consensus digest using the configured summarizer model."""
    if not reviews:
        return None, None, None
    if not settings.OPENAI_API_KEY or not get_summarizer_model():
        return None, None, "LLM API key or model not configured."

    bullets = []
    for idx, r in enumerate(reviews[:40], 1):
        verdict = "POS" if r.get("voted_up") else "NEG"
        src = "Free" if r.get("received_for_free") else ("Steam" if r.get("steam_purchase") else "Key/Other")
        hrs = r.get("playtime_at_review", "N/A")
        acct_n = r.get("author_num_reviews", "?")
        ea = " EA" if r.get("written_during_early_access") else ""
        ref = " Refunded" if r.get("refunded") else ""
        snippet = str(r.get("review", "")).replace("\r\n", " ").replace("\n", " ").strip()[:360]
        bullets.append(f"{idx}. [{verdict} | {src} | {hrs} | {acct_n} revs{ea}{ref}] {snippet}")

    pos = summary.get("total_positive", 0)
    neg = summary.get("total_negative", 0)
    tot = summary.get("total_reviews", pos + neg)
    system_prompt = (
        f"You are summarizing Steam user reviews for '{game_name}' ({pos} pos / {neg} neg, {tot} total). "
        "Synthesize ONLY facts present in the supplied reviews into 3 concise bullet sections without fluff:\n"
        "- Praise: ...\n- Complaints: ...\n- Technical/Notes: ...\n"
        "Preserve minority criticisms cleanly even on well-reviewed games, and never invent features not stated."
    )
    try:
        digest, in_tok, out_tok = aiCall(
            "\n".join(bullets),
            system_prompt,
            return_tokens=True,
            model=get_summarizer_model(),
        )
        return digest.strip(), {"in": in_tok, "out": out_tok}, None
    except Exception as e:
        return None, None, str(e)


@safe_tool
def get_reviews_byname(game_name, count=10, summarize=False):
    """
    Gets the reviews and neutral recent-sample telemetry for a given game name.
    When `summarize=True`, fetches a broader batch and condenses it via sub-LLM digest.
    """
    review_schema = {
        "transformations": {
            "timestamp_created": "date",
            "playtime_forever": "minutes_to_hours",
            "playtime_at_review": "minutes_to_hours",
            "votes_up": "int",
        },
        "keep_keys": [
            "review",
            "playtime_at_review",
            "playtime_forever",
            "author_num_reviews",
            "author_games_owned",
            "voted_up",
            "steam_purchase",
            "received_for_free",
            "written_during_early_access",
            "primarily_steam_deck",
            "refunded",
            "votes_funny",
            "votes_up",
            "timestamp_created",
        ],
    }

    app = get_steam_app_info(game_name)
    if not app:
        return {"error": f"Game '{game_name}' not found on Steam."}

    appid = app['id'][0]
    fetch_count = max(int(count), 20) if summarize else int(count)
    steam_reviews = get_steam_reviews(appid, fetch_count)
    if isinstance(steam_reviews, dict) and "error" in steam_reviews:
        return steam_reviews

    cleaned_reviews = clean_json_for_ai(
        steam_reviews['reviews'],
        transformations=review_schema["transformations"],
        keep_keys=review_schema["keep_keys"],
    )

    if summarize:
        digest, tokens, err = _summarize_reviews_with_llm(
            app.get("name", game_name),
            steam_reviews.get("summary", {}),
            cleaned_reviews,
        )
        if digest:
            steam_reviews["summary_digest"] = digest
        if tokens:
            steam_reviews["_tokens"] = tokens
        if err:
            steam_reviews["digest_error"] = err
        # Keep only up to 4 anchor quotes alongside a digest (2 pos + 2 neg)
        pos_quotes = [r for r in cleaned_reviews if r.get("voted_up")][:2]
        neg_quotes = [r for r in cleaned_reviews if not r.get("voted_up")][:2]
        steam_reviews["reviews"] = pos_quotes + neg_quotes
    else:
        steam_reviews["reviews"] = cleaned_reviews

    return steam_reviews


@safe_tool
def evaluate_game(game_name: str, deep: bool = False):
    """
    Composite game investigator combining library ownership/status, Steam & CheapShark
    store/pricing/HLTB details, global + recent review telemetry, and optional (`deep=True`)
    sub-LLM review digest + community consensus in a single round-trip.
    """
    app = get_steam_app_info(game_name)
    if not app:
        return {"error": f"Game '{game_name}' not found on Steam."}

    appid = int(app["id"][0])
    canonical_name = app.get("name") or game_name

    vault_entry = vault.get_game_by_appid(appid)
    vault_status = None
    if vault_entry:
        vault_status = {
            "appid": appid,
            "name": vault_entry.get("name", canonical_name),
            "status": calculate_status(vault_entry),
            "hours": round((vault_entry.get("playtime_forever") or 0) / 60.0, 1),
            "last_played": vault.format_time_ago(vault_entry.get("rtime_last_played", 0)),
        }

    # Lazy import avoids circular top-level dependency with community_sentiment
    import core.community_sentiment as community_sentiment

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        f_details = executor.submit(get_global_game_info, canonical_name)
        f_reviews = executor.submit(get_reviews_byname, canonical_name, 8, deep)
        f_sentiment = executor.submit(community_sentiment.get_community_sentiment, canonical_name) if deep else None

        details = f_details.result()
        reviews = f_reviews.result()
        sentiment = f_sentiment.result() if f_sentiment else None

    total_in = 0
    total_out = 0
    for block in (reviews, sentiment):
        if isinstance(block, dict) and "_tokens" in block:
            tok = block.pop("_tokens") or {}
            total_in += tok.get("in", 0)
            total_out += tok.get("out", 0)

    payload = {
        "appid": appid,
        "game_name": canonical_name,
        "vault_status": vault_status,
        "details": details,
        "reviews": reviews,
        "community_sentiment": sentiment,
    }
    if total_in > 0 or total_out > 0:
        payload["_tokens"] = {"in": total_in, "out": total_out}

    return payload
