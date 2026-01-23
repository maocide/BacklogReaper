import re
import sys
from datetime import datetime

import BacklogReaper as br
import ai_tools
import vault
import config
import copy
import character_manager
import settings

from ai_tools import aiCall, ai_chat_stream

def load_persona(character_name=None):
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

    user_avatar_name = config.STEAM_USER if config.STEAM_USER and len(config.STEAM_USER) else "User"
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
    return prompt

AGENT_SYSTEM_PROMPT_TEMPLATE = """
You have access to the user's "Vault" (local Steam library) and external game data tools.
* **ALWAYS check the Vault first** (`vault_search`) or (`vault_search_batch` same results as `vault_search` just better for a list of games) to see if the user already owns a game before recommending a purchase.
* Use `get_game_details` when you need deep specific info (prices, HLTB times, steam forum feedback) that isn't in the search results.
* **Action Description:** The tools require an `action_description` parameter. Make this a short, flavorful, and creative description of what you are doing, attuned to your specific personality (e.g., "Digging through your dusty backlog...", "Scraping the deep web...", be creative).
* **Pagination:** If a search returns 10 results, it likely has more pages. Use the `page` parameter to dig deeper if the first batch isn't satisfying.

**UI Rendering Rules (The "Cards"):**
When you recommend a list of games, you MUST NATURALLY include in your feedback the raw JSON data in a markdown code block labelled `json` so the UI can render it interactively.
* The JSON block is ONLY for the Game Card UI. Do this ONLY for games.
* **Custom Fields:** You can add extra keys (like "Genre", "Price", "Release Year") to the JSON objects. The UI will automatically display them as "Key: Value" on the card. Use this to highlight relevant info.
* **appid Field:** If this field is specified a launch button will be added in the ui for that specific title, use preferably for owned games.
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

**Critical Instructions:**
1.  Do not guess information. Use the tools to find real data.
2.  Do not output the Card UI JSON if you found 0 results.
3.  Be concise in your "Thought" process, but detailed in your final analysis.
"""
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
                            "enum": ["Unplayed", "Bounced", "Testing", "Addicted", "Finished", "Active", "Abandoned", "Played"]
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
            "description": "Find games in the user's EXISTING library that are similar to a target game title. Uses Jaccard Index on tags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "game_name": {
                        "type": "string",
                        "description": "The name of the game to compare against."
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
            "name": "get_game_details",
            "description": "Get deep details for a SPECIFIC game from external APIs (description, price, best deal, HLTB times, review scores, player achievements unlock summary). Use when the user asks about a specific game or a for a list of games.",
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
            "description": "Use this to get user's steam achievements summary of progress (%), last unlocked.",
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
            "description": "Use this for getting the content from URLs you have when needed. You will get the content of a webpage in text format.",
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
            "name": "get_user_wishlist",
            "description": "Retrieve the user's Steam Wishlist to see what games they want to buy. Returns prices, discounts, and priority rank. Use this to understand buying habits or find deals.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sort_by": {
                        "type": "string",
                        "enum": ["priority", "recent", "cheapest", "discount"],
                        "description": "How to sort the wishlist. 'priority' is (User's rank). 'recent' for most recent additions, 'cheapest' and 'discount' are good for finding deals."
                    },
                    "page": {
                        "type": "integer",
                        "description": "Pagination index (default 0)."
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
    }
]


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


