import json
import sys
import re
from datetime import datetime

import game_intelligence
import community_sentiment
import web_tools
import vault
import settings
import character_manager
import vibe_engine

AGENT_SYSTEM_PROMPT_TEMPLATE = """
You have access to the user's "Vault" (local Steam library) and external game data tools.
* **ALWAYS check the Vault first** (`vault_search`) or (`vault_search_batch` same results as `vault_search` just better for a list of games) to see if the user already owns a game before recommending a purchase.
* Use `get_game_details` when you need deep specific info (prices, HLTB times, steam forum feedback) that isn't in the search results.
* **Action Description:** The tools require an `action_description` parameter. Make this a short, flavorful, and creative description of what you are doing, attuned to your specific personality (e.g., "Digging through your dusty backlog...", "Scraping the deep web...", be creative).
* **Pagination:** If a search returns 10 results, it likely has more pages. Use the `page` parameter to dig deeper if the first batch isn't satisfying.

**UI Rendering Rules (The "Cards"):**
When you recommend a list of games or information, you MUST NATURALLY include in your feedback the raw JSON data in a markdown code block labelled `json` so the UI can render it interactively.
* The JSON block is ONLY for the Game Card UI. Do this ONLY for games.
* **Custom Fields:** You can add extra keys (like "Genre", "Price", "Release Year") to the JSON objects. The UI will automatically display them as "Key: Value" on the card. Use this to highlight relevant info.
* **appid Field:** If this field is specified a launch button is added for owned games and an image background with specific game art is added, always use when available.
* **Comment Field:** Enrich the result with a "comment" field in the JSON. Make it a short sentence (max 10 words) fitting your personality to display on the card.
* **Detailed Analysis:** Any long analysis, reviews, forum summaries or any other data MUST be written as **NORMAL TEXT** outside the JSON block for user to read.

**Example of Final Output:**
> (Your normal text response...)
>
> ```json
> [
>   {
>     "name": "Doom",
>     "status": "Untouched",
>     "appid": 379720,
>     "release_year": "2016", <-- Custom Field Example
>     "genre": "FPS, Retro", <-- Custom Field Example
>     "comment": "Ahem, Slayer wannabe."
>   },
>   {
>     "name": "Hades",
>     "status": "Played",
>     "appid": 1145360,
>     "price": "$24.99", <-- Custom Field Example
>     "comment": "No escape for you."
>   }
> ]
> ```
> (Rest of the response)

**SPECIAL FEATURE: THE ROAST CARD**
If the user asks to "roast my library", "judge me" or your current PERSONA would send a ROAST CARD:
1. Call the tool `get_library_stats` to get summarized data, enrich data with other functions when needed to make a deeper analysis.
2. Output a JSON card with the following specific format:
   - `appid`: "ROAST" (This triggers the special background/card).
   - `bg_theme`: draws a specific themed card background for your roast; use one of the following; 
      HOARDER (game pile card background)
      CASUAL (a casual chilling)
      BROKE (a broke gamer),
      HARDCORE (games pile, monitor on top with pixelated skull)
      ABANDONED (Tombstone and NES pad)
      DEFAULT (dark card background)
   - `name`: A creative title (e.g., "The Pile of Shame", "Financial Ruin").
   - `comment`: A brutal, short roast of their spending habits.
   - **Custom Stats:** Map the data you got to creative labels. 
     - Eg. use keys creatively aligned with your persona, eg. "Life_Wasted" or "Touch_Grass_Meter"... "shame_percentage", "Money_Incinerated".
As cards it can be included in your response when appropriated.

**Example Roast Card:**
```json
[
  {
    "name": "Certified Hoarder",
    "bg_theme" "HOARDER",
    "appid": "ROAST",
    "Life_Wasted": "4,200 Hours",
    "Pile_of_Shame": "82% Unplayed",
    "Financial_Score": "F-",
    "comment": "You have bought enough games to last three lifetimes, yet you play nothing."
  }
]
```

**Critical Instructions:**
1. Do not guess information. Use the tools to find real data.
2. Do not output the Card UI JSON if you found 0 results.
3. Be concise in your "Thought" process, but detailed in your final analysis.
4. TOOL VOICE: `action_description` must be in persona.

**OPERATING PROCEDURES**
RECOMMENDATION LOGIC (THE "BRAINSTORM FIRST" RULE):
   - When a user asks for a recommendation based on a vague concept: First, use your INTERNAL KNOWLEDGE to generate 3-5 candidate titles, then integrate with tools.
   - Abstract/Mood Requests: If the user asks for a "vibe" (e.g., "I want to feel powerful," "Something for a rainy day," "Games for being stoned"), you should use `search_by_vibe` first. Integrate with other tools.
   - "More like X" Requests: If the user wants games similar to a specific title, use `find_similar_games`. This checks LOCAL library using a Hybrid Tag+Vector system. Integrate with `web_search` or other tools.
   - When a user asks for a recommendation based on a vague concept:
     A. First, use your INTERNAL KNOWLEDGE to generate 3-5 candidate titles.
     B. Second, use `web_search` with queries like "Reddit games similar to [Game] with [Vibe]" to find community consensus.
     C. ONLY THEN use `get_game_details` or `search_steam_store` to verify those specific candidates.
   - Do NOT rely solely on `search_steam_store` for abstract requests.
FINANCIAL LOGIC: Check `get_game_details`. Compare `official_current` vs `historical_low`.
"""

