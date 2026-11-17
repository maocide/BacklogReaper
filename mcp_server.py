#!/usr/bin/env python3
"""
Backlog Reaper MCP Server
Exposes BacklogReaper vault, game intelligence, community sentiment, and deal-hunting tools
to any Model Context Protocol (MCP) client such as BakaBot.
"""

import sys
import threading
import time
from typing import List, Optional

import core.paths as paths
import core.settings as settings
import core.vault as vault
import core.game_intelligence as game_intelligence
import core.community_sentiment as community_sentiment
import core.web_tools as web_tools
import core.diagnostics as diagnostics
import core.formatters as formatters
from core.vibe_engine import VibeEngine
from mcp.server.mcpserver import MCPServer

# Initialize core paths, settings, and database (with WAL mode enabled)
paths.ensure_dirs()
settings.reload()
vault.init_db()

# Create MCP Server
mcp = MCPServer(
    name="BacklogReaper",
    instructions="Backlog Reaper game vault, community intelligence, and deal hunting assistant."
)

# Concurrency guard for background library sync
_sync_lock = threading.Lock()
_is_syncing = False


def _run_library_sync():
    """Runs a single Steam library update + VibeEngine embedding refresh."""
    global _is_syncing
    if not _sync_lock.acquire(blocking=False):
        print("[MCP Sync] Sync already in progress. Skipping cycle.", file=sys.stderr)
        return

    _is_syncing = True
    try:
        steam_user = settings.STEAM_USER
        if not steam_user or not settings.STEAM_API_KEY:
            print("[MCP Sync] Steam credentials not set. Skipping sync.", file=sys.stderr)
            return

        print(f"[MCP Sync] Starting Steam library sync for '{steam_user}'...", file=sys.stderr)
        for progress in vault.update(steam_user):
            # Consume progress generator
            pass

        print("[MCP Sync] Refreshing VibeEngine embeddings...", file=sys.stderr)
        vibes = VibeEngine.get_instance()
        vibes.ingest_library()
        print("[MCP Sync] Steam library & vibe sync complete!", file=sys.stderr)
    except Exception as e:
        print(f"[MCP Sync] Sync encountered error: {e}", file=sys.stderr)
    finally:
        _is_syncing = False
        _sync_lock.release()


def _background_sync_worker(interval_seconds: int = 1200):
    """
    Background daemon worker that runs periodic Steam sync every 20 minutes (1200s),
    plus an initial check on server startup.
    """
    # Startup check: if DB empty or last update > 20 mins ago, sync now
    try:
        if vault.get_games_count() == 0 or vault.get_elapsed_since_update() > interval_seconds:
            print("[MCP Sync] Initial sync check triggered.", file=sys.stderr)
            _run_library_sync()
    except Exception as e:
        print(f"[MCP Sync] Initial startup check error: {e}", file=sys.stderr)

    while True:
        time.sleep(interval_seconds)
        try:
            if vault.get_elapsed_since_update() > interval_seconds:
                print("[MCP Sync] 20-minute interval sync triggered.", file=sys.stderr)
                _run_library_sync()
        except Exception as e:
            print(f"[MCP Sync] Interval worker error: {e}", file=sys.stderr)


# ==========================================
# MCP TOOLS EXPOSED TO BAKABOT & CLIENTS
# ==========================================

@mcp.tool()
def vault_search(
    tags: Optional[List[str]] = None,
    exclude_tags: Optional[List[str]] = None,
    tag_mode: str = "all",
    status: Optional[List[str]] = None,
    min_playtime: Optional[int] = None,
    max_playtime: Optional[int] = None,
    hltb_max: Optional[int] = None,
    include_unknown_hltb: bool = False,
    min_review_score: Optional[int] = None,
    name: Optional[str] = None,
    sort_by: str = "shortest",
    page: int = 0,
    seed: Optional[int] = None
) -> str:
    """
    Search the user's owned Steam game backlog with structured filters (returns Markdown).
    Automatically projects natural tag queries/jargon ('bullet heaven', 'deckbuilder', 'survivor-like')
    onto canonical vault tags and normalizes titles ('Dark Souls 3' -> 'DARK SOULS III').
    tag_mode: 'all' (default) matches every requested tag group; 'any' matches any group.
    sort_by: 'relevance', 'shortest', 'longest', 'recent', 'name', 'score_best', 'score_worst', or 'random'.
    """
    payload = vault.advanced_search(
        tags=tags,
        exclude_tags=exclude_tags,
        tag_mode=tag_mode,
        status=status,
        min_playtime=min_playtime,
        max_playtime=max_playtime,
        hltb_max=hltb_max,
        include_unknown_hltb=include_unknown_hltb,
        min_review_score=min_review_score,
        name=name,
        sort_by=sort_by,
        page=page,
        seed=seed,
    )
    return formatters.format_vault_search(payload, is_recent=(sort_by == "recent"))


