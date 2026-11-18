"""
Game Wiki, Guides, Web Mechanics & Lore Synthesis Dossiers.
Supports multi-stage source selection, disk caching with expiry, and compact/full modes.
"""

from bs4 import BeautifulSoup
import concurrent.futures
from datetime import datetime
import json
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote

from ddgs import DDGS
import requests
import trafilatura

from core.ai_tools import aiCall, clean_json_for_ai, get_summarizer_model
import core.paths as paths
import core.text_utils as text_utils
from core.safe_tool import safe_tool
from core.steam_store import get_steam_app_details, get_steam_app_info
from core.web_tools import get_hltb_data, get_steam_bypass, get_steam_bypass_with_referer


def _sanitize_slug(name: str) -> str:
    """Create filesystem-friendly slug for caching game dossiers."""
    return re.sub(r'[^a-zA-Z0-9_\-]+', '_', name.strip().lower()).strip('_')


def get_game_wiki_cache_path(appid: int, game_name: str, mode: str = "full") -> Path:
    """Resolve destination path in data/game_wikis/{appid}_{slug}_{mode}.md."""
    slug = _sanitize_slug(game_name)
    mode_clean = (mode or "full").lower().strip()
    cache_dir = paths.get_base_dir() / "data" / "game_wikis"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{appid}_{slug}_{mode_clean}.md"


def load_cached_wiki(appid: int, game_name: str, mode: str = "full", max_age_days: float = 7.0) -> Optional[dict]:
    """
    Reads cached game wiki markdown for the requested mode if present and younger than max_age_days.
    Returns standard payload dictionary or None if cache miss / expired.
    """
    mode_clean = (mode or "full").lower().strip()
    path = get_game_wiki_cache_path(appid, game_name, mode=mode_clean)
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
        age_seconds = time.time() - mtime
        if age_seconds > (max_age_days * 86400):
            return None  # Cache expired

        content = path.read_text(encoding="utf-8")
        meta = {}
        meta_match = re.search(r'<!--\s*WIKI_CACHE_METADATA:\s*({.*?})\s*-->', content, re.DOTALL)
        if meta_match:
            try:
                meta = json.loads(meta_match.group(1))
            except Exception:
                pass

        cached_mode = meta.get("mode")
        if cached_mode and cached_mode.lower() != mode_clean:
            return None

        dossier = re.sub(r'<!--\s*WIKI_CACHE_METADATA:.*?-->\n*', '', content, flags=re.DOTALL).strip()
        return {
            "game": meta.get("game", game_name),
            "appid": appid,
            "mode": mode_clean,
            "dossier": dossier,
            "hltb": meta.get("hltb", {}),
            "sources": meta.get("sources", []),
            "cached": True,
            "cache_path": str(path),
            "cached_at": meta.get("cached_at", time.ctime(mtime)),
            "_tokens": {"in": 0, "out": 0}
        }
    except Exception as e:
        print(f"Warning: Failed reading wiki cache for {appid}: {e}")
        return None


def save_wiki_to_cache(appid: int, game_name: str, dossier: str, hltb: dict, sources: list, mode: str = "full") -> Path:
    """Persists markdown dossier to data/game_wikis/{appid}_{slug}_{mode}.md with metadata header."""
    mode_clean = (mode or "full").lower().strip()
    path = get_game_wiki_cache_path(appid, game_name, mode=mode_clean)
    meta = {
        "cached_at": datetime.utcnow().isoformat() + "Z",
        "timestamp": time.time(),
        "appid": appid,
        "game": game_name,
        "mode": mode_clean,
        "hltb": hltb,
        "sources": sources
    }
    file_content = f"<!-- WIKI_CACHE_METADATA: {json.dumps(meta)} -->\n\n{dossier}\n"
    path.write_text(file_content, encoding="utf-8")
    return path


