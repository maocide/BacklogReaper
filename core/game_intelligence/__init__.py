"""
Unified Game Intelligence Subpackage.
Consolidates domain-specific intelligence modules under clean, modular namespaces:
- core.game_intelligence.store (Catalog, Search, Wishlist, Pricing, AppDetails, Trends)
- core.game_intelligence.achievements (Schema Cache, Player Unlocks, Session Milestones, Analytics)
- core.game_intelligence.social (Friends, Avatar, Library Comparisons, User Activity)
- core.game_intelligence.reviews (Review Forensics, Telemetry, Bot Detection, Review Summaries)
- core.game_intelligence.wiki (Guides, Web Wikis, Dossier Compilation, Disk Caching)
"""

from core.game_intelligence.store import (
    resolve_steam_id,
    get_steam_avatar,
    get_wishlist_appids,
    is_game_wishlisted,
    search_steam_store,
    get_similar_games,
    get_game_deals,
    get_reviews,
    get_reviews_summary,
    get_steam_app_info,
    get_steam_app_discount,
    get_steam_app_details,
    get_steamspy_game_info,
    get_global_game_info,
    get_batch_game_details,
    generate_contextual_dna,
    get_user_wishlist,
    get_steam_store_trends,
)

from core.game_intelligence.achievements import (
    get_achievement_stats,
    get_game_achievement_schema,
    get_player_achievements_raw,
    get_session_achievements,
)

from core.game_intelligence.social import (
    process_friends_list,
    get_friends_who_own,
    compare_library_with_friend,
    get_active_friends,
    get_user_activity,
)

from core.game_intelligence.reviews import (
    get_current_os_for_steam,
    _normalize_review_record,
    _compute_review_telemetry,
    get_n_reviews,
    get_steam_reviews,
    _summarize_reviews_with_llm,
    get_reviews_byname,
    evaluate_game,
)

from core.game_intelligence.wiki import (
    get_steam_guides_index,
    get_steam_guide_details,
    get_web_wiki_index,
    get_web_mechanics_index,
    _extract_page_markdown,
    _select_wiki_sources_with_llm,
    compile_game_wiki,
    get_game_wiki_cache_path,
    load_cached_wiki,
    save_wiki_to_cache,
)

__all__ = [
    # Store & Catalog
    "resolve_steam_id",
    "get_steam_avatar",
    "get_wishlist_appids",
    "is_game_wishlisted",
    "search_steam_store",
    "get_similar_games",
    "get_game_deals",
    "get_reviews",
    "get_reviews_summary",
    "get_steam_app_info",
    "get_steam_app_discount",
    "get_steam_app_details",
    "get_steamspy_game_info",
    "get_global_game_info",
    "get_batch_game_details",
    "generate_contextual_dna",
    "get_user_wishlist",
    "get_steam_store_trends",
    # Achievements
    "get_achievement_stats",
    "get_game_achievement_schema",
    "get_player_achievements_raw",
    "get_session_achievements",
    # Steam Social & User Activity
    "process_friends_list",
    "get_friends_who_own",
    "compare_library_with_friend",
    "get_active_friends",
    "get_user_activity",
    # Review Forensics
    "get_current_os_for_steam",
    "_normalize_review_record",
    "_compute_review_telemetry",
    "get_n_reviews",
    "get_steam_reviews",
    "_summarize_reviews_with_llm",
    "get_reviews_byname",
    "evaluate_game",
    # Game Wiki & Lore
    "get_steam_guides_index",
    "get_steam_guide_details",
    "get_web_wiki_index",
    "get_web_mechanics_index",
    "_extract_page_markdown",
    "_select_wiki_sources_with_llm",
    "compile_game_wiki",
    "get_game_wiki_cache_path",
    "load_cached_wiki",
    "save_wiki_to_cache",
]

if __name__ == "__main__":
    from pprint import pprint
    pprint(get_achievement_stats(game_name="KILL KNIGHT"))