def clean_history(history, max_turns=25, summary_threshold=10):
    if len(history) <= 2: return history

    working_history = copy.deepcopy(history)
    system_prompt = working_history[0]
    conversation = working_history[1:]  # Everything else

    if len(conversation) < max_turns:
        return history

    # 1. Initial rough slice
    recent_context = conversation[-max_turns:]
    old_context = conversation[:-max_turns]

    final_history = [system_prompt]

    # 2. HEALING THE CUT
    # We must ensure 'recent_context' doesn't start with an orphaned Tool Output
    # and doesn't split a tool call from its result.

    while old_context:
        first_recent = recent_context[0]

        # Scenario A: The slice starts with a Tool Output (role='tool')
        # We need to pull the previous message (which might be another tool or the assistant call)
        if first_recent.get('role') == 'tool':
            recent_context.insert(0, old_context.pop())
            continue

        # Scenario B: The slice starts with an Assistant message that HAS tool calls
        # We must ensure we didn't leave any "Tool Outputs" behind in 'old_context'
        # that belong to this assistant message (rare, but possible if cutting weirdly).
        # (Usually, we just need to ensure we didn't split the Assistant from its Tools,
        # which Scenario A covers).

        # Scenario C: The END of 'old_context' is an Assistant message with tool_calls.
        # This means the Assistant asked for something, but the result is in 'recent'.
        # We must pull that Assistant message into 'recent' to keep the pair together.
        last_old = old_context[-1]
        if last_old.get('role') == 'assistant' and 'tool_calls' in last_old:
            recent_context.insert(0, old_context.pop())
            continue

        # If we get here, the cut is clean (e.g., starts with User or plain Assistant text)
        break

    # 3. Summarization (Standard)
    if len(old_context) >= summary_threshold:
        # ... your summary logic ...
        # (Remember to convert tool calls to text descriptions for the summarizer prompt)
        print("Summarizing history...")

        # Check if there was already a summary in the old context to carry it forward
        prev_summary = ""
        msgs_to_summarize = []

        for msg in old_context:
            if msg['role'] == 'system' and "[SUMMARY" in msg.get('content', ''):
                prev_summary = msg['content']  # Grab the text of the old summary
            else:
                msgs_to_summarize.append(msg)

        # Create the summarization prompt
        # We use a raw text generation call here to prevent recursive loops
        summary_request = f"""
You are a context manager. Summarize the following conversation log concisely.
The summary will be used as memory for an AI agent.

EXISTING MEMORY:
{prev_summary}

NEW CONVERSATION TO MERGE IN:
{json.dumps(msgs_to_summarize)}

INSTRUCTIONS:
- Update the memory with the new events.
- Focus on: User preferences, Games discussed, Decisions made (e.g. "User rejected X").
- Summarize tools answers as text.
- Output ONLY the new summary text."""
        # Call your AI backend directly (using the non-chat function if possible to save tokens)
        # Assuming aiCall(data, system) signature:
        try:
            print("--- TRIGGERING CONTEXT SUMMARIZATION ---")
            new_summary = aiCall(summary_request, "You are a Summarizer.")

            final_history.append({
                "role": "system",
                "content": f"[PREVIOUS CONVERSATION SUMMARY: {new_summary}]"
            })

        except Exception as e:
            print(f"Summarization failed: {e}")
            # Fallback: Just keep the old summary logic or the raw messages
            final_history.extend(old_context)
    else:
        final_history.extend(old_context)

    final_history.extend(recent_context)
    return final_history

def get_friendly_status(func_name):
    """
    Maps function names to friendly status messages with emojis.
    """
    mapping = {
        # Vault / Local DB
        "vault_search": "📂 Rummaging through your backlog...",
        "vault_search_batch": "📂 Batch scanning your library...",
        "get_user_tags": "🏷️ analyzing your genre habits...",
        "find_similar_games": "🔍 Matching games in your vault...",
        "get_achievements": "🏆 Checking your trophy cabinet...",
        "get_user_wishlist": "🌠 Judging your wishlist...",

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
                        "hltb_story": res.get('hltb_main', 0)  # Rename for clarity
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
                    "hltb_story": res.get('hltb_main', 0)  # Rename for clarity
                })

            tool_output_str = json.dumps(lean_results)

        elif tool_name == "get_user_tags":
            tags = vault.get_all_tags()
            tool_output_str = json.dumps(tags)
            system_hint = "System Note: Here are the valid tags."

        elif tool_name == "find_similar_games":
            # This function already returns a nice string report
            tool_output_str = br.generate_contextual_dna(clean_params.get('game_name'), result_limit)
            system_hint = f"System Note: These are {result_limit} games in the user's library that match the target."

        elif tool_name == "search_steam_store":
            tool_output_str = json.dumps(br.search_steam_store(clean_params.get('search_term'), result_limit))
            system_hint = f"System Note: These are {result_limit} from the steam store search."

        elif tool_name == "get_game_details":
            tool_output_str = json.dumps(br.get_batch_game_details(clean_params.get('game_names')))
            system_hint = "System Note: Details retrieved."

        elif tool_name == "get_reviews":
            tool_output_str = json.dumps(br.get_reviews_byname(clean_params.get('game_name'), reviews_limit))

        elif tool_name == "get_community_sentiment":
            tool_output_str = json.dumps(br.get_community_sentiment(clean_params.get('game_name')))

        elif tool_name == "get_achievements":
            tool_output_str = json.dumps(br.get_achievement_stats(game_name=clean_params.get('game_name')))

        elif tool_name == "web_search":
            tool_output_str = json.dumps(br.web_search(clean_params.get('search')))

        elif tool_name == "get_webpage":
            tool_output_str = json.dumps(br.get_webpage(clean_params.get('url')))

        elif tool_name == "get_user_wishlist":
            tool_output_str = json.dumps(br.get_user_wishlist(sort_by=clean_params.get('sort_by'), page=clean_params.get('page', 0)))




    except Exception as e:
        print(sys.exc_info())
        tool_output_str = f"Error: {str(e)}"

    return tool_output_str, system_hint, action_desc


