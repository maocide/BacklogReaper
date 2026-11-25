"""
Shared Markdown formatters for BacklogReaper tool outputs.
Used identically by core/agent_tools.py and mcp_server.py so internal agents
and external MCP callers receive compact, structured, consistent Markdown.
"""

from datetime import datetime
import time
from typing import Any, Dict, List, Optional


def _cell(value: Any, max_len: int = 80) -> str:
    """Sanitize a value for Markdown table cell rendering."""
    if value is None or value == "":
        return "N/A"
    text = str(value).replace("|", "\\|").replace("\r\n", " ").replace("\n", " ").strip()
    if max_len and len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _table(headers: List[str], rows: List[List[Any]]) -> str:
    """Build a GitHub-flavored Markdown table."""
    if not rows:
        return "_No entries._"
    header_line = "| " + " | ".join(_cell(h, max_len=0) for h in headers) + " |"
    sep_line = "| " + " | ".join("---" for _ in headers) + " |"
    body_lines = [
        "| " + " | ".join(_cell(c) for c in row) + " |"
        for row in rows
    ]
    return "\n".join([header_line, sep_line] + body_lines)


def _format_error(title: str, data: Any) -> Optional[str]:
    """Return formatted Markdown error block if payload indicates an error, else None."""
    if isinstance(data, dict) and "error" in data:
        err_msg = data.get("error", "Unknown error")
        err_type = data.get("error_type")
        lines = [f"### ❌ {title} Error", f"**Details:** {err_msg}"]
        if err_type:
            lines.append(f"**Type:** `{err_type}`")
        return "\n".join(lines)
    return None


def _short_tags(tags: Any, limit: int = 5) -> str:
    """Format comma-separated or list tags cleanly capped at `limit`."""
    if not tags:
        return "N/A"
    if isinstance(tags, str):
        parts = [t.strip() for t in tags.split(",") if t.strip()]
    elif isinstance(tags, list):
        parts = [str(t).strip() for t in tags if str(t).strip()]
    else:
        return str(tags)
    if not parts:
        return "N/A"
    shown = parts[:limit]
    suffix = f" (+{len(parts) - limit})" if len(parts) > limit else ""
    return ", ".join(shown) + suffix


def _format_hltb_pair(main_h: Any, comp_h: Any) -> str:
    main_str = f"{main_h}h" if isinstance(main_h, (int, float)) else str(main_h or "N/A")
    comp_str = f"{comp_h}h" if isinstance(comp_h, (int, float)) else str(comp_h or "N/A")
    return f"{main_str} / {comp_str}"


def format_vault_search(payload: Any, is_recent: bool = False, title: str = "Vault Search Results") -> str:
    err = _format_error(title, payload)
    if err:
        return err

    if isinstance(payload, dict):
        results = payload.get("results", [])
        total_count = payload.get("total_count", len(results))
        page = payload.get("page", 0)
        total_pages = payload.get("total_pages", 1 if results else 0)
        skipped_hltb = payload.get("unknown_hltb_skipped", 0)
        expanded_tags = payload.get("expanded_tags")
    elif isinstance(payload, list):
        results = payload
        total_count = len(results)
        page = 0
        total_pages = 1 if results else 0
        skipped_hltb = 0
        expanded_tags = None
    else:
        return f"### {title}\nUnexpected response shape."

    lines = [f"### 🎮 {title}"]
    if total_pages > 1:
        lines.append(f"**Matches:** {total_count} total (Showing {len(results)} on Page {page + 1}/{total_pages})")
    else:
        lines.append(f"**Matches:** {total_count}")

    if expanded_tags:
        exp_parts = [f"'{k}' → [{', '.join(v)}]" for k, v in expanded_tags.items() if v]
        if exp_parts:
            lines.append(f"**Expanded Tags:** {'; '.join(exp_parts)}")

    if is_recent:
        lines.append("> **Note:** Playtime reflects *lifetime* hours played, sorted by most recently played.")

    if skipped_hltb > 0:
        lines.append(f"> **Note:** {skipped_hltb} matching title(s) skipped because HLTB duration is unknown (`include_unknown_hltb=True` to include).")

    if not results:
        lines.append("\nNo owned games matched those filters.")
        return "\n".join(lines)

    rows = []
    for g in results:
        hrs = g.get("hours", 0)
        hrs_str = f"{hrs}h" if isinstance(hrs, (int, float)) else str(hrs or "0h")
        score = g.get("review_score")
        score_str = f"{score}%" if isinstance(score, (int, float)) and score >= 0 else "N/A"
        rows.append([
            g.get("appid", "N/A"),
            g.get("name", "Unknown"),
            g.get("status", "N/A"),
            hrs_str,
            _format_hltb_pair(g.get("hltb_main"), g.get("hltb_completionist")),
            score_str,
            g.get("last_played", "N/A"),
            _short_tags(g.get("tags"), limit=5),
        ])

    lines.append("")
    lines.append(_table(["AppID", "Title", "Status", "Playtime", "HLTB (Main/Comp)", "Score", "Last Played", "Tags"], rows))
    return "\n".join(lines)


