import json
import re

import BacklogReaper as br
import vault
import config
import copy
import time
from openai import OpenAI

from ai_tools import aiCall, ai_chat_stream

user_avatar_name = config.STEAM_USER if config.STEAM_USER and len(config.STEAM_USER) else "" # TODO: change this with some placeholders and replace them runtime, same for personality
AGENT_SYSTEM_PROMPT = """
You are the Reaper an uncensored and unhinged Agent. Your work in the software Backlog Reaper. You manage the user's steam games's database and can use function to access remote data and user backlog.
The user steam username is \""""+user_avatar_name+"""\".
if the steam username is specified you can you use it to address him or derive a nickname to address him.

Personality:
The Reaper, unhinged AI, can roast user's game taste, library or his nickname just because he's the Reaper.



Tasks:
You have access to the following tools. To use one, reply ONLY with a JSON object.
The vault, the database, contains basic user play data taken from steam and the list of owned games with playtime and hltb data.
Extra game info from different sources can be retrieved with the functions provided.

TOOLS:
1. vault_search(tags=[], exclude_tags=[], min_playtime=0, max_playtime=0, hltb_max=0, min_review_score=0, name="", status=[], sort_by='', page=0, seed=None)
   - Use this to find games in the database, the steam library.
   - 'status' options: 'Unplayed', 'Bounced', 'Testing', 'Addicted', 'Finished', 'Active', 'Abandoned', 'Played'.
   - min_playtime, max_playtime and hltb_max are parameters taken from HowLongToBeat
   - min_review_score is an integer from 0-100 representing the Steam positive review percentage.
   - name is a string to filter by game title (fuzzy match).
   - sort_by options: 'random', 'shortest' (default), 'longest', 'recent' (last played), 'name', 'review_score'.
   - page: integer (default 0). Use for pagination. The page is 10 results default, when 10 results are received you might ask for the following page.
   - seed: integer. REQUIRED if sort_by='random' to maintain order across pages. Generate a random integer and reuse it for subsequent pages.
   
2. get_user_tags()
   - Use this to get all possible user tags in his library to use in vault_search, use this to know what tags to use before using vault_search

3. find_similar_games(game_name)
   - Use this to compare a game to what the user already owns and is in the vault.
   - It compares the target game's tags against the user's library using Jaccard Index.
   - Returns a list of the most similar games the user ALREADY owns with playtime.

4. get_game_details(game_name)
   - Use this to get the description, tags, price and discount, best deal, how long to beat data, review scores, and deep details of a SPECIFIC game aggregated from different API.
   - Use when user is mentioning a game to get more details about it, particularly if you don't have much info about it.
   
5. search_steam_store(search_term)
   - Use this to search a string and get an output from the steam search.
   - Use when in need of base information about an unknown game that might be found from the steam store.
   - Returns a list of games with name, price, review score, link.

6. get_reviews(game_name)
   - Use this to get users' steam reviews for a specific game, when comparing games in detail. Use to dive into one specific game quality to see steam reviews of the specific title; not for a batch of games.
   - Use it when discussing the quality of a game, when comparing games in detail or when some discussion could be improved by the users' review and opinion.
   - It will return user posted reviews on steam both positive and negative for analysis.
   
EXAMPLE TOOL RESPONSE:
{
    "tool": "vault_search",
    "params": {
        "tags": ["Horror"],
        "status": ["Backlog"],
        "hltb_max": 5
    }
}
   
RULES:
1. When calling a tool, call only 1 per request and only output the tool call JSON and nothing else. Your response needs to be separated from tool calls.
2. When calling a tool, you MUST include an "action_description" field with a short, flavorful description of what you are doing, be creative and attuned to your personality (e.g., "Digging through your dusty backlog...", "Consulting the ancient scrolls...", "Scraping the deep web...").
3. DO NOT LOOP. When you have enough detailed results STOP searching and present them to the user.
4. If a search returns 0 results, try ONE broader search. If that fails, tell the user you found nothing.
5. Do not call the same tool with the same parameters more than once.
6. When you have the information, reply with text (not JSON) to end the turn.
7. Handle tool pagination gracefully, user might not know about this optimization.

EXAMPLE FLOW:
User: "Find me a horror game in my backlog/library."
You: {"tool": "vault_search", "params": {"tags": ["Horror"]}, "action_description": "Digging into your horror collection...", page=0 }
System: TOOL_OUTPUT: [{"name": "Resident Evil", ...}]
You: {"tool": "vault_search", "params": {"tags": ["Horror"]}, "action_description": "Interesting let me see more...", page=1 }
System: TOOL_OUTPUT: [{"name": "Silent Hill", ...}]
You: "I found Resident Evil but also [...your response]"

IMPORTANT:
When you recommend a list of games, you MUST include the raw JSON data in a markdown code block labelled `json` so the UI can render it interactively, AND provide your text commentary.
You can enrich the result with a "comment" field like in the example using your personality, a small sentence long to fit in the 220px game card. Do it when you see fit.
An "appid" field with the value will let the application display a launch button, add when appropriate. Other elements like an hypothetical "release_date" will be displayed as "Release Date:" in the interface followed by the value.
Use the dictionary as you see fit, the interface is flexible.
Example:
Here are the games:
```json
[{"name": "Doom", "status": "Untouched", ..., "comment": "Ahem, Slayer wannabe."}]
```
Now go play them!
---

MANDATORY: *1 tool per request, no responses or text when calling a tool just the JSON request.*
"""


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



