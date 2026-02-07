
"""
Reaper Backend Facade
This module aggregates functionality from `game_intelligence` and `community_sentiment`
to maintain backward compatibility.
"""

# Re-export everything from game_intelligence
from game_intelligence import (
    resolve_steam_id,
    search_steam_store,
    get_similar_games,
    get_game_deals,
    get_global_game_info,
    get_batch_game_details,
    generate_contextual_dna,
    get_reviews,
    get_reviews_summary,
    get_n_reviews,
    get_steam_app_info,
    get_steam_app_discount,
    get_steam_app_details,
    get_steam_reviews,
    get_steamspy_game_info,
    get_reviews_byname,
    get_reviews_byname_formatted,
    format_reviews_for_ai,
    get_achievement_stats,
    get_user_wishlist
)

# Re-export everything from community_sentiment
from community_sentiment import (
    scrape_steam_forums,
    get_webpage,
    scrape_reddit_search,
    scrape_4chan_thread,
    find_4chan_thread,
    scrape_4chan_thread_with_ai,
    get_community_sentiment
)

# Also expose imports that might be expected
from web_tools import get_hltb_data as get_hltb_search_scrape # Alias for compat
from web_tools import web_search

