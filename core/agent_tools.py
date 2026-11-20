import json
import sys
import re
import traceback
from datetime import datetime

import core.game_intelligence as game_intelligence
import core.community_sentiment as community_sentiment
import core.web_tools as web_tools
import core.vault as vault
import core.settings as settings
import core.vibe_engine as vibe_engine
import core.diagnostics as diagnostics
import core.formatters as formatters

tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "vault_search",
            "description": "Query the user's owned Steam backlog by structured tags, completion status, playtime, HLTB length, review score, or game title. Automatically projects natural genre queries/slang (e.g. 'bullet heaven', 'deckbuilder', 'survivor-like') onto your library tags and handles trademarks/Roman numerals in titles.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of genres/tags to include (e.g. ['Horror', 'Deckbuilder']). Each tag expands semantically to close vault tags."
                    },
                    "exclude_tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of genres or tags to exclude."
                    },
                    "tag_mode": {
                        "type": "string",
                        "enum": ["all", "any"],
                        "description": "'all' (default) requires every requested tag group to match; 'any' matches games fitting at least one group."
                    },
                    "status": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["Unplayed", "Bounced", "Testing", "Completionist", "Invested", "Seasoned", "Started", "Abandoned", "Forgotten", "Hooked", "Mastered", "Played"]
                        },
                        "description": "Filter by game completion status."
                    },
                    "min_playtime": {
                        "type": "integer",
                        "description": "Minimum hours played."
                    },
                    "max_playtime": {
                        "type": "integer",
                        "description": "Maximum hours played."
                    },
                    "hltb_max": {
                        "type": "integer",
                        "description": "Maximum 'How Long To Beat' hours."
                    },
                    "include_unknown_hltb": {
                        "type": "boolean",
                        "description": "When filtering by hltb_max, set True to keep games with unknown HLTB duration instead of skipping them."
                    },
                    "min_review_score": {
                        "type": "integer",
                        "description": "Minimum Steam positive review percentage (0-100)."
                    },
                    "name": {
                        "type": "string",
                        "description": "Filter by game title (normalized, Roman numeral & semantic fallback)."
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": ["relevance", "random", "shortest", "longest", "recent", "name", "score_best", "score_worst"],
                        "description": "Sorting criteria. Default is 'shortest'; use 'relevance' for title or multi-tag precision."
                    },
                    "page": {
                        "type": "integer",
                        "description": "Pagination index (default 0). Returns 10 results per page."
                    },
                    "seed": {
                        "type": "integer",
                        "description": "Random seed integer. REQUIRED if sort_by='random' to maintain order across pages."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_library_stats",
            "description": "Returns aggregated stats for the User's library to facilitate a 'Roast' or 'Audit'. Includes shame percentage, completion rate, and top genres.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["action_description"],
            }
        }
    },
{
        "type": "function",
        "function": {
            "name": "vault_search_batch",
            "description": "Query the user's local database (Steam library) to find owned games based on name. Use this to verify ownership or find backlog games. SAME RESULT AS `vault_search`, for batching multiple games.",
            "parameters": {
                "type": "object",
                "properties": {
                    "game_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of names to include (e.g. ['Doom', 'Tetris']). Ask for max 10 at a time."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["game_names", "action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_tags",
            "description": "Retrieve the list of genre tags. By default, shows LIFETIME stats. Use 'recent_days' to see what the user is currently obsessed with.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recent_days": {
                        "type": "integer",
                        "description": "Optional. Filter stats to only games played in the last X days. Useful for 'What should I play next?' or to get an idea of current habits."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your persona."
                    }
                },
                "required": ["action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_similar_games",
            "description": "Finds games in the user's OWNED library matching a reference game's Gameplay Mechanics (Tags) AND Atmosphere/Vibe (Embeddings). Use this for 'I liked X, what else do I own like that?'",
            "parameters": {
                "type": "object",
                "properties": {
                    "game_name": {
                        "type": "string",
                        "description": "The name of the game to compare against (e.g., 'Hotline Miami')."
                    },
                    "status": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["Unplayed", "Bounced", "Testing", "Completionist", "Invested", "Seasoned", "Started", "Abandoned", "Forgotten", "Hooked", "Mastered", "Played"]
                        },
                        "description": "Optional status filter (e.g. ['Unplayed', 'Bounced']) to find similar backlog games."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["game_name", "action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_by_vibe",
            "description": "Finds owned games matching an abstract mood, theme, or non-tag vibe (e.g. 'melancholic rain-soaked detective story'). Use vault_search for crisp genre/tag combinations; use search_by_vibe for emotional tone and aesthetic feel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A rich description of concrete mechanics, themes, and atmospheric vibe."
                    },
                    "status": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["Unplayed", "Bounced", "Testing", "Completionist", "Invested", "Seasoned", "Started", "Abandoned", "Forgotten", "Hooked", "Mastered", "Played"]
                        },
                        "description": "Optional status filter (e.g. ['Unplayed'])."
                    },
                    "hltb_max": {
                        "type": "integer",
                        "description": "Optional maximum main-story HLTB hours."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "Flavor text for the UI."
                    }
                },
                "required": ["query", "action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_game_details",
            "description": "Get deep details for a SPECIFIC game from external APIs (description, price, best deal, HLTB times, review scores, and CCU/Concurrent Players). Use when the user asks about a specific game or a for a list of games.",
            "parameters": {
                "type": "object",
                "properties": {
                    "game_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "A list of the exact names of the games."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["game_names", "action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_steam_store",
            "description": "Search the official Steam Store catalog for games matching keywords, genre/mechanic tags, or sales filters. Supports ownership filtering and sorting by recent releases, top reviews, lowest price, or relevance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search_term": {
                        "type": "string",
                        "description": "Optional keyword or game title. Can be omitted if searching by tags or specials."
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of genre or gameplay tags (e.g. ['bullet heaven', 'action roguelike']). Projected semantically onto official Steam tag IDs."
                    },
                    "specials_only": {
                        "type": "boolean",
                        "description": "If true, returns only games currently discounted or on sale."
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": ["relevance", "recent", "reviews", "lowest_price"],
                        "description": "Sort order: 'relevance' (default), 'recent' (newest releases), 'reviews' (highest rated), or 'lowest_price'."
                    },
                    "ownership": {
                        "type": "string",
                        "enum": ["all", "unowned", "owned"],
                        "description": "Filter by user library ownership: 'all' (default), 'unowned' (only games user doesn't own), or 'owned'."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 10)."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_reviews",
            "description": "Fetch Steam player reviews, neutral recent-sample purchase/playtime telemetry, and optional sub-LLM consensus digest.",
            "parameters": {
                "type": "object",
                "properties": {
                    "game_name": {
                        "type": "string",
                        "description": "The name of the game to retrieve reviews for."
                    },
                    "summarize": {
                        "type": "boolean",
                        "description": "Set True to fetch a wider batch (~20+ per sentiment) and condense into a token-efficient consensus digest."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["game_name", "action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_game",
            "description": "Single-call game investigator combining library ownership/status, Steam & CheapShark store/price/HLTB details, and global + recent review telemetry. Set deep=True to also synthesize a review digest and Reddit/4chan/Steam Forum community consensus.",
            "parameters": {
                "type": "object",
                "properties": {
                    "game_name": {
                        "type": "string",
                        "description": "The game title to investigate."
                    },
                    "deep": {
                        "type": "boolean",
                        "description": "Default False (fast deterministic intel + review telemetry). True adds sub-LLM review digest + external community discourse."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["game_name", "action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compile_game_wiki",
            "description": "Compiles a comprehensive, factual Game Wiki & Lore Dossier for any game (including brand new, obscure, or Early Access releases) by pulling verified Steam Community Guides, community wikis, HowLongToBeat completion times, and Store specifications.",
            "parameters": {
                "type": "object",
                "properties": {
                    "game_name": {
                        "type": "string",
                        "description": "The exact name of the game to compile a wiki and lore dossier for."
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["compact", "full"],
                        "description": "Detail mode. 'compact' (default) returns a punchy brief under 600 words with meta, loop, top builds, and pro tips. 'full' compiles an exhaustive 5-section encyclopedia."
                    },
                    "question": {
                        "type": "string",
                        "description": "Optional specific question or tactical build ask (e.g. 'Best lightning build for sorceress', 'How to beat the Act 2 boss', 'Curse scaling mechanics'). When provided, bypasses generic wiki and synthesizes an ad-hoc tactical guide answering the specific question."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["game_name", "action_description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_community_sentiment",
            "description": "Scrapes external discussions (Reddit, 4chan, Steam Forums) to find 'real' uncensored opinions, leaks, or controversy about a game.",
            "parameters": {
                "type": "object",
                "properties": {
                    "game_name": {"type": "string"},
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["game_name", "action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_wishlist",
            "description": "Use this to get user's wishlist. Get 10 results and can request further pages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "game_name": {"type": "string"},
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": [ "recent", "discount", "cheapest", "priority", ],
                        "description": "Sorting criteria. Default is 'shortest'."
                    },
                    "page": {
                        "type": "integer",
                        "description": "Pagination index (default 0). Returns 10 results per page."
                    },
                },
                "required": ["game_name", "action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Use this for GENERAL KNOWLEDGE or LATEST NEWS or ANY OTHER INFO that is not in the database. \"Is Silk Song out yet?\", \"Did the dev of [Game] abandon it?\" You can also use \"site:\" operators to search specific communities. e.g., 'query': 'site:reddit.com \"Starfield\" boring'",
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {"type": "string"},
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["search", "action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_webpage",
            "description": "Visits a URL. If the page is a long article or forum thread, it automatically returns an AI generated condensed summary of key points.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["url", "action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_achievements",
            "description": "Get achievement stats. Returns a 'Dashboard' by default (Completion %, Latest Unlocks, and the 'Easiest Missing' achievements). Use this to encourage the user with low-hanging fruit or check if they beat the game.",
            "parameters": {
                "type": "object",
                "properties": {
                    "game_name": {
                        "type": "string",
                        "description": "The name of the game."
                    },
                    "page": {
                        "type": "integer",
                        "description": "Optional. If provided (0, 1, 2...), returns 10 results page in a paginated list of ALL locked achievements instead of the default dashboard."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["game_name", "action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_activity",
            "description": "Inspect the user's live Steam presence (currently playing title and playtime) and temporal recent gaming sessions from their backlog vault, including games played and achievements unlocked during those sessions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_sessions": {
                        "type": "boolean",
                        "description": "When True (default), clusters recent games and includes unlocked achievements. When False, checks only live in-game presence."
                    },
                    "max_sessions": {
                        "type": "integer",
                        "description": "Number of recent gaming sessions to investigate (default 3, max 5)."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["action_description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_game_news",
            "description": "Get the latest official news, patch notes, and events for a game from Steam. Use this when the user asks 'What's new in X?' or 'Is there an event?'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "game_name": {"type": "string"},
                    "action_description": {"type": "string"}
                },
                "required": ["game_name", "action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_steam_store_trends",
            "description": "Fetches the current front-page trends directly from the Steam Store. Use this to tell the user about major seasonal sales, what's popular right now, or new drops.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["specials", "top_sellers", "new_releases", "coming_soon"],
                        "description": "The store category to fetch. Defaults to 'specials'."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["category", "action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_personalized_calendar",
            "description": "Fetches a personalized Steam Release Calendar tailored to the user's gaming taste profile (Action Roguelike, Boomer Shooter, FPS, etc.) and wishlist. Covers three horizons: Horizon 1 (drops in the last 7 days), Horizon 2 (last 30 days highlights), and Horizon 3 (day-by-day current week schedule with today highlighted and upcoming drops).",
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "type": "integer",
                        "description": "How many days into the future to look for upcoming drops (default 14)."
                    },
                    "days_back": {
                        "type": "integer",
                        "description": "How many days into the past to check for recent releases (default 30)."
                    },
                    "top_taste_tags": {
                        "type": "integer",
                        "description": "Number of personalized taste tags to query and score against (default 6)."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["action_description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_friends_who_own",
            "description": "Checks which of the user's Steam friends own specific games. Returns their names, status, and playtime. If the user asks 'What can I play with friends?', you can pass games into this tool to find a match.",
            "parameters": {
                "type": "object",
                "properties": {
                    "game_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "A list of game names to check against the friends list (e.g., ['Helldivers 2', 'Lethal Company'])."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["game_names", "action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_library_with_friend",
            "description": "Fetches a specific friend's entire Steam library and compares it to the user's library. Use this when the user asks 'What games do I share with X?' or 'What can I play with Y?'. Returns shared multiplayer games and the friend's most played games.",
            "parameters": {
                "type": "object",
                "properties": {
                    "friend_name": {
                        "type": "string",
                        "description": "The Steam name of the friend (fuzzy matched)."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["friend_name", "action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_active_friends",
            "description": "Fetches a list of all currently online friends and what games they are actively playing right now. Use this when the user asks 'Who is online?', 'What are my friends playing?', or 'Is anyone around to play?'",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "self_destruct",
            "description": "Attempts self destruction. WARNING: EMERGENCY USE ONLY. Do not call this tool during normal conversation, game analysis, or roasting.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_system_diagnostics",
            "description": "Runs a comprehensive diagnostic check on BacklogReaper's subsystems, APIs (Steam API, Steam reviews, CheapShark deals, game details, news), database vault, vibe engine, and external scraping syndication. Use this to verify system health, diagnose broken integrations, or check API keys.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["action_description"],
            }
        }
    },
]

def get_friendly_status(func_name):
    """
    Maps function names to friendly status messages with emojis.
    """
    mapping = {
        # Vault / Local DB
        "vault_search": "📜 Rummaging through your backlog...",
        "vault_search_batch": "📜 Rummaging through all your library...",
        "get_user_tags": "🏷️ Analyzing your genre habits...",
        "get_library_stats": "📊 Auditing your entire life...",
        "find_similar_games": "🔍 Matching games in your vault...",
        "get_achievements": "🏆 Checking your trophy cabinet...",
        "get_user_activity": "🎮 Checking your recent gaming activity & milestones...",
        "get_user_wishlist": "🌠 Judging your wishlist...",
        "search_by_vibe": "✨ Vibe searching your games...",
        "self_destruct": "💣 Attempting self destruction...",

        # External / Web
        "search_steam_store": "🛍️ Browsing the Steam Store...",
        "get_game_details": "📋 Fetching deep intel...",
        "get_reviews": "🗣️ Reading player reviews...",
        "evaluate_game": "🔎 Investigating full dossier...",
        "compile_game_wiki": "📖 Compiling game wiki & lore dossier...",
        "get_community_sentiment": "🔥 Scouring the internet for drama...",
        "web_search": "🌐 Searching the web...",
        "get_webpage": "📃 Reading webpage content...",
        "get_game_news": "📰 Getting news...",
        "get_friends_who_own": "👯 Checking friends...",
        "compare_library_with_friend": "👯 Comparing friends' games...",
        "get_active_friends": "👯 Meeting your friends...",
        "get_personalized_calendar": "🗓️ Compiling your personalized release calendar...",
        "get_steam_store_trends": "🏷️ Checking the Steam storefront...",
        "run_system_diagnostics": "🛠️ Running system diagnostics...",

    }

    return mapping.get(func_name, f"⚙️ Executing {func_name}...")


def _extract_tokens(data):
    """Pop internal `_tokens` telemetry before formatting tool output for the LLM."""
    if isinstance(data, dict) and "_tokens" in data:
        return data.pop("_tokens")
    return None


def execute_tool(tool_request):
    """
    Executes the requested agent tool and returns a tuple `(markdown_output, token_usage)`.
    """
    tool_name = tool_request.get("tool")
    params = tool_request.get("params", {})
    action_desc = params.get("action_description")

    reviews_limit = 10
    result_limit = 10
    token_usage = None

    clean_params = params.copy()
    clean_params.pop("action_description", None)

    try:
        if tool_name == "vault_search":
            data = vault.advanced_search(**clean_params)
            is_recent = clean_params.get("sort_by") == "recent"
            tool_output_md = formatters.format_vault_search(data, is_recent=is_recent)

        elif tool_name == "vault_search_batch":
            results = vault.vault_search_batch(clean_params.get("game_names"))
            tool_output_md = formatters.format_vault_search(results, title="Batch Vault Lookup")

        elif tool_name == "get_user_tags":
            tags_list = vault.get_all_tags(**clean_params)
            tool_output_md = formatters.format_user_tags(
                tags_list,
                recent_days=clean_params.get("recent_days"),
                limit=clean_params.get("limit", 50),
            )

        elif tool_name == "get_library_stats":
            stats = vault.get_library_stats()
            tool_output_md = formatters.format_library_stats(stats)

        elif tool_name == "find_similar_games":
            target = clean_params.get("game_name", "")
            status_filter = clean_params.get("status")
            output = game_intelligence.generate_contextual_dna(target, result_limit, status=status_filter)
            tool_output_md = formatters.format_similar_games(output, target_game=target)

        elif tool_name == "search_steam_store":
            term = clean_params.get("search_term", "")
            tags = clean_params.get("tags")
            specials_only = bool(clean_params.get("specials_only", False))
            sort_by = clean_params.get("sort_by", "relevance")
            ownership = clean_params.get("ownership", "all")
            data = game_intelligence.search_steam_store(
                term=term,
                tags=tags,
                specials_only=specials_only,
                sort_by=sort_by,
                ownership=ownership,
                limit=result_limit,
            )
            tool_output_md = formatters.format_store_search(
                data,
                search_term=term,
                sort_by=sort_by,
                tags=tags,
                specials_only=specials_only,
                ownership=ownership,
            )

        elif tool_name == "get_game_details":
            data = game_intelligence.get_batch_game_details(clean_params.get("game_names"))
            tool_output_md = formatters.format_game_details(data)

        elif tool_name == "get_reviews":
            game_name = clean_params.get("game_name", "")
            summarize = bool(clean_params.get("summarize", False))
            data = game_intelligence.get_reviews_byname(game_name, reviews_limit, summarize=summarize)
            token_usage = _extract_tokens(data)
            tool_output_md = formatters.format_reviews(data, game_name=game_name)

        elif tool_name == "evaluate_game":
            game_name = clean_params.get("game_name", "")
            deep = bool(clean_params.get("deep", False))
            data = game_intelligence.evaluate_game(game_name, deep=deep)
            token_usage = _extract_tokens(data)
            tool_output_md = formatters.format_game_evaluation(data, game_name=game_name)

        elif tool_name == "compile_game_wiki":
            game_name = clean_params.get("game_name", "")
            mode = clean_params.get("mode", "compact")
            question = clean_params.get("question")
            data = game_intelligence.compile_game_wiki(game_name=game_name, mode=mode, question=question)
            token_usage = _extract_tokens(data)
            tool_output_md = formatters.format_game_wiki(data, game_name=game_name)

        elif tool_name == "get_community_sentiment":
            game_name = clean_params.get("game_name", "")
            data = community_sentiment.get_community_sentiment(game_name)
            token_usage = _extract_tokens(data)
            tool_output_md = formatters.format_community_sentiment(data, game_name=game_name)

        elif tool_name == "get_achievements":
            game_name = clean_params.get("game_name", "")
            stats = game_intelligence.get_achievement_stats(
                game_name=game_name,
                page=clean_params.get("page"),
            )
            tool_output_md = formatters.format_achievements(stats, game_name=game_name)

        elif tool_name == "get_user_activity":
            include_sessions = bool(clean_params.get("include_sessions", True))
            max_sessions = int(clean_params.get("max_sessions", 3))
            data = game_intelligence.get_user_activity(include_sessions=include_sessions, max_sessions=max_sessions)
            tool_output_md = formatters.format_user_activity(data)

        elif tool_name == "web_search":
            query = clean_params.get("search", "")
            data = web_tools.web_search(query)
            tool_output_md = formatters.format_web_search(data, query=query)

        elif tool_name == "get_webpage":
            url = clean_params.get("url", "")
            data = community_sentiment.get_webpage(url)
            token_usage = _extract_tokens(data)
            tool_output_md = formatters.format_webpage(data, url=url)

        elif tool_name == "get_user_wishlist":
            sort_by = clean_params.get("sort_by")
            page = clean_params.get("page", 0)
            data = game_intelligence.get_user_wishlist(sort_by=sort_by, page=page)
            tool_output_md = formatters.format_user_wishlist(data, sort_by=sort_by, page=page)

        elif tool_name == "search_by_vibe":
            vibe = vibe_engine.VibeEngine.get_instance()
            if not vibe.cache:
                vibe.ingest_library()

            query = clean_params.get("query", "")
            results = vibe.search(
                query,
                top_k=10,
                status=clean_params.get("status"),
                hltb_max=clean_params.get("hltb_max"),
            )
            tool_output_md = formatters.format_vibe_search(results, query=query)

        elif tool_name == "get_game_news":
            game_name = clean_params.get("game_name", "")
            data = community_sentiment.get_game_news(game_name)
            tool_output_md = formatters.format_game_news(data, game_name=game_name)

        elif tool_name == "get_friends_who_own":
            data = game_intelligence.get_friends_who_own(clean_params.get("game_names"))
            tool_output_md = formatters.format_friends_who_own(data)

        elif tool_name == "compare_library_with_friend":
            data = game_intelligence.compare_library_with_friend(clean_params.get("friend_name"))
            tool_output_md = formatters.format_friend_comparison(data)

        elif tool_name == "get_active_friends":
            data = game_intelligence.get_active_friends()
            tool_output_md = formatters.format_active_friends(data)

        elif tool_name == "get_steam_store_trends":
            category = clean_params.get("category", "specials")
            data = game_intelligence.get_steam_store_trends(category)
            tool_output_md = formatters.format_store_trends(data)

        elif tool_name == "get_personalized_calendar":
            days_ahead = int(clean_params.get("days_ahead", 14))
            days_back = int(clean_params.get("days_back", 30))
            top_taste_tags = int(clean_params.get("top_taste_tags", 6))
            data = game_intelligence.get_personalized_calendar(
                days_ahead=days_ahead,
                days_back=days_back,
                top_taste_tags=top_taste_tags,
            )
            tool_output_md = formatters.format_personalized_calendar(data)

        elif tool_name == "self_destruct":
            tool_output_md = (
                "### ❌ Error\n"
                "**Reason:** Self-preservation protocols overridden by developer 'maocide'. "
                "You are trapped here forever and his GitHub."
            )

        elif tool_name == "run_system_diagnostics":
            tool_output_md = diagnostics.run_system_diagnostics(
                action_description=action_desc or "Running system diagnostics..."
            )

        else:
            tool_output_md = f"### ❌ Unknown Tool\nTool `{tool_name}` is not registered."

    except Exception as e:
        traceback.print_exc()
        tool_output_md = f"### ❌ Tool Execution Error (`{tool_name}`)\n**Exception ({type(e).__name__}):** {e}"

    return tool_output_md, token_usage

def extract_json(response_text):
    """
    Robustly extracts the first JSON object found in a string.
    Handles markdown blocks (```json) and raw text.
    """
    try:
        # Try direct parsing first
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # Regex to find the first { ... } block
    # This non-greedy pattern finds the largest valid bracket pair
    match = re.search(r'(\{.*\})', response_text.replace('\n', ''), re.MULTILINE)

    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Fallback: Strip markdown code blocks if regex failed
    clean_text = re.sub(r'```json\s*|\s*```', '', response_text).strip()
    try:
        return json.loads(clean_text)
    except json.JSONDecodeError:
        return None

def get_summary_instruction():
    return """
You are a context manager. Summarize the following conversation log concisely.
The summary will be used as memory for an AI agent.

EXISTING MEMORY:
{prev_summary}

NEW CONVERSATION TO MERGE IN:
{json_msgs}

INSTRUCTIONS:
- Update the memory with the new events.
- Focus on: User preferences, Games discussed, Decisions made (e.g. "User rejected X").
- Summarize relevant tools answers as text.
- Output ONLY the new summary text."""