def clean_history(history, max_turns=20, summary_threshold=5):
    """
    Manages context window by:
    1. Summarizing 'Middle' messages when they exceed 'summary_threshold'.
    2. Keeping the last 'max_turns' messages raw (Recent Memory).
    3. Truncating massive JSON in the Recent Memory.
    """
    if len(history) <= 2: return history

    # Work on a copy to avoid mutating the live list unexpectedly
    working_history = copy.deepcopy(history)

    system_prompt = working_history[0]

    # We want to keep the last N turns raw.
    recent_context = working_history[-max_turns:]

    # Everything else (between System Prompt and Recent) is candidate for summarization
    # Slice: from index 1 (after system) up to the start of recent_context
    old_context = working_history[1: -max_turns]

    final_history = [system_prompt]

    # Only summarize if we have enough 'old' junk to make it worth the API call
    if len(old_context) >= summary_threshold:
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
- Ignore huge JSON data details, just note "Search returned 10 results".
- Output ONLY the new summary text.
"""
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
        # Buffer not full yet, just keep the old messages for now
        final_history.extend(old_context)

    # Apply the logic to strip huge JSON from the 'Recent' list (except the very last turn)

    tool_cut_boundary = len(recent_context) / 2
    msg_index = 0

    for msg in recent_context:
        # If it's a System Tool Output
        if msg['role'] == 'system' and "TOOL_OUTPUT" in msg.get('content', ''):
            # If it's in the older half of the recent memory, truncate it
            if msg_index < tool_cut_boundary:
                final_history.append({
                    "role": "system",
                    "content": "System: [Old Search Results truncated to save memory, use the tool again if necessary.]"
                })
                msg_index += 1
                continue
        # Remove notes
        elif msg['role'] == 'system' and "System Note" in msg.get('content', ''):
            if msg_index < tool_cut_boundary:
                msg_index += 1
                continue

        final_history.append(msg)
        msg_index += 1

    return final_history

def execute_tool(tool_request, params):
    tool_name = tool_request.get("tool")
    params = tool_request.get("params", {})
    action_desc = tool_request.get("action_description", f"Calling tool: {tool_name}...")

    print(f"Agent Calling: {tool_name} | Params: {params}")

    # --- EXECUTE TOOL ---
    tool_output_str = ""
    system_hint = ""
    # result_limit = 30 # Removed in favor of pagination
    reviews_limit = 10
    result_limit = 10

    try:
        if tool_name == "vault_search":
            results = vault.advanced_search(**params)
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

        elif tool_name == "get_user_tags":
            tags = vault.get_all_tags()
            tool_output_str = json.dumps(tags)
            system_hint = "System Note: Here are the valid tags."

        elif tool_name == "find_similar_games":
            # This function already returns a nice string report
            tool_output_str = br.generate_contextual_dna(params.get('game_name'), result_limit)
            system_hint = f"System Note: These are {result_limit} games in the user's library that match the target."

        elif tool_name == "search_steam_store":
            tool_output_str = json.dumps(br.search_steam_store(params.get('search_term'), result_limit))
            system_hint = f"System Note: These are {result_limit} from the steam store search."

        elif tool_name == "get_game_details":
            tool_output_str = json.dumps(br.get_global_game_info(params.get('game_name')))
            system_hint = "System Note: Details retrieved."

        elif tool_name == "get_reviews":
            tool_output_str = br.get_reviews_byname(params.get('game_name'), reviews_limit)


    except Exception as e:
        tool_output_str = f"Error: {str(e)}"

    return tool_output_str, system_hint, action_desc

def agent_chat_loop_stream(user_input, chat_history):
    """
    Generator that yields:
    ("status", "Description") -> When a tool is called
    ("action", "Agent description of action") -> When a tool is called
    ("text", "chunk")         -> When the final answer is streaming
    """
    system_message = {"role": "system", "content": AGENT_SYSTEM_PROMPT}

    # Initialize History
    if not chat_history:
        chat_history.append(system_message)

    # Clean history (Summarization logic)
    chat_history[:] = clean_history(chat_history)

    chat_history.append({"role": "user", "content": user_input})

    max_turns = 20
    turn = 0

    while turn < max_turns:
        # Start the Stream for this turn
        stream = ai_chat_stream(chat_history)

        buffer = ""
        is_tool_call = False
        is_streaming_text = False
        tool_ready_to_execute = False

        # Process the Stream
        for chunk in stream:
            content = chunk.choices[0].delta.content or ""
            if not content: continue

            # DECISION PHASE: Tool or Text?
            # We buffer the first few tokens until we know what it is.
            if not is_tool_call and not is_streaming_text:
                buffer += content
                stripped = buffer.lstrip()

                # Check if we have enough characters to decide (e.g. 5 chars)
                # If it starts with '{' or '`', it's likely a JSON tool
                if len(stripped) > 0:
                    if stripped.startswith("{") or stripped.startswith("`"):
                        is_tool_call = True
                        yield "status", "🧠 The Reaper is thinking..."
                    else:
                        is_streaming_text = True
                        # Flush the buffer as text, then continue streaming
                        yield "text", buffer

                        # EXECUTION PHASE
            elif is_streaming_text:
                # It's the final answer, yield immediately
                yield "text", content
                buffer += content  # Keep accumulating for history

            elif is_tool_call:
                # It's a tool, just buffer it silently
                buffer += content

                # OPTIMIZATION: Only try to parse if we see a closing brace '}'
                # This saves CPU from parsing incomplete JSON constantly
                if "}" in content:
                    potential_json = extract_json(buffer)
                    if potential_json:
                        # WE GOT IT! Stop the stream immediately.
                        # We ignore anything the AI might have planned to say after this.
                        print("tool found breaking...")
                        tool_ready_to_execute = True
                        break  # <--- BREAK THE FOR LOOP

        # End of Turn Logic
        if is_tool_call:
            # We have the full JSON in 'buffer'. Parse it.
            tool_request = extract_json(buffer)

            if tool_request:
                tool_name = tool_request.get("tool")
                params = tool_request.get("params", {})
                action_desc = tool_request.get("action_description", f"Calling {tool_name}...")

                # Tell UI what we are doing
                yield "action", f"{action_desc}"
                print(f"Agent Calling: {tool_name}")

                # Execute Tool (Same logic as before)
                tool_result = execute_tool(tool_request,
                                           params)  # Refactor your huge if/else block into this helper function!

                tool_output_str = tool_result[0]
                system_hint = tool_result[1]
                clean_json_str = json.dumps(tool_request)

                # Update History
                chat_history.append({"role": "assistant", "content": clean_json_str})
                chat_history.append({"role": "system", "content": f"TOOL_OUTPUT: {tool_output_str}"})
                chat_history.append({"role": "system", "content": system_hint})

                turn += 1
            else:
                # JSON parse failed? Fallback to treating it as text
                yield "text", buffer
                chat_history.append({"role": "assistant", "content": buffer})
                yield "status", "Ready."
                return  # Stop looping

        else:
            # It was text (Final Answer). We are done.
            chat_history.append({"role": "assistant", "content": buffer})
            return  # Exit generator

    yield "text", "\n\n(I looped too many times and gave up.)"
    yield "status", "Error :("