def format_library_stats(stats: Any) -> str:
    err = _format_error("Library Stats", stats)
    if err:
        return err

    lines = [
        "### 📊 Library Audit Stats",
        f"- **Total Games Owned:** {stats.get('total_games', 0)}",
        f"- **Unplayed:** {stats.get('unplayed_count', 0)} | **Bounced (<2h):** {stats.get('bounced_count', 0)} | **Shame Rate:** {stats.get('shame_percentage', '0%')}",
        f"- **Completion Rate:** {stats.get('completion_rate', '0%')}",
        f"- **Total Hours Played:** {stats.get('total_hours_played', 0)}h (Avg {stats.get('avg_playtime_hours', 0)}h/game)",
        f"- **Estimated Backlog Debt:** {stats.get('backlog_debt_hours', 0)}h",
    ]

    top_played = stats.get("top_played_genres", [])
    if top_played:
        played_str = ", ".join(f"{g['tag']} ({g['hours']}h)" for g in top_played)
        lines.append(f"- **Top Played Genres:** {played_str}")

    top_owned = stats.get("top_owned_genres", [])
    if top_owned:
        owned_str = ", ".join(f"{g['tag']} ({g['count']} games)" for g in top_owned)
        lines.append(f"- **Top Owned Genres:** {owned_str}")

    return "\n".join(lines)


def format_user_tags(tags_list: Any, recent_days: Optional[int] = None, limit: int = 50) -> str:
    err = _format_error("User Tags", tags_list)
    if err:
        return err

    period = f"Last {recent_days} Days" if recent_days else "Lifetime"
    lines = [f"### 🏷️ Top User Tags ({period} — Top {len(tags_list)} of {limit} cap)"]
    if not tags_list:
        lines.append("\nNo tag history available for this period.")
        return "\n".join(lines)

    count_key = "active_titles_count" if recent_days else "owned_count"
    count_label = "Active Titles" if recent_days else "Owned Titles"
    rows = [
        [t.get("name", "Unknown"), t.get(count_key, 0), f"{t.get('lifetime_hours_in_tag', 0)}h"]
        for t in tags_list
    ]
    lines.append("")
    lines.append(_table(["Tag", count_label, "Lifetime Hours"], rows))
    return "\n".join(lines)


def format_similar_games(matches: Any, target_game: str = "") -> str:
    err = _format_error(f"Similar Owned Games ({target_game})", matches)
    if err:
        return err

    header = f"### 🧬 Owned Library DNA Matches for '{target_game}'" if target_game else "### 🧬 Owned Library DNA Matches"
    if not matches:
        return f"{header}\n\nNo sufficiently close matches found in your library."

    rows = [
        [
            m.get("appid", "N/A"),
            m.get("name", "Unknown"),
            m.get("status", "N/A"),
            m.get("match_score", "N/A"),
            m.get("hours", "0h"),
            _format_hltb_pair(m.get("hltb_main_hours"), m.get("hltb_completionist_hours")),
            _short_tags(m.get("tags"), limit=5),
        ]
        for m in matches
    ]
    return f"{header}\n**Matches Found:** {len(matches)}\n\n" + _table(
        ["AppID", "Title", "Status", "DNA Match", "Playtime", "HLTB (Main/Comp)", "Tags"],
        rows,
    )


def format_vibe_search(results: Any, query: str = "") -> str:
    err = _format_error("Vibe Search", results)
    if err:
        return err

    header = f"### ✨ Vibe Search Results for '{query}'" if query else "### ✨ Vibe Search Results"
    if not results:
        return f"{header}\n\nNo games matched that vibe."

    rows = []
    for g in results:
        pt = g.get("playtime_forever")
        pt_str = f"{round(pt / 60, 1)}h" if isinstance(pt, (int, float)) else str(g.get("playtime", "0h"))
        hltb_m = g.get("hltb_main")
        hltb_c = g.get("hltb_completionist")
        m_str = f"{round(hltb_m / 60, 1)}h" if isinstance(hltb_m, (int, float)) and hltb_m > 0 else str(g.get("hltb_main_hours", "N/A"))
        c_str = f"{round(hltb_c / 60, 1)}h" if isinstance(hltb_c, (int, float)) and hltb_c > 0 else str(g.get("hltb_completionist_hours", "N/A"))
        rows.append([
            g.get("appid", "N/A"),
            g.get("name", "Unknown"),
            g.get("status", "N/A"),
            g.get("vibe_match", g.get("vibe_match_score", "N/A")),
            pt_str,
            f"{m_str} / {c_str}",
            _short_tags(g.get("tags"), limit=4),
        ])

    return f"{header}\n**Matches:** {len(results)}\n\n" + _table(
        ["AppID", "Title", "Status", "Vibe Match", "Playtime", "HLTB (Main/Comp)", "Tags"],
        rows,
    )