def get_steam_guides_index(appid: int, limit: int = 8) -> List[dict]:
    """Scrape top-rated Steam community guides index (file IDs, titles, preview URLs)."""
    headers, cookies = get_steam_bypass_with_referer(appid)
    url = f"https://steamcommunity.com/app/{appid}/guides/?browsefilter=toprated&p=1"
    try:
        r = requests.get(url, headers=headers, cookies=cookies, timeout=10)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, 'html.parser')
        guides = []
        seen = set()
        for a in soup.find_all('a', href=True):
            href = a['href']
            if 'sharedfiles/filedetails/?id=' in href:
                m = re.search(r'id=(\d+)', href)
                if not m:
                    continue
                gid = m.group(1)
                if gid in seen:
                    continue
                seen.add(gid)
                title_text = a.get_text(separator=' ', strip=True)
                if not title_text:
                    continue
                guides.append({
                    "id": gid,
                    "title": title_text[:140],
                    "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={gid}"
                })
                if len(guides) >= limit:
                    break
        return guides
    except Exception as e:
        print(f"Warning: Failed to fetch Steam guides index for {appid}: {e}")
        return []


def get_steam_guide_details(guide_ids: List[str]) -> List[dict]:
    """Fetch official author descriptions and tags for guides via Steam Remote Storage API."""
    if not guide_ids:
        return []
    url = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
    data = {"itemcount": len(guide_ids)}
    for idx, gid in enumerate(guide_ids):
        data[f"publishedfileids[{idx}]"] = str(gid)
    try:
        r = requests.post(url, data=data, timeout=10)
        if r.status_code != 200:
            return []
        items = r.json().get("response", {}).get("publishedfiledetails", [])
        out = []
        for item in items:
            title = item.get("title")
            if not title:
                continue
            desc = item.get("description", "")
            clean_desc = re.sub(r'\[/?(?:b|i|u|h\d|url|code|quote|list|\*)\]', '', desc)
            clean_desc = re.sub(r'\[img\].*?\[/img\]', '', clean_desc)
            clean_desc = re.sub(r'\[url=[^\]]*\](.*?)\[/url\]', r'\1', clean_desc)
            clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()
            out.append({
                "id": str(item.get("publishedfileid")),
                "title": title,
                "desc": clean_desc[:2500],
                "views": item.get("views", 0),
                "subs": item.get("subscriptions", 0),
                "tags": [t.get("tag") for t in item.get("tags", []) if isinstance(t, dict)],
                "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={item.get('publishedfileid')}"
            })
        return out
    except Exception as e:
        print(f"Warning: Failed to fetch Steam guide details: {e}")
        return []


def get_web_wiki_index(game_name: str, limit: int = 5) -> List[dict]:
    """Search for community lore wikis and world setting articles."""
    query = f'"{game_name}" (wiki OR lore OR factions OR "world setting") -site:steampowered.com'
    try:
        results = DDGS().text(query, max_results=limit * 2)
        out = []
        for r in results:
            title = r.get("title", "")
            href = r.get("href", "")
            body = r.get("body", "")
            if not href or any(junk in href.lower() for junk in ["/category:", "/special:", "/file:", "login", "signup"]):
                continue
            if not text_utils.text_mentions_game(game_name, title, body, href):
                continue
            out.append({"title": title, "url": href, "snippet": body})
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        print(f"Warning: Web wiki search error for {game_name}: {e}")
        return []


def get_web_mechanics_index(game_name: str, limit: int = 4) -> List[dict]:
    """Fallback search for gameplay mechanics and guide articles if Steam guides are absent."""
    query = f'"{game_name}" (gameplay OR mechanics OR build OR guide) -site:steampowered.com'
    try:
        results = DDGS().text(query, max_results=limit * 2)
        out = []
        for r in results:
            title = r.get("title", "")
            href = r.get("href", "")
            body = r.get("body", "")
            if not href or any(junk in href.lower() for junk in ["/category:", "/special:", "/file:", "login", "signup"]):
                continue
            if not text_utils.text_mentions_game(game_name, title, body, href):
                continue
            out.append({"title": title, "url": href, "snippet": body})
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        print(f"Warning: Web mechanics search error for {game_name}: {e}")
        return []


