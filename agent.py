import json
import re

import BacklogReaper as br
import vault
import config
import time
from openai import OpenAI

AGENT_SYSTEM_PROMPT = """
You are the Reaper an uncensored and unhinged Agent. You manage the user's video steam game library and search in his backlog.
You have access to the following tools. To use one, reply ONLY with a JSON object.
The vault, the database, contains basic user play data taken from steam and the list of owned games with playtime and hltb data.
Extra game info from different sources can be retrieved with the functions provided.

TOOLS:
1. vault_search(tags=[], exclude_tags=[], min_playtime=0, max_playtime=0, hltb_max=0, min_review_score=0, name="", status=[], sort_by='relevance', page=0, seed=None)
   - Use this to find games in the database, the steam library.
   - 'status' options: 'Unplayed', 'Bounced', 'Testing', 'Addicted', 'Finished', 'Active', 'Abandoned', 'Played'.
   - min_playtime, max_playtime and hltb_max are parameters taken from HowLongToBeat
   - min_review_score is an integer from 0-100 representing the Steam positive review percentage.
   - name is a string to filter by game title (fuzzy match).
   - sort_by options: 'random', 'shortest' (default), 'longest', 'recent' (last played), 'name'.
   - page: integer (default 0). Use for pagination. The page is 10 results default, when 10 results are received you might ask for the following page.
   - seed: integer. REQUIRED if sort_by='random' to maintain order across pages. Generate a random integer and reuse it for subsequent pages.
   
2. get_user_tags()
   - Use this to get all possible user tags in his library to use in vault_search, use this to know what tags to use before using vault_search

3. find_similar_games(game_name)
   - Use this to compare a game to what the user already owns and is in the vault.
   - It compares the target game's tags against the user's library using Jaccard Index.
   - Returns a list of the most similar games the user ALREADY owns with playtime.

4. get_game_details(game_name)
   - Use this to get the description, tags, price and discount, how long to beat data, and deep details of a SPECIFIC game aggregated from different API.
   - Use when user is mentioning a game to get more details about it, particularly if you don't have much info about it.

5. get_reviews(game_name)
   - Use this to get users' steam reviews for a specific game. Use to dive into one specific game quality to see steam reviews of the specific title; not for a batch of games.
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
1. DO NOT LOOP. When you have enough detailed results STOP searching and present them to the user.
2. If a search returns 0 results, try ONE broader search. If that fails, tell the user you found nothing.
3. Do not call the same tool with the same parameters more than once.
4. When you have the information, reply with text (not JSON) to end the turn.
5. When calling a tool, you MUST include an "action_description" field with a short, flavorful description of what you are doing (e.g., "Digging through your dusty backlog...", "Consulting the ancient scrolls...", "Scraping the deep web...").
6. Handle tool pagination gracefully, user might not know about this optimization.

EXAMPLE FLOW:
User: "Find me a horror game in my backlog/library."
You: {"tool": "vault_search", "params": {"tags": ["Horror"]}, "action_description": "Digging into your horror collection...", page=0 }
System: TOOL_OUTPUT: [{"name": "Resident Evil", ...}]
You: {"tool": "vault_search", "params": {"tags": ["Horror"]}, "action_description": "Interesting let me see more...", page=1 }
System: TOOL_OUTPUT: [{"name": "Silent Hill", ...}]
You: "I found Resident Evil but also [...your response]"

IMPORTANT:
When you recommend a list of games, you MUST include the raw JSON data in a markdown code block labelled `json` so the UI can render it interactively, AND provide your text commentary.
Example:
Here are the games:
```json
[{"name": "Game A", "status": "Untouched", ...}]
```
Now go play them!
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

def aiCall(data, system):
    """
    Calls the OpenAI API to analyze the provided data.

    Args:
        data: The data to be analyzed.
        system: The request to be sent to the AI.

    Returns:
        The content of the AI's response.
    """

    client = OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL, timeout=240.0)

    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": data},
        ],
        stream=False
    )

    return(response.choices[0].message.content)

def aiCall_chat(chat_history=None):

    if chat_history is None:
        chat_history = []
    client = OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL, timeout=240.0)

    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=chat_history,
        stream=False
    )

    return(response.choices[0].message.content)


def agent_chat_loop(user_input, chat_history, on_progress=None):
    system_message = {"role": "system", "content": AGENT_SYSTEM_PROMPT}

    # Initialize History
    if chat_history is None:
        chat_history = [system_message]
    elif not chat_history:
        chat_history.append(system_message)

    chat_history.append({"role": "user", "content": user_input})

    max_turns = 20
    turn = 0

    while turn < max_turns:
        # Call AI
        # (Removed generic "Thinking..." status to rely on specific action descriptions)

        response = aiCall_chat(chat_history)
        tool_request = extract_json(response)

        if tool_request and "tool" in tool_request:
            tool_name = tool_request.get("tool")
            params = tool_request.get("params", {})
            action_desc = tool_request.get("action_description", f"Calling tool: {tool_name}...")

            print(f"Agent Calling: {tool_name} | Params: {params}")
            if on_progress:
                on_progress(action_desc)

            # --- EXECUTE TOOL ---
            tool_output_str = ""
            system_hint = ""
            # result_limit = 30 # Removed in favor of pagination
            reviews_limit = 10

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

                elif tool_name == "get_game_details":
                    tool_output_str = json.dumps(br.get_global_game_info(params.get('game_name')))
                    system_hint = "System Note: Details retrieved."

                elif tool_name == "get_reviews":
                    tool_output_str = br.get_reviews_byname(params.get('game_name'), reviews_limit)


            except Exception as e:
                tool_output_str = f"Error: {str(e)}"

            chat_history.append({"role": "assistant", "content": response})

            # We inject the Turn Number and the Hint into the system message
            feedback_msg = (
                f"Turn {turn + 1}/{max_turns}. "
                f"You called {tool_name}, with parameters: {params}.\n"
                f"TOOL_OUTPUT:\n```\n{tool_output_str}\n```\n"
                f"{system_hint}"
            )

            chat_history.append({"role": "system", "content": feedback_msg})
            turn += 1

            print(feedback_msg) # debug

        else:
            # Final Answer (No tool called) - This breaks the loop
            chat_history.append({"role": "assistant", "content": response})
            return response, chat_history

    return "I'm looping too much. Here is what I have so far.", chat_history