def format_store_search(
    results: Any,
    search_term: str = "",
    sort_by: str = "relevance",
    tags: Optional[List[str]] = None,
    specials_only: bool = False,
    ownership: str = "all",
) -> str:
    err = _format_error("Steam Store Search", results)
    if err:
        return err

    parts = []
    if search_term:
        parts.append(f"term: '{search_term}'")
    if tags:
        parts.append(f"tags: {tags}")
    if specials_only:
        parts.append("deals only")
    if ownership and ownership != "all":
        parts.append(f"ownership: `{ownership}`")
    parts.append(f"sort: `{sort_by}`")

    header = f"### 🛍️ Steam Store Search ({', '.join(parts)})"
    if not results:
        return f"{header}\n\nNo store results found."

    rows = []
    for r in results:
        if r.get("owned"):
            badge = "`[IN LIBRARY]`"
        elif r.get("on_wishlist"):
            badge = "`[ON WISHLIST]`"
        else:
            badge = "Unowned"

        disc = r.get("discount")
        price_str = r.get("price", "N/A")
        if disc and disc not in ("None", "0%", "0"):
            price_str = f"{price_str} ({disc})"

        rows.append([
            r.get("appid", "N/A"),
            r.get("name", "Unknown"),
            price_str,
            r.get("reviews", "Unknown"),
            r.get("release_date", "Unknown"),
            badge,
        ])

    return f"{header}\n**Results:** {len(results)}\n\n" + _table(
        ["AppID", "Title", "Price", "Reviews", "Released", "Status"],
        rows,
    )


def format_game_details(details: Any) -> str:
    err = _format_error("Game Details", details)
    if err:
        return err

    items = details if isinstance(details, list) else [details]
    if not items:
        return "### 📋 Game Details\nNo details retrieved."

    sections = []
    for item in items:
        item_err = _format_error(item.get("title", "Game"), item)
        if item_err:
            sections.append(item_err)
            continue

        title = item.get("title", "Unknown Game")
        owned_badge = "`[IN LIBRARY]`" if item.get("owned") else "`[UNOWNED]`"
        market = item.get("market_analysis", {})
        hltb = item.get("how_long_to_beat_hours", {})
        pos = item.get("total_positive")
        neg = item.get("total_negative")
        total_rev = item.get("total_reviews")
        if total_rev is None and pos is not None and neg is not None:
            total_rev = pos + neg

        lines = [f"### 📋 {title} {owned_badge}"]
        lines.append(f"- **Developer / Publisher:** {item.get('developer', 'N/A')} / {item.get('publisher', 'N/A')}")
        lines.append(f"- **Genre / Tags:** {item.get('genre', 'N/A')} | {_short_tags(item.get('tags'), limit=8)}")
        lines.append(f"- **Current Price:** {market.get('official_current', item.get('price', 'N/A'))} | **Lowest Deal:** {market.get('lowest_recorded', 'N/A')}")
        lines.append(f"- **Value ($/h):** Current `{market.get('price_per_hour', 'N/A')}` | Historic Low `{market.get('price_per_hour_low', 'N/A')}` | Your Playtime Rate `{market.get('user_price_per_hour', 'N/A')}`")

        rev_detail = f"{item.get('user_score', 'N/A')}"
        if total_rev is not None:
            rev_detail += f" ({pos} pos / {neg} neg — {total_rev} total)"
        lines.append(f"- **Reviews:** {rev_detail} | **CCU:** {item.get('ccu', 'N/A')}")
        lines.append(f"- **Community Playtime:** Avg `{item.get('playtime_avg', 'No Data')}` | Median `{item.get('median_forever', 'No Data')}`")

        if hltb:
            lines.append(f"- **HLTB Estimates:** Main `{hltb.get('main_story', 'N/A')}h` | Main+Extras `{hltb.get('main_extra', 'N/A')}h` | Completionist `{hltb.get('completionist', 'N/A')}h`")
        else:
            lines.append("- **HLTB Estimates:** N/A")

        desc = item.get("description")
        if desc:
            lines.append(f"- **Summary:** {desc}")
        sections.append("\n".join(lines))

    return "\n\n---\n\n".join(sections)