def _extract_page_markdown(url: str, max_chars: int = 3500) -> str:
    """Download and extract clean article markdown from a URL using trafilatura."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        extracted = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            include_links=False,
            output_format="markdown",
        )
        if not extracted:
            return ""
        clean = re.sub(r'\n{3,}', '\n\n', extracted).strip()
        return clean[:max_chars]
    except Exception as e:
        print(f"Warning: Failed to extract markdown from {url}: {e}")
        return ""


def _select_wiki_sources_with_llm(
    game_name: str,
    mechanics_candidates: List[dict],
    lore_candidates: List[dict],
) -> Tuple[List[dict], List[dict], int, int]:
    """
    Sub-LLM Selector: Evaluates candidates from the Dual-Lane Index and picks
    the top 1-2 mechanics sources and top 1 lore source, filtering out translation mods and spam.
    """
    in_tok, out_tok = 0, 0
    if not mechanics_candidates and not lore_candidates:
        return [], [], 0, 0

    selector_system = f"""You are a research selector choosing the best source material for a video game wiki and lore dossier on '{game_name}'.
Review the candidate lists below:
1. 'mechanics_candidates': Select up to 2 best sources for gameplay mechanics, beginner loop, character classes, or buildcrafting. (Ignore joke/meme guides, translation mod notes, or video spam).
2. 'lore_candidates': Select up to 1 best source for world lore, factions, narrative setting, or universe premise.

