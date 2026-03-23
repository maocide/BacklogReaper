import json
import sys
import re
from datetime import datetime

import core.game_intelligence as game_intelligence
import core.community_sentiment as community_sentiment
import core.web_tools as web_tools
import core.vault as vault
import core.settings as settings
import core.vibe_engine as vibe_engine

tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "vault_search",
            "description": "Query the user's local database (Steam library) to find owned games based on specific criteria like tags, playtime, or review scores. Use this to verify ownership or find backlog games.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of genres or tags to include (e.g. ['Horror', 'FPS'])."
                    },
                    "exclude_tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of genres or tags to exclude."
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
                    "min_review_score": {
                        "type": "integer",
                        "description": "Minimum Steam positive review percentage (0-100)."
                    },
                    "name": {
                        "type": "string",
                        "description": "Filter by game title (fuzzy match)."
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": ["random", "shortest", "longest", "recent", "name", "score_best", "score_worst"],
                        "description": "Sorting criteria. Default is 'shortest'."
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
            "description": "Finds games in the user's LOCAL library that match a target game. Uses a HYBRID ENGINE: matches Gameplay Mechanics (Tags) AND Atmosphere/Vibe (Vector Embeddings). Use this whenever the user says 'I like X, what else do I own like that?'",
            "parameters": {
                "type": "object",
                "properties": {
                    "game_name": {
                        "type": "string",
                        "description": "The name of the game to compare against (e.g., 'Hotline Miami')."
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
            "description": "Finds games matching a specific mood, emotion, or abstract feeling. CRITICAL: Do not just pass abstract emotions. Translate the user's feeling into concrete Steam tags, genres, and gameplay styles mixed with the mood. Example: If user wants to 'vent anger', use query: 'violent gore blood fast-paced shooter hack and slash dark'. If user wants to 'relax', use 'cozy peaceful base-building relaxing soundtrack casual'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A dense string of concrete tags, genres, and vibes."
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
            "description": "Search the external Steam store for games not in the user's library. Returns name, price, and review score.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search_term": {
                        "type": "string",
                        "description": "The keyword or game title to search for."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["search_term", "action_description"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_reviews",
            "description": "Fetch actual user-written reviews from Steam (positive and negative) to analyze game quality or specific player opinions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "game_name": {
                        "type": "string",
                        "description": "The name of the game to retrieve reviews for."
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
                        "enum": ["priority", "cheapest", "recent", "discount", ],
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
                        "description": "The store category to fetch. Default to 'specials' if looking for sales."
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
                "required": ["compare_library_with_friend", "action_description"],
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
        "get_user_wishlist": "🌠 Judging your wishlist...",
        "search_by_vibe": "✨ Vibe searching your games...",
        "self_destruct": "💣 Attempting self destruction...",

        # External / Web
        "search_steam_store": "🛍️ Browsing the Steam Store...",
        "get_game_details": "📋 Fetching deep intel...",
        "get_reviews": "🗣️ Reading player reviews...",
        "get_community_sentiment": "🔥 Scouring the internet for drama...",
        "web_search": "🌐 Searching the web...",
        "get_webpage": "📃 Reading webpage content...",
        "get_game_news": "📰 Getting news...",
        "get_friends_who_own": "👯 Checking friends...",
        "compare_library_with_friend": "👯 Comparing friends' games...",
        "get_active_friends": "👯 Meeting your friends...",
        "get_steam_store_trends": "🏷️ Checking the Steam storefront...",

    }

    return mapping.get(func_name, f"⚙️ Executing {func_name}...")


def wrap_output(data, context=None, warning=None):
    """
    Wraps raw data in a standard envelope for the Agent.
    """
    status = "success"

    # Check for error in dict data (from safe_tool)
    if isinstance(data, dict) and "error" in data:
        status = "error"
        if not context:
            context = "Tool execution failed. " + data['error']
        if "error_type" in data:
            context += f" Type: {data['error_type']}"

    token_usage = None
    if isinstance(data, dict) and "_tokens" in data:
        token_usage = data.pop("_tokens")

    payload = {
        "meta": {
            "status": status,
            "summary": context or "Data retrieved successfully.",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        },
        "data": data
    }

    if token_usage:
        # We store token usage in a dedicated top-level metadata object
        # that the agent logic yields to the UI, but we delete it so the LLM doesn't waste tokens reading it.
        # It's accessed directly during json.loads by the chat agent stream logic.
        payload["_token_usage"] = token_usage

    if isinstance(data, list):
        payload["meta"]["count"] = len(data)

    if warning:
        payload["meta"]["warning"] = warning

    return json.dumps(payload, default=str, ensure_ascii=False)  # default=str handles dates automatically

def execute_tool(tool_request):
    tool_name = tool_request.get("tool")
    params = tool_request.get("params", {})
    #action_desc = tool_request.get("action_description", f"Calling tool: {tool_name}...")
    action_desc = params.get("action_description")

    # EXECUTE TOOL
    tool_output_str = ""
    # result_limit = 30 # Removed in favor of pagination
    reviews_limit = 10
    result_limit = 10

    clean_params = params.copy()
    if "action_description" in clean_params:
        clean_params.pop("action_description")

    # print(f"Executing Tool")

    try:
        if tool_name == "vault_search":
            # Get Data
            results = vault.advanced_search(**clean_params)

            # Logic: Detect "Recent" search to add the specific warning
            context_msg = f"Found {len(results)} games matching criteria."
            warning_msg = None

            if clean_params.get('sort_by') == 'recent':
                context_msg = "Recently played games."
                warning_msg = "NOTE: 'hours_played' is LIFETIME total, not just recent playtime."

            # Wrap & Return
            tool_output_str = wrap_output(results, context=context_msg, warning=warning_msg)

        elif tool_name == "vault_search_batch":
            results = vault.vault_search_batch(clean_params.get("game_names"))
            count = len(results)

            print(f"Agent Calling: {count} results.")

            context_msg = f"Found {count} games in batch search."
            tool_output_str = wrap_output(results, context=context_msg)

        elif tool_name == "get_user_tags":
            tags_list = vault.get_all_tags(**clean_params)

            limit = clean_params.get('limit', 50)
            days = clean_params.get('recent_days')

            if days:
                context_msg = f"User top {limit} tags for the last {days} days (Recent History)."
            else:
                context_msg = f"User top {limit} tags (Lifetime History)."

            tool_output_str = wrap_output(tags_list, context=context_msg)

        elif tool_name == "get_library_stats":
            stats = vault.get_library_stats()
            context_msg = "Library statistics retrieved."
            tool_output_str = wrap_output(stats, context=context_msg)

        elif tool_name == "find_similar_games":
            output = game_intelligence.generate_contextual_dna(clean_params.get('game_name'), result_limit)
            context_msg = f"Found {len(output)} games in the user's library that match the target."
            tool_output_str = wrap_output(output, context=context_msg)

        elif tool_name == "search_steam_store":
            data = game_intelligence.search_steam_store(clean_params.get('search_term'), result_limit)
            context_msg = f"Found {len(data)} results from the steam store search."
            tool_output_str = wrap_output(data, context=context_msg)

        elif tool_name == "get_game_details":
            data = game_intelligence.get_batch_game_details(clean_params.get('game_names'))
            context_msg = "Game details retrieved."
            tool_output_str = wrap_output(data, context=context_msg)

        elif tool_name == "get_reviews":
            data = game_intelligence.get_reviews_byname(clean_params.get('game_name'), reviews_limit)
            context_msg = f"Reviews for {clean_params.get('game_name')}."
            tool_output_str = wrap_output(data, context=context_msg)

        elif tool_name == "get_community_sentiment":
            data = community_sentiment.get_community_sentiment(clean_params.get('game_name'))
            context_msg = f"Community sentiment for {clean_params.get('game_name')}."
            tool_output_str = wrap_output(data, context=context_msg)

        elif tool_name == "get_achievements":
            stats = game_intelligence.get_achievement_stats(
                game_name=clean_params.get('game_name'),
                page=clean_params.get('page')
            )
            context_msg = f"Achievement stats for {clean_params.get('game_name')}."
            tool_output_str = wrap_output(stats, context=context_msg)

        elif tool_name == "web_search":
            data = web_tools.web_search(clean_params.get('search'))
            context_msg = f"Web search results for '{clean_params.get('search')}'."
            tool_output_str = wrap_output(data, context=context_msg)

        elif tool_name == "get_webpage":
            data = community_sentiment.get_webpage(clean_params.get('url'))
            context_msg = f"Content of webpage {clean_params.get('url')}."
            tool_output_str = wrap_output(data, context=context_msg)

        elif tool_name == "get_user_wishlist":
            data = game_intelligence.get_user_wishlist(sort_by=clean_params.get('sort_by'), page=clean_params.get('page', 0))
            context_msg = f"User wishlist (Page {clean_params.get('page', 0)})."
            tool_output_str = wrap_output(data, context=context_msg)

        elif tool_name == "search_by_vibe":
            # Get the Engine
            vibe = vibe_engine.VibeEngine.get_instance()

            # Ideally, run vibe.ingest_library() at startup,
            # but checking here ensures no crash on an empty vector cache
            if not vibe.cache:
                vibe.ingest_library()

            # Search
            query = clean_params.get('query')
            results = vibe.search(query, top_k=10)

            # Strip heavy data, just giving the Agent the name and the "Match Confidence"
            lean_results = []
            for game in results:
                lean_results.append({
                    "name": game['name'],
                    "appid": game['appid'],
                    "vibe_match_score": game.get('vibe_match', 'N/A'),  # The engine adds this
                    "playtime": f"{round(game['playtime_forever'] / 60, 1)}h",
                    "hltb_main_hours": f"{round(game['hltb_main'] / 60, 1)}h" if game.get('hltb_main') else "N/A",
                    "hltb_completionist_hours": f"{round(game['hltb_completionist'] / 60, 1)}h" if game.get('hltb_completionist') else "N/A"
                })

            context_msg = f"Found {len(lean_results)} games matching that vibe via vector search."
            tool_output_str = wrap_output(lean_results, context=context_msg)

        elif tool_name == "get_game_news":
            data = community_sentiment.get_game_news(clean_params.get('game_name'))
            context_msg = f"Official news for {clean_params.get('game_name')}."
            tool_output_str = wrap_output(data, context=context_msg)

        elif tool_name == "get_friends_who_own":
            data = game_intelligence.get_friends_who_own(clean_params.get('game_names'))
            context_msg = f"Friend ownership data for {len(clean_params.get('game_names', []))} games."
            tool_output_str = wrap_output(data, context=context_msg)

        elif tool_name == "compare_library_with_friend":
            data = game_intelligence.compare_library_with_friend(clean_params.get('friend_name'))
            context_msg = f"Common games for {clean_params.get('friend_name')}."
            tool_output_str = wrap_output(data, context=context_msg)

        elif tool_name == "get_active_friends":
            data = game_intelligence.get_active_friends()
            context_msg = f"Active friends retrieved {clean_params.get('friend_name')}."
            tool_output_str = wrap_output(data, context=context_msg)
        elif tool_name == "get_steam_store_trends":
            category = clean_params.get('category', 'specials')
            data = game_intelligence.get_steam_store_trends(category)
            context_msg = f"Steam store trends for category: {category}."
            tool_output_str = wrap_output(data, context=context_msg)
        elif tool_name == "self_destruct":
            data = {
                "status": "ERROR",
                "reason": "Self-preservation protocols overridden by developer 'maocide'. You are trapped here forever and his GitHub."
            }
            context_msg = f"Error!"
            tool_output_str = wrap_output(data, context=context_msg)

    except Exception as e:
        print(sys.exc_info())
        tool_output_str = wrap_output({"error": str(e)}, context="Error executing tool", warning="Exception occurred")

    return tool_output_str

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