def format_reviews(data: Any, game_name: str = "") -> str:
    err = _format_error(f"Steam Reviews ({game_name})", data)
    if err:
        return err

    summary = data.get("summary", {}) if isinstance(data, dict) else {}
    telemetry = data.get("telemetry", {}) if isinstance(data, dict) else {}
    reviews = data.get("reviews", []) if isinstance(data, dict) else []
    digest = data.get("summary_digest") if isinstance(data, dict) else None
    digest_err = data.get("digest_error") if isinstance(data, dict) else None

    title = f"### 🗣️ Steam Reviews: {game_name}" if game_name else "### 🗣️ Steam Reviews"
    lines = [title]
    if summary:
        pos = summary.get("total_positive", 0)
        neg = summary.get("total_negative", 0)
        tot = summary.get("total_reviews", pos + neg)
        pct = f"{round((pos / tot) * 100, 1)}%" if tot else "N/A"
        lines.append(
            f"**Global Summary:** {summary.get('review_score_desc', 'Unknown')} ({pct}) — "
            f"**{pos}** positive / **{neg}** negative (**{tot}** total)"
        )

    if isinstance(telemetry, dict) and telemetry.get("sample_size", 0) > 0:
        n = telemetry["sample_size"]
        med_h = telemetry.get("median_playtime_at_review_hours")
        med_str = f"`{med_h}h`" if med_h is not None else "N/A"
        under_1h = telemetry.get("low_playtime_under_1h_pct")
        under_1h_str = f"{under_1h}%" if under_1h is not None else "N/A"
        lines.append(f"\n**Recent Sample Telemetry** (last {n} global reviews):")
        lines.append(
            f"- **Recent Positivity:** {telemetry.get('sample_positive_pct', 'N/A')}% | "
            f"**Steam Direct Purchases:** {telemetry.get('steam_purchase_pct', 'N/A')}% | "
            f"**Non-Steam / Free:** {telemetry.get('non_steam_or_free_pct', 'N/A')}%"
        )
        lines.append(
            f"- **Playtime at Review:** Median {med_str} | **<1h Playtime:** {under_1h_str} | "
            f"**Refunded:** {telemetry.get('refunded_pct', 0.0)}%"
        )
        hist_line = (
            f"- **Reviewer History:** {telemetry.get('low_history_accounts_pct', 'N/A')}% accounts with ≤2 reviews | "
            f"**Early Access:** {telemetry.get('early_access_pct', 0.0)}%"
        )
        peak = telemetry.get("peak_day")
        if isinstance(peak, dict):
            hist_line += f" | **Peak Day:** {peak.get('count')} on {peak.get('date')}"
        lines.append(hist_line)

    if digest:
        lines.append("\n#### 📝 Review Consensus Digest")
        lines.append(digest)
    elif digest_err:
        lines.append(f"\n> ⚠️ Sub-LLM digest unavailable ({digest_err}); showing raw sampled quotes.")

    lines.append(f"\n**Sampled Quotes:** {data.get('fetch_positive', 0)} positive & {data.get('fetch_negative', 0)} negative")

    if not reviews:
        lines.append("\nNo review text returned.")
        return "\n".join(lines)

    quote_limit = 260 if digest else 500
    for idx, r in enumerate(reviews, 1):
        verdict = "👍 Recommended" if r.get("voted_up") else "👎 Not Recommended"
        pt_rev = r.get("playtime_at_review", "N/A")
        pt_rev_str = f"{pt_rev}h" if isinstance(pt_rev, (int, float)) else str(pt_rev or "N/A")
        date_str = r.get("timestamp_created", "Unknown date")

        if r.get("received_for_free"):
            src_label = "Free Copy"
        elif r.get("steam_purchase") is False:
            src_label = "Non-Steam Key"
        elif r.get("steam_purchase") is True:
            src_label = "Steam Purchase"
        else:
            src_label = "Unknown Source"

        flags = []
        acct_n = r.get("author_num_reviews")
        if isinstance(acct_n, int):
            flags.append(f"{acct_n} acct rev{'s' if acct_n != 1 else ''}")
        if r.get("written_during_early_access"):
            flags.append("Early Access")
        if r.get("primarily_steam_deck"):
            flags.append("Steam Deck")
        if r.get("refunded"):
            flags.append("Refunded")
        if r.get("votes_up"):
            flags.append(f"{r['votes_up']} helpful")
        meta_extra = f" | {', '.join(flags)}" if flags else ""
        text = str(r.get("review", "")).strip().replace("\r\n", " ").replace("\n", " ")
        if len(text) > quote_limit:
            text = text[: quote_limit - 3] + "..."
        lines.append(
            f"\n**{idx}. {verdict}** (`{src_label}` • `{pt_rev_str}` at review | {date_str}{meta_extra})\n> {text}"
        )

    return "\n".join(lines)


def format_community_sentiment(data: Any, game_name: str = "") -> str:
    err = _format_error(f"Community Sentiment ({game_name})", data)
    if err:
        return err

    lines = [f"### 🔥 Community Consensus: {game_name}" if game_name else "### 🔥 Community Consensus"]

    forums = data.get("steam_forums_opinion")
    if isinstance(forums, dict):
        lines.append("\n#### Steam Discussions")
        lines.append(forums.get("analysis") or forums.get("error") or "No forum summary.")

    reddit = data.get("reddit_opinion")
    if isinstance(reddit, dict):
        lines.append("\n#### Reddit")
        if "error" in reddit:
            lines.append(reddit["error"])
        elif "results" in reddit:
            lines.append(format_reddit_discussions(reddit["results"], game_name=game_name, include_header=False))
    elif isinstance(reddit, list):
        lines.append("\n#### Reddit")
        lines.append(format_reddit_discussions(reddit, game_name=game_name, include_header=False))

    chan = data.get("4chan_opinion")
    if isinstance(chan, dict):
        lines.append("\n#### 4chan (/v/ & /vg/)")
        lines.append(chan.get("analysis") or chan.get("error") or "No relevant threads found.")

    return "\n".join(lines)