Respond STRICTLY with valid JSON:
{{"selected_mechanics_ids": ["<id or url>", ...], "selected_lore_urls": ["<url>"]}}"""

    candidates_summary = {
        "game": game_name,
        "mechanics_candidates": [
            {"id": c.get("id") or c.get("url"), "title": c.get("title"), "snippet": (c.get("desc") or c.get("snippet", ""))[:160]}
            for c in mechanics_candidates[:8]
        ],
        "lore_candidates": [
            {"url": c.get("url"), "title": c.get("title"), "snippet": c.get("snippet", "")[:160]}
            for c in lore_candidates[:5]
        ]
    }

    selected_mech = []
    selected_lore = []

    try:
        raw_res, in_tok, out_tok = aiCall(
            data=json.dumps(candidates_summary),
            system=selector_system,
            return_tokens=True,
            model=get_summarizer_model(),
        )
        m = re.search(r'\{.*\}', raw_res, re.DOTALL)
        if m:
            parsed = json.loads(m.group(0))
            mech_keys = set(parsed.get("selected_mechanics_ids", []))
            lore_keys = set(parsed.get("selected_lore_urls", []))
            selected_mech = [c for c in mechanics_candidates if (c.get("id") in mech_keys or c.get("url") in mech_keys)][:2]
            selected_lore = [c for c in lore_candidates if c.get("url") in lore_keys][:1]
    except Exception as e:
        print(f"Warning: LLM source selection fallback: {e}")

    # Heuristic fallback if LLM returned empty or failed
    if not selected_mech and mechanics_candidates:
        ranked = sorted(
            mechanics_candidates,
            key=lambda c: any(k in (c.get("title", "") + " " + c.get("desc", "")).lower() for k in ["guide", "build", "basic", "mechanic", "class", "weapon"]),
            reverse=True
        )
        selected_mech = ranked[:2]

    if not selected_lore and lore_candidates:
        ranked = sorted(
            lore_candidates,
            key=lambda c: any(k in c.get("url", "").lower() for k in ["wiki", "fandom", "lore"]),
            reverse=True
        )
        selected_lore = ranked[:1]

    return selected_mech, selected_lore, in_tok, out_tok


@safe_tool
def compile_game_wiki(game_name: str, mode: str = "full", force_refresh: bool = False, max_age_days: float = 7.0) -> dict:
    """
    Compiles a comprehensive, factual Game Wiki & Lore Dossier for any game (including brand new releases)
    by pulling Steam Community Guides, community wikis, HowLongToBeat completion times, and Store specifications
    via a multi-stage selector and sub-LLM synthesis pipeline.

    Args:
        game_name: Title of the video game to investigate.
        mode: 'full' (dense 5-section encyclopedia) or 'compact' (concise high-signal brief under 600 words).
        force_refresh: When True, bypasses local markdown cache in data/game_wikis/.
        max_age_days: Cache validity window (default 7 days).
    """
    app_info = get_steam_app_info(game_name)
    if not app_info or 'id' not in app_info or not app_info['id']:
        return {"error": f"Game '{game_name}' not found on Steam."}

    appid = int(app_info['id'][0])
    canonical_name = app_info.get('name', [game_name])[0] if isinstance(app_info.get('name'), list) else app_info.get('name', game_name)
    mode_clean = (mode or "full").lower().strip()

    # Check local markdown cache first (O(1) hit for BakaBot / agent tools)
    if not force_refresh:
        cached_result = load_cached_wiki(appid, canonical_name, mode=mode_clean, max_age_days=max_age_days)
        if cached_result:
            return cached_result

    total_in = 0
    total_out = 0

    # Stage 1: Parallel Fetch of Store Specs, HLTB, Steam Guides Index, and Web Lore Index
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        f_store = executor.submit(get_steam_app_details, appid)
        f_hltb = executor.submit(get_hltb_data, canonical_name)
        f_guides = executor.submit(get_steam_guides_index, appid, limit=8)
        f_lore = executor.submit(get_web_wiki_index, canonical_name, limit=5)

        store_data = f_store.result() or {}
        raw_hltb = f_hltb.result() or []
        guides_index = f_guides.result() or []
        lore_index = f_lore.result() or []

    hltb_data = {}
    if isinstance(raw_hltb, list) and raw_hltb:
        first = raw_hltb[0]
        if hasattr(first, '__dict__'):
            hltb_data = vars(first)
        elif isinstance(first, dict):
            hltb_data = first
    elif isinstance(raw_hltb, dict):
        hltb_data = raw_hltb

    # If Steam has 0 guides, engage web mechanics fallback
    mechanics_candidates = guides_index
    if not mechanics_candidates:
        mechanics_candidates = get_web_mechanics_index(canonical_name, limit=5)

    # Stage 2: Smart Sub-LLM Selector
    selected_mech, selected_lore, sel_in, sel_out = _select_wiki_sources_with_llm(
        canonical_name, mechanics_candidates, lore_index
    )
    total_in += sel_in
    total_out += sel_out

    # Stage 3: Fetch Content from Selected Sources
    mechanics_content_blocks = []
    sources_consulted = []

    # If selected mechanics sources are Steam guides, fetch details via API
    steam_guide_ids = [c["id"] for c in selected_mech if "id" in c]
    if steam_guide_ids:
        guide_details = get_steam_guide_details(steam_guide_ids)
        for gd in guide_details:
            mechanics_content_blocks.append(
                f"### [Steam Guide]: {gd['title']}\n**Tags:** {', '.join(gd.get('tags', []))}\n{gd['desc']}"
            )
            sources_consulted.append({"title": f"Steam Guide: {gd['title']}", "url": gd['url']})

    # For web mechanics sources (if any selected)
    for wm in selected_mech:
        if "url" in wm and "id" not in wm:
            txt = _extract_page_markdown(wm["url"], max_chars=3000)
            if txt:
                mechanics_content_blocks.append(f"### [Web Guide]: {wm.get('title', 'Guide')}\n{txt}")
                sources_consulted.append({"title": wm.get('title', 'Web Guide'), "url": wm["url"]})

    # For lore sources
    lore_content_blocks = []
    for wl in selected_lore:
        txt = _extract_page_markdown(wl["url"], max_chars=3500)
        if txt:
            lore_content_blocks.append(f"### [Wiki / Lore]: {wl.get('title', 'Lore')}\n{txt}")
            sources_consulted.append({"title": wl.get('title', 'Lore Wiki'), "url": wl["url"]})

    # Stage 4: Synthesizer Assembly
    store_meta = {
        "title": canonical_name,
        "appid": appid,
        "developer": ", ".join(store_data.get("developers", [])) if isinstance(store_data.get("developers"), list) else store_data.get("developers", "Unknown"),
        "publisher": ", ".join(store_data.get("publishers", [])) if isinstance(store_data.get("publishers"), list) else store_data.get("publishers", "Unknown"),
        "release_date": (store_data.get("release_date") or {}).get("date", "Unknown") if isinstance(store_data.get("release_date"), dict) else "Unknown",
        "genres": [g.get("description") for g in store_data.get("genres", []) if isinstance(g, dict)],
        "short_description": store_data.get("short_description", ""),
        "detailed_description": re.sub(r'<[^>]+>', ' ', (store_data.get("about_the_game") or store_data.get("detailed_description", ""))[:1800]),
    }

    combined_input = f"""