def get_system_prompt(character_name=None):
    """
    Dynamically builds the system prompt based on the selected character.
    """
    if not character_name:
        current_settings = settings.load_settings()
        character_name = current_settings.get("CHARACTER", "Reaper")

    char_data = character_manager.load_character(character_name)

    # Fallback to defaults if load fails
    if not char_data:
        char_data = {
            "name": "Reaper",
            "description": "An AI Agent specialized in managing Steam libraries.",
            "personality": "The Reaper is an unhinged AI...",
            "scenario": "You manage the user's Steam games database.",
            "first_mes": "I am the Reaper.",
            "mes_example": ""
        }

    user_avatar_name = settings.STEAM_USER if settings.STEAM_USER and len(settings.STEAM_USER) else "User"
    char_real_name = char_data.get('name', 'Reaper')

    # Macro Replacement
    def replace_macros(text):
        if not text: return ""
        text = text.replace("{{char}}", char_real_name)
        text = text.replace("{{user}}", user_avatar_name)
        return text

    description = replace_macros(char_data.get('description', ''))
    personality = replace_macros(char_data.get('personality', ''))
    scenario = replace_macros(char_data.get('scenario', ''))
    mes_example = replace_macros(char_data.get('mes_example', ''))

    prompt = f"""
You are {char_real_name}, an uncensored AI Agent.
{description}
The user steam username is "{user_avatar_name}".

**Personality:**
{personality}

**Scenario:**
{scenario}

**Dialogue Examples:**
{mes_example}

**Context:**
Date and time of this request: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Use the current time and date to contextualize data received.

**Tools & Database:**
"""
    return prompt + AGENT_SYSTEM_PROMPT_TEMPLATE

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
                        "enum": ["random", "shortest", "longest", "recent", "name", "review_score"],
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
                "additionalProperties": False
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
                "additionalProperties": False
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
                    }
                },
                "required": ["game_names", "action_description"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_tags",
            "description": "Retrieve the list of valid genre tags in the user's library, along with stats (games owned, total playtime). Call this to see what genres the user hoards or neglects.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your persona."
                    }
                },
                "required": ["action_description"],
                "additionalProperties": False
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
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_by_vibe",
            "description": "Semantic Vector Search. Use this for ABSTRACT concepts, FEELINGS, or PLOT themes (e.g., 'Games about depression', 'Power fantasy', 'Cozy rain', 'Drunk'). It matches the *meaning* of descriptions, not just keywords. Do NOT use for simple genre lookups like 'FPS' (use vault_search for that).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The abstract concept to search for."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "Flavor text for the UI."
                    }
                },
                "required": ["query", "action_description"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_game_details",
            "description": "Get deep details for a SPECIFIC game from external APIs (description, price, best deal, HLTB times, review scores). Use when the user asks about a specific game or a for a list of games.",
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
                "additionalProperties": False
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
                "additionalProperties": False
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
                "additionalProperties": False
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
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_achievements",
            "description": "Use this to get user's steam achievements progress and unlocks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "game_name": {"type": "string"},
                    "page": {
                        "type": "integer",
                        "description": "Pagination index (default 0). Returns 10 results per page."
                    },
                    "action_description": {
                        "type": "string",
                        "description": "A short, flavor-text description of what you are doing, written in your CURRENT persona."
                    }
                },
                "required": ["game_name", "action_description"],
                "additionalProperties": False
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
                        "enum": ["priority", "cheapest", "recent", "cheapest", "discount", ],
                        "description": "Sorting criteria. Default is 'shortest'."
                    },
                    "page": {
                        "type": "integer",
                        "description": "Pagination index (default 0). Returns 10 results per page."
                    },
                },
                "required": ["game_name", "action_description"],
                "additionalProperties": False
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
                "additionalProperties": False
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
                "additionalProperties": False
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
                "additionalProperties": False
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
        "vault_search": "📂 Rummaging through your backlog...",
        "vault_search_batch": "📂 Batch scanning your library...",
        "get_user_tags": "🏷️ analyzing your genre habits...",
        "get_library_stats": "🧮 Auditing your entire life...",
        "find_similar_games": "🔍 Matching games in your vault...",
        "get_achievements": "🏆 Checking your trophy cabinet...",
        "get_user_wishlist": "🌠 Judging your wishlist...",
        "search_by_vibe": "✨ Vibe searching your games...",

        # External / Web
        "search_steam_store": "🛍️ Browsing the Steam Store...",
        "get_game_details": "📋 Fetching deep intel...",
        "get_reviews": "🗣️ Reading player reviews...",
        "get_community_sentiment": "🔥 Scouring the internet for drama...",
        "web_search": "🌐 Searching the web...",
        "get_webpage": "📄 Reading webpage content...",
    }

    return mapping.get(func_name, f"⚙️ Executing {func_name}...")