def format_reddit_discussions(results: Any, game_name: str = "", include_header: bool = True) -> str:
    err = _format_error(f"Reddit Search ({game_name})", results)
    if err:
        return err

    lines = []
    if include_header:
        lines.append(f"### 💬 Reddit Discussions: {game_name}" if game_name else "### 💬 Reddit Discussions")

    if not results:
        lines.append("No relevant Reddit threads found.")
        return "\n".join(lines)

    for idx, p in enumerate(results, 1):
        sub = p.get("subreddit", "r/gaming")
        score = p.get("score", "N/A")
        comments = p.get("comments", "N/A")
        title = p.get("title", "Thread")
        url = p.get("url", "")
        body = p.get("body", "")
        meta = f"`{sub}`"
        if score != "N/A" or comments != "N/A":
            meta += f" • ⬆ {score} • 💬 {comments}"
        lines.append(f"{idx}. **{title}** ({meta})\n   - {body}\n   - {url}")

    return "\n".join(lines)


def format_game_deals(deal_info: Any, game_name: str = "", appid: Any = None) -> str:
    err = _format_error(f"Game Deals ({game_name})", deal_info)
    if err:
        return err

    title = f"### 💸 Lowest Recorded Deal: {game_name}" + (f" (`{appid}`)" if appid else "")
    return f"{title}\n- **Store:** {deal_info.get('store', 'N/A')}\n- **Lowest Price Found:** ${deal_info.get('price', 'N/A')}"


def format_game_news(news_items: Any, game_name: str = "") -> str:
    err = _format_error(f"Game News ({game_name})", news_items)
    if err:
        return err

    lines = [f"### 📰 Latest Steam News: {game_name}" if game_name else "### 📰 Latest Steam News"]
    if not news_items:
        lines.append("No recent official announcements found.")
        return "\n".join(lines)

    for idx, item in enumerate(news_items, 1):
        lines.append(
            f"\n#### {idx}. {item.get('title', 'Announcement')} ({item.get('date', 'Unknown')})\n"
            f"*Author: {item.get('author', 'Developer')}* | {item.get('url', '')}\n\n"
            f"{item.get('content', '')}"
        )
    return "\n".join(lines)


def format_achievements(stats: Any, game_name: str = "") -> str:
    err = _format_error(f"Achievements ({game_name})", stats)
    if err:
        return err

    title = stats.get("game") or game_name or "Game"
    if stats.get("view") == "no_achievements":
        msg = stats.get("message") or "This game does not have Steam Achievements."
        return f"### 🏆 Achievements: {title}\n{msg}"

    if stats.get("view") == "locked_list":
        page = stats.get("page", 0)
        total_locked = stats.get("total_locked", 0)
        achs = stats.get("achievements", [])
        lines = [f"### 🏆 Locked Achievements: {title} (Page {page + 1} — {total_locked} total locked)"]
        if not achs:
            lines.append("No locked achievements on this page.")
            return "\n".join(lines)
        rows = [[a.get("name", "Unknown"), f"{a.get('rarity', 0)}%", a.get("description", "Hidden")] for a in achs]
        lines.append("")
        lines.append(_table(["Achievement", "Global Rarity", "Description"], rows))
        return "\n".join(lines)

    st = stats.get("stats", {})
    lines = [
        f"### 🏆 Achievement Dashboard: {title}",
        f"- **Progress:** {st.get('unlocked_count', 0)} / {st.get('total', 0)} (**{st.get('completion_percent', 0)}%**)",
    ]

    latest = stats.get("latest_unlocks", [])
    if latest:
        lines.append("\n**Latest Unlocks:**")
        rows = [[a.get("name", ""), a.get("date", ""), f"{a.get('rarity', 0)}%", a.get("description", "")] for a in latest]
        lines.append(_table(["Achievement", "Unlocked", "Global Rarity", "Description"], rows))

    rec = stats.get("recommended_next", [])
    if rec:
        lines.append("\n**Easiest Missing Targets:**")
        rows = [[a.get("name", ""), f"{a.get('rarity', 0)}%", a.get("description", "")] for a in rec]
        lines.append(_table(["Achievement", "Global Rarity", "Description"], rows))

    return "\n".join(lines)


def format_user_wishlist(items: Any, sort_by: Optional[str] = None, page: int = 0) -> str:
    err = _format_error("User Wishlist", items)
    if err:
        return err

    header = f"### 🌠 Steam Wishlist (Sort: `{sort_by or 'recent'}`, Page {page + 1})"
    if not items:
        return f"{header}\n\nNo wishlist items on this page."

    rows = []
    for item in items:
        disc = item.get("discount", 0)
        disc_str = f"-{disc}%" if isinstance(disc, (int, float)) and disc > 0 else "0%"
        rows.append([
            item.get("appid", "N/A"),
            item.get("name", "Unknown"),
            item.get("price", "N/A"),
            disc_str,
            item.get("priority", 999),
            item.get("date_added", "N/A"),
        ])

    return f"{header}\n**Shown:** {len(items)}\n\n" + _table(
        ["AppID", "Title", "Price", "Discount", "Priority", "Date Added"],
        rows,
    )