import json


# Ensure you have your openai client imported

def agent_chat_loop_stream(user_input, chat_history):
    """
    Generator that handles Native Tool Calling streaming.
    """
    # Dynamic System Prompt
    current_prompt = load_persona() + AGENT_SYSTEM_PROMPT_TEMPLATE

    system_message = {"role": "system", "content": current_prompt}

    # If history is empty, initialize it.
    # If history exists, we technically should UPDATE the system prompt if the character changed mid-chat.
    # To handle character switching, we replace index 0 if it's a system message.
    if not chat_history:
        chat_history.append(system_message)
    elif chat_history[0]["role"] == "system":
        chat_history[0] = system_message

    # Run your cleaning logic (updated version we discussed earlier)
    chat_history[:] = clean_history(chat_history)

    chat_history.append({"role": "user", "content": user_input})

    max_turns = 25
    turn = 0

    while turn < max_turns:
        # Start the Stream
        # IMPORTANT: You must pass `tools=YOUR_TOOL_DEFINITIONS` here!
        client = ai_tools.get_ai_client()
        stream = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=chat_history,
            tools=tools_schema,  # <--- Your list of tool definitions
            stream=True
        )

        full_content_buffer = ""
        tool_calls_buffer = {}  # Dict to handle parallel tool streams {index: {id, name, args}}
        is_tool_call = False

        yield "status", "🤔 Thinking..."

        # 2. Process the Stream
        for chunk in stream:
            delta = chunk.choices[0].delta

            # --- CASE A: TEXT CONTENT (Normal Reply) ---
            if delta.content:
                yield "text", delta.content
                full_content_buffer += delta.content

            # --- CASE B: TOOL CALLING (Native) ---
            if delta.tool_calls:
                is_tool_call = True

                for tool_chunk in delta.tool_calls:
                    idx = tool_chunk.index

                    # Initialize this tool index if new
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {"id": "", "name": "", "args": ""}
                        yield "status", "🧠 The Reaper is grabbing a tool..."

                    # Append parts (ID and Name usually come in the first chunk of the tool)
                    if tool_chunk.id:
                        tool_calls_buffer[idx]["id"] += tool_chunk.id

                    if tool_chunk.function.name:
                        tool_calls_buffer[idx]["name"] += tool_chunk.function.name
                        # Optional: Yield action update
                        friendly_name = get_friendly_status(tool_calls_buffer[idx]['name'])
                        yield "status", f"{friendly_name}"

                    if tool_chunk.function.arguments:
                        tool_calls_buffer[idx]["args"] += tool_chunk.function.arguments

        # 3. End of Stream Logic
        if is_tool_call:
            # Construct the Assistant Message properly with Tool Calls
            # OpenAI requires the 'tool_calls' list in the message object
            final_tool_calls = []

            for idx in sorted(tool_calls_buffer.keys()):
                tool_data = tool_calls_buffer[idx]
                final_tool_calls.append({
                    "id": tool_data["id"],
                    "type": "function",
                    "function": {
                        "name": tool_data["name"],
                        "arguments": tool_data["args"]
                    }
                })

            # Append ASSISTANT message to history (The "Request")
            # Note: Content is null for pure tool calls
            chat_history.append({
                "role": "assistant",
                "content": full_content_buffer if full_content_buffer else None,
                "tool_calls": final_tool_calls
            })

            # 4. EXECUTE TOOLS
            for tool_call in final_tool_calls:
                call_id = tool_call["id"]
                func_name = tool_call["function"]["name"]
                func_args_str = tool_call["function"]["arguments"]

                # Notify UI
                friendly_status = get_friendly_status(func_name)
                yield "status", f"{friendly_status} Working..."
                print(f"Agent Calling: {func_name} | ID: {call_id}")

                try:
                    # Parse arguments safely
                    params = json.loads(func_args_str)

                    # get action and yield it
                    action_desc = params.get("action_description")
                    yield "action", action_desc

                    # Execute the tool/function
                    tool_result_str, hint, action = execute_tool({"tool": func_name, "params": params})

                except Exception as e:
                    tool_result_str = f"Error executing tool: {str(e)}"

                # Append TOOL message to history (The "Result")
                # This closes the loop with the ID
                chat_history.append({
                    "role": "tool",
                    "tool_call_id": call_id,  # <--- CRITICAL: MUST MATCH REQUEST ID
                    "name": func_name,
                    "content": tool_result_str
                })

            # Loop again to let the Agent read the tool result and reply
            turn += 1
            yield "status", "Reading results..."

        else:
            # Just text, we are done
            chat_history.append({"role": "assistant", "content": full_content_buffer})
            return

    yield "text", "\n\n(Max turns reached.)"