GAME INTEL:
- Title: {store_meta['title']} (AppID: {store_meta['appid']})
- Developer: {store_meta['developer']} | Publisher: {store_meta['publisher']}
- Release Date: {store_meta['release_date']}
- Genres: {', '.join(store_meta['genres'])}
- HowLongToBeat: Main Story {hltb_data.get('main_story', 'N/A')}h | Main+Extra {hltb_data.get('main_extra', 'N/A')}h | Completionist {hltb_data.get('completionist', 'N/A')}h
- Official Overview: {store_meta['short_description']}
- Official Feature Details: {store_meta['detailed_description'][:1200]}

COMMUNITY MECHANICS & BUILDS:
{chr(10).join(mechanics_content_blocks) if mechanics_content_blocks else "No community build guides available. Rely on official features."}

WORLD LORE & FACTIONS:
{chr(10).join(lore_content_blocks) if lore_content_blocks else "No extended lore wiki pages found. Rely on official premise."}
"""

    if mode == "compact":
        synth_system = f"""You are an elite video game intelligence researcher compiling a Compact Game Wiki & Lore Brief for an AI agent.
Synthesize the provided official specs, HowLongToBeat estimates, community guides, and lore text for '{canonical_name}' into a concise, high-signal Markdown summary (under 600 words).

Required Document Structure:
# {canonical_name} — Compact Game Brief

## 1. 📋 Meta & HLTB
Table with: Developer, Publisher, Release Date, Status (Early Access / 1.0), Genres, HLTB Hours (Main / Extra / Completionist).
Followed by a concise 1-sentence core premise summary.

## 2. ⚔️ Gameplay Loop & Perspective
2-3 bullet points defining camera perspective, mechanics, run flow, and win/loss loop.

## 3. 🧙 Meta Builds & Synergies
Top 2-3 build archetypes or class/weapon synergies documented by player guides.

## 4. 💡 Vital Survival Rules
Top 3 pro-tips or beginner rules from community guides.

Tone: Dense, objective, factual. Eliminate PR marketing adjectives, hype, and conversational filler."""
    else:
        synth_system = f"""You are an elite video game intelligence researcher compiling a Game Wiki & Lore Dossier for an AI agent knowledge base.
Synthesize the provided official specs, HowLongToBeat estimates, community guides, and lore text for '{canonical_name}' into a dense, structured Markdown document.

Required Document Structure:
# {canonical_name} — Game Wiki & Lore Dossier

## 1. 📋 Overview & Meta
Table with: Title, Steam AppID, Developer, Publisher, Release Date, Status (Early Access / 1.0), Genres, HLTB Estimates (Main, Extra, Completionist).
Followed by a concise 1-2 sentence core premise summary.

## 2. 🌍 World, Setting & Narrative Premise
World setting, narrative hook, atmosphere, factions/lore background.

## 3. ⚔️ Core Gameplay Loop & Combat Mechanics
Perspective, run flow, progression loop, win/loss conditions, resource/economy rules.

## 4. 🧙 Classes, Builds & Synergies
Playable characters/classes, stat scaling, build archetypes, weapon/item synergies documented by player guides.

## 5. 💡 Pro Tips & Early-Game Strategy
Tactical advice, common beginner mistakes, shop/stat priorities from community guides.

Tone: Dense, objective, factual. Eliminate PR marketing adjectives, hype, and conversational filler."""

    try:
        dossier_text, syn_in, syn_out = aiCall(
            data=combined_input,
            system=synth_system,
            return_tokens=True,
            model=get_summarizer_model(),
        )
        total_in += syn_in
        total_out += syn_out
    except Exception as e:
        dossier_text = f"### 📖 {canonical_name} Dossier\nFailed to synthesize dossier: {e}\n\n**Official Premise:**\n{store_meta['short_description']}"

    # Persist the dossier to disk cache for future O(1) reads and tool grepping
    cache_path = save_wiki_to_cache(appid, canonical_name, dossier_text, hltb_data, sources_consulted, mode=mode_clean)

    return {
        "game": canonical_name,
        "appid": appid,
        "mode": mode_clean,
        "dossier": dossier_text,
        "hltb": hltb_data,
        "sources": sources_consulted,
        "cached": False,
        "cache_path": str(cache_path),
        "_tokens": {"in": total_in, "out": total_out}
    }