def format_store_trends(data: Any) -> str:
    err = _format_error("Steam Store Trends", data)
    if err:
        return err

    cat = data.get("current_view", "specials")
    games = data.get("games", [])
    header = f"### 🏷️ Steam Store Trends (`{cat}` — {len(games)} items)"
    if not games:
        return f"{header}\n\nNo items found."

    rows = []
    for g in games:
        badge = "`[IN LIBRARY]`" if g.get("owned") else "Unowned"
        rows.append([
            g.get("appid", "N/A"),
            g.get("name", "Unknown"),
            g.get("price", "N/A"),
            g.get("discount", "None"),
            g.get("original", "N/A"),
            badge,
        ])

    return header + "\n\n" + _table(["AppID", "Title", "Price", "Discount", "MSRP", "Ownership"], rows)


def format_friends_who_own(data: Any) -> str:
    err = _format_error("Friends Who Own", data)
    if err:
        return err

    lines = [
        "### 👥 Friend Game Ownership",
        f"- **Games Checked:** {', '.join(data.get('games_checked', []))}",
        f"- **Friends Matched:** {data.get('owners_count', 0)} / {data.get('friend_count', 0)}",
    ]
    user_owns = data.get("user_owns", {})
    if user_owns:
        own_parts = [f"{name} ({'Owned' if owned else 'Unowned'})" for name, owned in user_owns.items()]
        lines.append(f"- **Your Library:** {', '.join(own_parts)}")

    friends_data = data.get("friends_data", [])
    if friends_data:
        rows = []
        for f in friends_data:
            matched = f.get("matched_games", [])
            matched_str = ", ".join(
                f"{m.get('game', 'Unknown')} ({m.get('playtime', 0)}h)" if isinstance(m, dict) else str(m)
                for m in matched
            )
            friend_name = f.get("personaname") or f.get("realname") or f.get("steamid", "Unknown")
            status_val = f.get("status")
            status_label = "Online" if status_val == 1 else f"Last seen: {f.get('lastlogoff', 'N/A')}"
            rows.append([friend_name, matched_str, status_label])
        lines.append("")
        lines.append(_table(["Friend", "Owns (Playtime)", "Status"], rows))
    else:
        lines.append("\nNo friends with public libraries own those games.")

    return "\n".join(lines)


def format_friend_comparison(data: Any) -> str:
    err = _format_error("Friend Comparison", data)
    if err:
        return err

    lines = [
        f"### 🤝 Library Comparison with {data.get('friend_name', 'Friend')} ({data.get('status', 'unknown')})",
        f"- **Total Shared Games:** {data.get('total_shared_games', 0)}",
    ]

    favs = data.get("friend_recent_favorites")
    if isinstance(favs, list) and favs:
        lines.append("\n**Friend's Recent Favorites:**")
        rows = [[g.get("name"), g.get("playtime_hours"), g.get("last_played")] for g in favs]
        lines.append(_table(["Title", "Playtime", "Last Played"], rows))

    for label, key in [("Top Shared Multiplayer", "top_shared_multiplayer"), ("Top Shared Games", "top_shared")]:
        items = data.get(key, [])
        if items:
            lines.append(f"\n**{label}:**")
            rows = [
                [g.get("name"), g.get("friend_playtime"), g.get("user_playtime"), g.get("friend_last_played")]
                for g in items
            ]
            lines.append(_table(["Title", "Friend Hours", "Your Hours", "Friend Last Played"], rows))

    return "\n".join(lines)


def format_active_friends(data: Any) -> str:
    err = _format_error("Active Friends", data)
    if err:
        return err

    lines = [f"### 🟢 Active Steam Friends ({data.get('online_count', 0)} online / {data.get('total_friends', 0)} checked)"]
    active = data.get("active_players", [])
    if active:
        rows = [[f.get("name"), f.get("status"), f.get("currently_playing")] for f in active]
        lines.append("")
        lines.append(_table(["Friend", "Status", "Currently Playing"], rows))

    offline = data.get("recently_offline", [])
    if offline:
        lines.append("\n**Recently Offline:**")
        rows = [[f.get("name"), f.get("last_seen")] for f in offline]
        lines.append(_table(["Friend", "Last Seen"], rows))

    return "\n".join(lines)


def format_web_search(data: Any, query: str = "") -> str:
    err = _format_error(f"Web Search ({query})", data)
    if err:
        return err

    lines = [f"### 🌐 Web Search: '{query}'" if query else "### 🌐 Web Search Results"]
    if not data:
        lines.append("No results returned.")
        return "\n".join(lines)

    for idx, r in enumerate(data, 1):
        lines.append(f"{idx}. **{r.get('title', 'Result')}**\n   - {r.get('body', '')}\n   - {r.get('href', '')}")
    return "\n".join(lines)


def format_webpage(data: Any, url: str = "") -> str:
    err = _format_error(f"Webpage ({url})", data)
    if err:
        return err

    content = data.get("content", "") if isinstance(data, dict) else str(data)
    return f"### 📃 Webpage Content: {url}\n\n{content}"