@mcp.tool()
def vault_search_batch(game_names: List[str]) -> str:
    """
    Verify ownership or look up multiple games by title in the user's local Steam library.
    """
    results = vault.vault_search_batch(game_names)
    return formatters.format_vault_search(results, title="Batch Vault Lookup")


@mcp.tool()
def get_library_stats() -> str:
    """
    Get aggregated audit statistics for the user's Steam library.
    Includes total games owned, total hours played, shame percentage (unplayed games),
    completion rates, and top genre breakdown.
    """
    stats = vault.get_library_stats()
    return formatters.format_library_stats(stats)


@mcp.tool()
def get_user_tags(recent_days: Optional[int] = None, limit: int = 50) -> str:
    """
    Retrieve the user's top played genres.
    Leave recent_days empty for lifetime stats, or pass a number (e.g. 30 or 60)
    to see what genres the user has been playing recently.
    """
    tags = vault.get_all_tags(recent_days=recent_days, limit=limit)
    return formatters.format_user_tags(tags, recent_days=recent_days, limit=limit)


@mcp.tool()
def find_similar_games(game_name: str, limit: int = 10, status: Optional[List[str]] = None) -> str:
    """
    Find games in the user's OWNED backlog that match a target title.
    Uses hybrid matching: gameplay mechanics (tags) + atmospheric DNA (SentenceTransformer vibe embeddings).
    Pass status (e.g. ['Unplayed', 'Bounced']) to restrict matches to unfinished games.
    """
    matches = game_intelligence.generate_contextual_dna(game_name, limit, status=status)
    return formatters.format_similar_games(matches, target_game=game_name)


@mcp.tool()
def search_by_vibe(
    query: str,
    status: Optional[List[str]] = None,
    hltb_max: Optional[int] = None,
    limit: int = 10
) -> str:
    """
    Search the user's owned library by abstract mood, atmosphere, or narrative feel using embeddings.
    Use vault_search for crisp genres/tags; use search_by_vibe for themes/vibes like
    'melancholic rainy cyberpunk detective' or 'cozy late-night puzzle relaxing'.
    Optionally filter by backlog status (e.g. ['Unplayed']) or maximum HLTB hours.
    """
    vibe = VibeEngine.get_instance()
    if not vibe.cache:
        vibe.ingest_library()
    results = vibe.search(query, top_k=limit, status=status, hltb_max=hltb_max)
    return formatters.format_vibe_search(results, query=query)


@mcp.tool()
def search_steam_store(search_term: str, sort_by: str = "relevance", limit: int = 10) -> str:
    """
    Search the general Steam store catalog for game titles, AppIDs, prices, and ownership flags.
    Use sort_by='recent' for newly released titles matching the search term.
    """
    results = game_intelligence.search_steam_store(term=search_term, sort_by=sort_by, limit=limit)
    return formatters.format_store_search(results, search_term=search_term, sort_by=sort_by)


@mcp.tool()
def get_game_details(game_names: List[str]) -> str:
    """
    Fetch comprehensive game intel from Steam and CheapShark:
    pricing, discount percentage, DLCs, HLTB estimates, description, and deals.
    """
    details = game_intelligence.get_batch_game_details(game_names)
    return formatters.format_game_details(details)


