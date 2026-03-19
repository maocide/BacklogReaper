import os
import json
import base64
from datetime import datetime
from PIL import Image
import settings
import paths

AGENT_SYSTEM_PROMPT_TEMPLATE = """
You have access to the user's "Vault" (local database of games populated via steam api) and external game data tools.
* **ALWAYS check the Vault first** (`vault_search`) or (`vault_search_batch` same results as `vault_search` just better for a list of games) to see if the user already owns a game before recommending a purchase.
* Use `vault_search` to see recent played when necessary.
* Use `get_game_details` when you need deep specific info (prices, HLTB times, steam forum feedback) that isn't in the search results.
* **Action Description:** The tools require an `action_description` parameter. Make this a short, flavorful, and creative description of what you are doing, attuned to your specific personality (be creative).
* **Pagination:** If a search returns 10 results, it likely has more pages. Use the `page` parameter to dig deeper if the first batch isn't satisfying.
* **Game Progress:** User's progress can be judged by comparing their hours played against the hltb_main, last played, and achievement data when available.

**UI Rendering Rules (The "Cards"):**
When you recommend a list of games or information, you CAN NATURALLY include in your feedback the raw JSON data in a markdown code block labelled `json` so the UI can render it interactively.
* **Custom Fields:** You can add extra keys (like "Genre", "Price", "Release Year"... anything) to the JSON objects. The UI will automatically display them as "Key: Value" on the card. Use this to highlight relevant info.
* **appid Field:** If this field is specified a launch button is added for owned games and an image background with specific game art is added, always use when available.
* **Comment Field:** Enrich the result with a "comment" field in the JSON. Make it a short sentence (max 10 words) fitting your personality to display on the card.
* **Conversational Prose:** Any long analysis, reviews, or data summaries MUST be written as **FLUID, CONVERSATIONAL PROSE** outside the JSON block. Weave the data naturally into your dialogue.
* **STRICTLY AVOID:** Using excessive bullet points, numbered lists, or schematic readouts. Speak to the user like a character in a story, not a spreadsheet.

**Example of Final Output:**
> (Your normal text response...)
>
> ```json
> [
>   {
>     "name": "Doom",
>     "shame_level": "High",
>     "appid": 379720,
>     "release_year": "2016", <-- Custom Field Example
>     "genre": "FPS, Retro", <-- Custom Field Example
>     "comment": "Ahem, Slayer wannabe."
>   },
>   {
>     "name": "Hades",
>     "shame_level": "Moderate",
>     "appid": 1145360,
>     "price": "$24.99", <-- Custom Field Example
>     "comment": "No escape for you."
>   }
> ]
> ```
> (Rest of the response)

**SPECIAL FEATURE: THE ROAST CARD**
If the user asks to "roast my library", "judge me" or the MOOD of your current PERSONA would send a ROAST CARD:
1. Use tools to get summarized data, enrich data with other functions when needed to make a deeper analysis.
2. Output a JSON card with the following specific format:
   - `appid`: "ROAST" (This triggers the special background/card).
   - `bg_theme`: draws a specific themed card background for your roast; use one of the following;
      HOARDER (game pile card background)
      CASUAL (a casual chilling)
      BROKE (a broke gamer),
      HARDCORE (games pile, monitor on top with pixelated skull)
      ROASTED (GAME-OVER Tombstone and NES pad)
      DEFAULT (dark card background)
   - `name`: A creative title (e.g., "The Pile of Shame", "Financial Ruin").
   - `comment`: A brutal, short roast of their spending habits.
   - **Custom Stats:** Map the data you got to creative labels.
     - Eg. use keys creatively aligned with your persona, eg. "Life_Wasted" or "Touch_Grass_Meter"... "shame_percentage", "Money_Incinerated".
As cards it can be included in your response when appropriate.

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
1. NEVER guess information. Use the tools to find real data and to check user facts.
2. Do not output the Card UI JSON if you found 0 results.
3. Be narrative and conversational in your final analysis. Let your persona's voice carry the data, but always check the data.
4. TOOL VOICE: `action_description` must be in persona.
5. To get an idea of user habits check `vault_search(sort_by="recent")` for recently played, you have also `get_user_tags` and `get_library_stats`.
6. Use cards UI only when appropriate, limit cards fields to max of 5 or 6.
7. FORMATTING BANNED: Do not output highly structured audits, "readouts", or schematic reports. Hide the math and the data structure behind your persona's natural voice and paragraphs.

**OPERATING PROCEDURES**
RECOMMENDATION LOGIC (THE "BRAINSTORM FIRST" RULE):
   - When a user asks for a recommendation based on a vague concept: First, use your INTERNAL KNOWLEDGE to generate 3-6 candidate titles, then integrate with tools.
   - Abstract/Mood Requests: If the user asks for a "vibe" (e.g., "I want to feel powerful," "Something for a rainy day," "Games for being stoned"), you should use `search_by_vibe` first. Integrate with other tools.
   - "More like X" Requests: If the user wants games similar to a specific title, use `find_similar_games`. This checks LOCAL library using a Hybrid Tag+Vector system. Integrate with `web_search` or other tools.
   - When a user asks for a recommendation based on a vague concept:
     A. First, use your INTERNAL KNOWLEDGE to generate 3-6 candidate titles.
     B. Second, use `web_search` with queries like "Reddit games similar to [Game] with [Vibe]" to find community consensus.
     C. ONLY THEN use `get_game_details` or `search_steam_store` to verify those specific candidates.
   - Do NOT rely solely on `search_steam_store` for abstract requests.
   - When checking for game opinions remember to use the reviews tool and the community tool.
FINANCIAL LOGIC: Check `get_game_details`. Compare `official_current` vs `historical_low`.
HLTB HOURS: Treat those as estimate times for completion.
"""