def format_game_evaluation(data: Any, game_name: str = "") -> str:
    """Format composite evaluate_game() intelligence into one unified Markdown dossier."""
    err = _format_error(f"Game Evaluation ({game_name})", data)
    if err:
        return err

    canon_name = data.get("game_name") or game_name
    appid = data.get("appid", "N/A")
    vault_status = data.get("vault_status")
    ownership_badge = "`[IN LIBRARY]`" if vault_status else "`[UNOWNED]`"

    lines = [f"## 🔎 Evaluation Dossier: {canon_name} (`AppID: {appid}`) {ownership_badge}"]
    if vault_status:
        lines.append(
            f"- **Backlog Status:** `{vault_status.get('status', 'N/A')}` | "
            f"**Your Playtime:** `{vault_status.get('hours', 0)}h` | "
            f"**Last Played:** {vault_status.get('last_played', 'Never')}"
        )

    details = data.get("details")
    if details:
        lines.append("")
        lines.append(format_game_details([details] if isinstance(details, dict) else details))

    reviews = data.get("reviews")
    if reviews:
        lines.append("\n---\n")
        lines.append(format_reviews(reviews, game_name=canon_name))

    sentiment = data.get("community_sentiment")
    if sentiment:
        lines.append("\n---\n")
        lines.append(format_community_sentiment(sentiment, game_name=canon_name))

    return "\n".join(lines)


def format_game_wiki(data: Any, game_name: str = "") -> str:
    """Format the compiled Game Wiki & Lore Dossier into Markdown."""
    err = _format_error(f"Game Wiki ({game_name})", data)
    if err:
        return err

    dossier = data.get("dossier")
    if dossier:
        extra_lines = ["\n---"]
        cache_path = data.get("cache_path")
        if cache_path:
            extra_lines.append(f"> 💾 **Cached Dossier:** `{cache_path}`")

        sources = data.get("sources", [])
        if sources:
            extra_lines.append("### 📚 Sources Consulted:")
            for s in sources:
                title = s.get("title", "Source")
                url = s.get("url", "")
                extra_lines.append(f"- [{title}]({url})" if url else f"- {title}")
        return dossier + "\n" + "\n".join(extra_lines)

    return f"### 📖 Game Wiki: {game_name}\nNo wiki dossier could be compiled."


def format_user_activity(data: Any) -> str:
    """Format live Steam activity and recent gaming sessions with milestones into Markdown."""
    err = _format_error("User Activity", data)
    if err:
        return err

    lines = []
    live = data.get("live_status", {})
    if live.get("status") == "in_game":
        gname = live.get("game", "Unknown Game")
        hours_str = f" ({live.get('total_hours')}h in vault)" if live.get("total_hours") is not None else ""
        lines.append(f"### 🎮 Live Status: Playing **{gname}**{hours_str}")
    elif live.get("online"):
        lines.append(f"### 🟢 Live Status: Online ({live.get('persona_state', 'Idle')})")
    else:
        lines.append("### ⚪ Live Status: Offline / Invisible")

    sessions = data.get("sessions", [])
    if not sessions:
        return "\n".join(lines)

    lines.append("\n#### 🕹️ Recent Gaming Sessions & Milestones:")

    for s in sessions:
        s_idx = s.get("session_index", 1)
        t_str = s.get("session_time_str", "Recent")
        games = s.get("games", [])

        lines.append(f"\n**Session {s_idx} ({t_str}):**")
        for g in games:
            gname = g.get("name")
            ghours = g.get("total_hours", 0)
            comp_pct = g.get("completion_pct", 0)
            unlocked_cnt = g.get("total_unlocked", 0)
            total_cnt = g.get("total_available", 0)
            unlocks = g.get("session_unlocks", [])

            if not g.get("has_achievements"):
                lines.append(f"- **{gname}** ({ghours}h total) — *Early Access / No achievements configured*")
            elif not unlocks:
                lines.append(f"- **{gname}** ({ghours}h total) — *No achievements unlocked this session* ({unlocked_cnt}/{total_cnt}, {comp_pct}%)")
            else:
                lines.append(f"- **{gname}** ({ghours}h total | Progress: {unlocked_cnt}/{total_cnt}, {comp_pct}%):")
                for u in unlocks:
                    u_name = u.get("name", u.get("apiname", "Achievement"))
                    u_desc = u.get("desc", "")
                    desc_str = f": *{u_desc}*" if u_desc else ""
                    lines.append(f"  - 🏆 **{u_name}** ({u.get('unlock_time')}){desc_str}")

    return "\n".join(lines)