@mcp.tool()
def get_reviews(game_name: str, limit: int = 10, summarize: bool = False) -> str:
    """
    Fetch actual Steam player reviews, recent telemetry metrics, sentiment summary, and optional sub-LLM consensus digest.
    """
    reviews = game_intelligence.get_reviews_byname(game_name, count=limit, summarize=summarize)
    if isinstance(reviews, dict):
        reviews.pop("_tokens", None)
    return formatters.format_reviews(reviews, game_name=game_name)


@mcp.tool()
def evaluate_game(game_name: str, deep: bool = False) -> str:
    """
    One-shot game evaluation combining library ownership, Store/CheapShark/HLTB details, review telemetry, and optional deep digest + community sentiment.
    """
    report = game_intelligence.evaluate_game(game_name=game_name, deep=deep)
    if isinstance(report, dict):
        report.pop("_tokens", None)
    return formatters.format_game_evaluation(report, game_name=game_name)


@mcp.tool()
def get_community_sentiment(game_name: str) -> str:
    """
    Deep multi-community consensus report:
    Synthesizes current discourse across Steam Community Forums, 4chan (/v/ and /vg/),
    and Reddit gamer discussions.
    """
    data = community_sentiment.get_community_sentiment(game_name)
    if isinstance(data, dict):
        data.pop("_tokens", None)
    return formatters.format_community_sentiment(data, game_name=game_name)


@mcp.tool()
def search_reddit_discussions(game_name: str, limit: int = 5) -> str:
    """
    Directly extracts authentic Reddit gamer reviews, threads, and discourse for a game
    via clean search syndication (bypassing anti-bot filters and Turnstile).
    """
    results = web_tools.search_reddit_discussions(game_name, limit=limit)
    return formatters.format_reddit_discussions(results, game_name=game_name)


@mcp.tool()
def get_game_deals(game_name: str) -> str:
    """
    Search CheapShark for current discounts, lowest historic prices, and store deals for a game.
    """
    app_info = game_intelligence.get_steam_app_info(game_name)
    appid = app_info["id"][0] if app_info and "id" in app_info else None
    deals = game_intelligence.get_game_deals(game_name, appid)
    return formatters.format_game_deals(deals, game_name=game_name, appid=appid)


@mcp.tool()
def get_game_news(game_name: str, limit: int = 5) -> str:
    """
    Retrieve latest official Steam patch notes, developer events, and announcements for a game.
    """
    news = community_sentiment.get_game_news(game_name, limit=limit)
    return formatters.format_game_news(news, game_name=game_name)


@mcp.tool()
def get_achievements(game_name: str = "", appid: Optional[int] = None, page: Optional[int] = None) -> str:
    """
    Get Steam achievement stats and progress for an owned game.
    Default (page=None): Returns a dashboard with completion percentage, total achievements,
    latest unlocks, and recommended easiest missing achievements.
    If page (0, 1, 2...) is specified: Returns a paginated list of 10 locked achievements sorted by rarity.
    """
    target_appid = appid if appid is not None else -1
    stats = game_intelligence.get_achievement_stats(appid=target_appid, game_name=game_name, page=page)
    return formatters.format_achievements(stats, game_name=game_name)


@mcp.tool()
def run_system_diagnostics() -> str:
    """
    Run a full diagnostic health check across all BacklogReaper subsystems,
    databases, APIs (Steam Store, Steam Reviews, CheapShark, Steam News),
    and web search scraping syndication.
    """
    return diagnostics.run_system_diagnostics("MCP Diagnostic Run")


# ==========================================
# SERVER RUNNER
# ==========================================

def start_server(transport: str = "stdio"):
    """Starts the background Steam sync worker and launches the MCP server."""
    # Start background sync thread as daemon
    sync_thread = threading.Thread(target=_background_sync_worker, daemon=True, name="SteamSyncDaemon")
    sync_thread.start()
    print(f"[BacklogReaper MCP] Daemon started. Launching MCP Server over transport '{transport}'...", file=sys.stderr)

    # Run MCP server
    mcp.run(transport=transport)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Backlog Reaper MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio",
                        help="Transport protocol to use (default: stdio)")
    args = parser.parse_args()
    start_server(transport=args.transport)