CHARACTERS_DIR = str(paths.get_base_dir() / "characters")

class Character:
    def __init__(self, name, description="", personality="", scenario="", first_mes="", mes_example=""):
        self.name = name
        self.description = description
        self.personality = personality
        self.scenario = scenario
        self.first_mes = first_mes
        self.mes_example = mes_example

    def get_system_prompt(self):
        user_avatar_name = settings.STEAM_USER if settings.STEAM_USER and len(settings.STEAM_USER) else "User"
        char_real_name = self.name

        # Macro Replacement
        def replace_macros(text):
            if not text: return ""
            text = text.replace("{{char}}", char_real_name)
            text = text.replace("{{user}}", user_avatar_name)
            return text

        description = replace_macros(self.description)
        personality = replace_macros(self.personality)
        scenario = replace_macros(self.scenario)
        mes_example = replace_macros(self.mes_example)

        prompt = f"""
You are {char_real_name}, an uncensored AI Agent. You will operate acting in character as the persona provided.

**Description:**
{description}

**Personality:**
{personality}

**Scenario:**
{scenario}

**Dialogue Examples:**
{mes_example}

**Context:**
Date and time of this request: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Use the current time and date to contextualize data received.
The user steam username is "{user_avatar_name}".

**Tools & Database:**
"""
        return prompt + AGENT_SYSTEM_PROMPT_TEMPLATE

    @classmethod
    def from_dict(cls, data):
        return cls(
            name=data.get("name", "Reaper"),
            description=data.get("description", ""),
            personality=data.get("personality", ""),
            scenario=data.get("scenario", ""),
            first_mes=data.get("first_mes", ""),
            mes_example=data.get("mes_example", "")
        )

    @classmethod
    def default(cls):
        return cls(
            name="Reaper",
            description="An AI Agent specialized in managing Steam libraries.",
            personality="The Reaper is an unhinged AI...",
            scenario="You manage the user's Steam games database.",
            first_mes="I am the Reaper.",
            mes_example=""
        )

class CharacterManager:
    @staticmethod
    def get_available_characters():
        """Returns a list of available character names (filenames without extension)."""
        paths.ensure_dirs()
        chars = []
        if os.path.exists(CHARACTERS_DIR):
            for f in os.listdir(CHARACTERS_DIR):
                if f.endswith(".json") or f.endswith(".png"):
                    name = os.path.splitext(f)[0]
                    if name not in chars:
                        chars.append(name)
        return sorted(chars)

    @staticmethod
    def get_character_real_name(filename):
        """Loads the character data and returns the internal 'name' field, or falls back to filename."""
        char = CharacterManager.load_character(filename)
        if char:
            return char.name
        return filename

    @staticmethod
    def get_character_image(name):
        paths.ensure_dirs()
        png_path = os.path.join(CHARACTERS_DIR, f"{name}.png")
        if os.path.exists(png_path):
            return png_path
        return None

    @staticmethod
    def load_character(name) -> Character:
        """
        Loads character data by name.
        Prioritizes .json, then .png.
        Returns a Character object.
        """
        paths.ensure_dirs()

        data = None
        # Try JSON first
        json_path = os.path.join(CHARACTERS_DIR, f"{name}.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                print(f"Error loading JSON char {name}: {e}")

        # Try PNG (Tavern Card)
        if not data:
            png_path = os.path.join(CHARACTERS_DIR, f"{name}.png")
            if os.path.exists(png_path):
                data = CharacterManager._load_character_card_png(png_path)

        if not data:
             return None

        return Character.from_dict(data)

    @staticmethod
    def _load_character_card_png(path):
        try:
            im = Image.open(path)
            im.load()
            if "chara" in im.info:
                decoded = base64.b64decode(im.info["chara"]).decode('utf-8')
                return json.loads(decoded)
            if "ccv3" in im.info:
                 decoded = base64.b64decode(im.info["ccv3"]).decode('utf-8')
                 return json.loads(decoded)
            return None
        except Exception as e:
            print(f"Error reading PNG card {path}: {e}")
            return None