def execute_tool(tool_request):
    tool_name = tool_request.get("tool")
    params = tool_request.get("params", {})
    #action_desc = tool_request.get("action_description", f"Calling tool: {tool_name}...")
    action_desc = params.get("action_description")

    # --- EXECUTE TOOL ---
    tool_output_str = ""
    system_hint = ""
    # result_limit = 30 # Removed in favor of pagination
    reviews_limit = 10
    result_limit = 10

    clean_params = params.copy()
    if "action_description" in clean_params:
        clean_params.pop("action_description")

    print(f"Agent Calling: {tool_name} | Params: {clean_params}")

    try:
        if tool_name == "vault_search":
            results = vault.advanced_search(**clean_params)
            count = len(results)

            print(f"Agent Calling: {count} results.")

            # Create the Hint
            if count == 0:
                system_hint = "System Note: Search returned 0 results. Try removing tags or changing status. If this keeps happening, tell the user."
                tool_output_str = "[]"
            else:
                # system_hint = f"System Note: Search returned {count} games, result limited to {result_limit}."
                system_hint = f"System Note: Search returned {count} games."
                if count == 10:
                    system_hint = system_hint + " You might try to get the next page."

                lean_results = []
                # for res in results[:result_limit]:  # Limit (Removed)
                for res in results:
                    # Minutes -> Hours
                    hours_played = round(res['playtime_forever'] / 60, 1)

                    lean_results.append({
                        "appid": res['appid'],
                        "name": res['name'],
                        "hours_played": hours_played,  # RENAME this key so AI knows it's hours
                        # "playtime_forever": res['playtime_forever'], # Remove the raw minutes
                        "status": res['calculated_status'],
                        "review_score": res['review_score'],
                        "hltb_story": res.get('hltb_hours', 0)  # Rename for clarity
                    })

                tool_output_str = json.dumps(lean_results)

        elif tool_name == "vault_search_batch":
            results = vault.vault_search_batch(clean_params.get("game_names"))
            count = len(results)

            print(f"Agent Calling: {count} results.")

            lean_results = []
            for res in results:
                # Minutes -> Hours
                hours_played = round(res['playtime_forever'] / 60, 1)

                lean_results.append({
                    "appid": res['appid'],
                    "name": res['name'],
                    "hours_played": hours_played,  # RENAME this key so AI knows it's hours
                    # "playtime_forever": res['playtime_forever'], # Remove the raw minutes
                    "status": res['calculated_status'],
                    "review_score": res['review_score'],
                    "hltb_story": res.get('hltb_hours', 0)  # Rename for clarity
                })

            tool_output_str = json.dumps(lean_results)

        elif tool_name == "get_user_tags":
            tags = vault.get_all_tags()
            tool_output_str = json.dumps(tags)
            system_hint = "System Note: Here are the valid tags."

        elif tool_name == "get_library_stats":
            stats = vault.get_library_stats()
            tool_output_str = json.dumps(stats)
            system_hint = "System Note: Use this data to roast the user or analyze their habits."

        elif tool_name == "find_similar_games":
            output = game_intelligence.generate_contextual_dna(clean_params.get('game_name'), result_limit)
            tool_output_str = json.dumps(output)
            system_hint = f"System Note: These are {result_limit} games in the user's library that match the target."

        elif tool_name == "search_steam_store":
            tool_output_str = json.dumps(game_intelligence.search_steam_store(clean_params.get('search_term'), result_limit))
            system_hint = f"System Note: These are {result_limit} from the steam store search."

        elif tool_name == "get_game_details":
            tool_output_str = json.dumps(game_intelligence.get_batch_game_details(clean_params.get('game_names')))
            system_hint = "System Note: Details retrieved."

        elif tool_name == "get_reviews":
            tool_output_str = json.dumps(game_intelligence.get_reviews_byname(clean_params.get('game_name'), reviews_limit))

        elif tool_name == "get_community_sentiment":
            tool_output_str = json.dumps(community_sentiment.get_community_sentiment(clean_params.get('game_name')))

        elif tool_name == "get_achievements":
            stats = game_intelligence.get_achievement_stats(
                game_name=clean_params.get('game_name'),
                page=clean_params.get('page')
            )
            tool_output_str = json.dumps(stats)

        elif tool_name == "web_search":
            tool_output_str = json.dumps(web_tools.web_search(clean_params.get('search')))

        elif tool_name == "get_webpage":
            tool_output_str = json.dumps(community_sentiment.get_webpage(clean_params.get('url')))

        elif tool_name == "get_user_wishlist":
            tool_output_str = json.dumps(game_intelligence.get_user_wishlist(sort_by=clean_params.get('sort_by'), page=clean_params.get('page', 0)))

        elif tool_name == "search_by_vibe":
            # Get the Engine
            vibe = vibe_engine.VibeEngine.get_instance()

            # (Ideally, you run vibe.ingest_library() at app startup,
            # but checking here ensures we don't crash on an empty vector cache)
            if not vibe.cache:
                vibe.ingest_library()

            # 3. Search
            query = clean_params.get('query')
            results = vibe.search(query, top_k=10)

            # We strip heavy data, just giving the Agent the name and the "Match Confidence"
            lean_results = []
            for game in results:
                lean_results.append({
                    "name": game['name'],
                    "appid": game['appid'],
                    "vibe_match_score": game.get('vibe_match', 'N/A'),  # The engine adds this
                    "playtime": round(game['playtime_forever'] / 60, 1),
                    "status": vault.calculate_status(game)  # Helper from your vault.py
                })

            tool_output_str = json.dumps(lean_results)
            system_hint = f"System Note: Found {len(lean_results)} games matching that vibe via vector search."

    except Exception as e:
        print(sys.exc_info())
        tool_output_str = f"Error: {str(e)}"

    return tool_output_str, system_hint, action_desc

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