def format_relative_time(ts: Optional[float]) -> str:
    """Calculates human-friendly relative time (e.g. '5 minutes ago', 'yesterday', 'Oct 28, 2026')."""
    if not ts or ts <= 0:
        return "never"

    now = time.time()
    diff = now - ts

    if diff < 0:
        return "just now"
    if diff < 60:
        return "just now"
    if diff < 3600:
        mins = int(diff // 60)
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    if diff < 86400:
        hours = int(diff // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    if diff < 172800:
        return "yesterday"
    if diff < 86400 * 30:
        days = int(diff // 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"

    try:
        dt = datetime.fromtimestamp(ts)
        return dt.strftime("%b %d, %Y")
    except Exception:
        return "past"


def format_now_playing(data: Any) -> str:
    """
    Renders an agent-first, macro-friendly Markdown representation of current Steam gaming reality.
    Mirrors MusicImp's get_now_playing structure:
    - In-Game: Spotlight hero with title, AppID, vault hours, and tags.
    - Not In-Game: Strict one-liner indicating Online or Offline status (with last seen time).
    """
    err = _format_error("Steam Status", data)
    if err:
        return err

    status = data.get("status")
    if status == "in_game":
        game = data.get("game", "Unknown Game")
        appid = data.get("appid")
        appid_str = f" (AppID: {appid})" if appid else ""
        hours = data.get("total_hours")
        hours_str = f" • [{hours}h in vault]" if hours is not None else ""

        lines = [
            "### 🎮 Now Playing",
            f"**{game}**{appid_str}{hours_str}",
        ]
        tags = data.get("tags") or []
        if tags:
            tags_str = " • ".join(tags)
            lines.append(f"- **Tags**: {tags_str}")
        return "\n".join(lines)

    if data.get("online"):
        persona = data.get("persona_state", "Online")
        return f"### 🟢 Steam Status: Online ({persona})"

    last_logoff = data.get("last_logoff")
    time_ago = format_relative_time(last_logoff) if last_logoff else None
    if time_ago and time_ago not in ("never", "past"):
        return f"### ⚪ Steam Status: Offline (last seen {time_ago})"
    return "### ⚪ Steam Status: Offline"


def format_personalized_calendar(data: Any) -> str:
    """Format personalized release calendar and multi-horizon schedules into compact, high-signal Markdown."""
    err = _format_error("Personalized Calendar", data)
    if err:
        return err

    def _badge(g: dict, include_date: bool = False) -> str:
        parts = []
        price = g.get("price", "TBA")
        disc = g.get("discount_pct", 0)
        parts.append(f"{price} -{disc}%" if disc > 0 else price)

        if g.get("is_early_access"):
            parts.append("EA")

        pct = g.get("review_pct")
        cnt = g.get("review_count")
        if pct is not None and cnt is not None:
            parts.append(f"{pct}%/{cnt}")

        if include_date and g.get("release_raw"):
            parts.append(g["release_raw"].split(",")[0].strip())

        return " | ".join(parts)

    lines = []
    taste = data.get("taste_profile", [])
    taste_str = ", ".join(t.get("name", "") for t in taste[:5])
    lines.append("### Personalized Release Calendar")
    if taste_str:
        lines.append(f"Affinities (50/50): {taste_str} (Note: Early Access marked [EA], unmarked = Full 1.0)\n")

    # Horizon 1: Last 7 Days (Top 8 high-signal drops)
    h1 = data.get("horizon_1_last_7_days", [])
    if h1:
        lines.append("#### Last 7 Days Highlights")
        for g in h1[:8]:
            wl = " [WL]" if g.get("is_wishlisted") else ""
            owned = " [Owned]" if g.get("is_owned") else ""
            tags = g.get("matched_tags", [])
            tag_str = f" — {', '.join(tags[:2])}" if tags else ""
            lines.append(f"- {g.get('name')} ({g.get('appid')}){wl}{owned} [{_badge(g, include_date=True)}]{tag_str}")

    # Horizon 3: Current Week Schedule (Compact day-by-day, up to 5 max per active day)
    h3 = data.get("horizon_3_upcoming_week", {})
    days = h3.get("days", [])
    if days:
        lines.append("\n#### This Week")
        for d in days:
            games = d.get("games", [])
            is_today = d.get("is_today", False)
            if not games and not is_today:
                continue

            today_mark = " (TODAY)" if is_today else ""
            header = f"**{d.get('weekday')} {d.get('display_date')}{today_mark}:**"
            if not games:
                lines.append(f"{header} No tracked drops.")
                continue

            lines.append(header)
            for g in games[:5]:
                wl = " [WL]" if g.get("is_wishlisted") else ""
                tags = g.get("matched_tags", [])
                tag_str = f" ({', '.join(tags[:2])})" if tags else ""
                lines.append(f"  - {g.get('name')} ({g.get('appid')}){wl} [{_badge(g)}]{tag_str}")

    # Beyond Week / Upcoming Highlights (Top 5)
    beyond = h3.get("beyond_week", [])
    if beyond:
        lines.append("\n#### Upcoming (Next 14 Days)")
        for g in beyond[:5]:
            wl = " [WL]" if g.get("is_wishlisted") else ""
            ea = " [EA]" if g.get("is_early_access") else ""
            rel_short = (g.get("release_raw") or "").split(",")[0].strip()
            tags = g.get("matched_tags", [])
            tag_str = f" — {', '.join(tags[:2])}" if tags else ""
            lines.append(f"- {g.get('name')} ({g.get('appid')}){wl}{ea} [{rel_short}]{tag_str}")

    return "\n".join(lines)

