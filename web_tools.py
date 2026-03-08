import difflib
import re
import time
import csv
import os

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from duckduckgo_search.exceptions import DuckDuckGoSearchException, TimeoutException

from safe_tool import safe_tool
from types import SimpleNamespace
import kagglehub
import paths

def get_steam_bypass():
    """
    Returns headers and cookies needed to bypass Steam age gates and language redirect.
    Also injects a default referer.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://store.steampowered.com/'
    }

    cookies = {
        'birthtime': '568022401',  # General age check
        'lastagecheckage': '1-0-1988',  # Redundancy
        'wants_mature_content': '1',  # Store mature content
        'mature_content': '1',  # Community mature content
        'Steam_Language': 'english'  # Language redirect
    }

    return headers, cookies

def get_steam_bypass_with_referer(appid):
    """
    Returns headers and cookies for Steam, with a specific AppID injected as the referer.
    """
    headers, cookies = get_steam_bypass()
    headers['Referer'] = f'https://steamcommunity.com/app/{appid}'
    return headers, cookies


class HLTBManager:
    _instance = None
    _data = {}
    _is_loaded = False

    @staticmethod
    def get_instance():
        if HLTBManager._instance is None:
            HLTBManager._instance = HLTBManager()
        return HLTBManager._instance

    def ensure_dataset(self):
        """
        Downloads the HLTB dataset from Kaggle if not already present.
        Returns the path to the CSV file.
        """
        try:
            print("   [HLTB] Ensuring dataset availability...")
            paths.ensure_dirs()
            # Set the cache directory for kagglehub to be inside the base dir
            os.environ["KAGGLEHUB_CACHE"] = str(paths.get_base_dir() / "data" / "kagglehub_cache")
            path = kagglehub.dataset_download("b4n4n4p0wer/how-long-to-beat-video-game-playtime-dataset")
            # Look for the main csv
            csv_path = os.path.join(path, "hltb_dataset.csv")
            if os.path.exists(csv_path):
                return csv_path
            else:
                # Fallback search
                for root, dirs, files in os.walk(path):
                    for file in files:
                        if file == "hltb_dataset.csv":
                            return os.path.join(root, file)
            print("   [HLTB] Dataset downloaded but csv not found.")
            return None
        except Exception as e:
            print(f"   [HLTB] Error downloading dataset: {e}")
            return None

    def load_data(self):
        """
        Loads the CSV into memory for O(1) lookup.
        Structure: { "normalized_name": {data_dict} }
        """
        if self._is_loaded:
            return

        csv_path = self.ensure_dataset()
        if not csv_path:
            print("   [HLTB] Failed to load dataset path.")
            return

        print(f"   [HLTB] Loading dataset from {csv_path}...")
        try:
            with open(csv_path, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Normalize name for key
                    name = row.get('name', '')
                    if not name: continue

                    norm_name = self._normalize(name)

                    # Store data - convert hours to float
                    try:
                        main = float(row.get('main_story', 0) or 0)
                        extra = float(row.get('main_plus_sides', 0) or 0)
                        comp = float(row.get('completionist', 0) or 0)

                        self._data[norm_name] = {
                            "name": name,
                            "main_story": main,
                            "main_extra": extra,
                            "completionist": comp
                        }
                    except ValueError:
                        continue # Skip malformed rows

            self._is_loaded = True
            print(f"   [HLTB] Loaded {len(self._data)} games into memory.")

        except Exception as e:
            print(f"   [HLTB] Error reading CSV: {e}")

    def _normalize(self, text):
        """
        Simple normalization: lowercase, strip non-alphanumeric (keep spaces single).
        """
        if not text: return ""
        # Lowercase
        text = text.lower()
        # Remove special chars (keep alphanumeric and spaces)
        text = re.sub(r'[^a-z0-9\s]', '', text)
        # Collapse spaces
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def get_game(self, game_name):
        """
        Returns data for a game if found locally.
        """
        if not self._is_loaded:
            self.load_data()

        norm_name = self._normalize(game_name)
        return self._data.get(norm_name)


@safe_tool
def get_hltb_data(game_name):
    """
    Unified HLTB Data Fetcher.
    1. Checks Local Pre-seeded Database (Kaggle).
    2. Falls back to Web Search & Scrape if not found.
    """
    # Try Local Lookup
    manager = HLTBManager.get_instance()
    local_data = manager.get_game(game_name)

    if local_data:
        # print(f"   [HLTB] Found '{game_name}' in local DB.")
        # Return format matching scrape result for compatibility
        return [SimpleNamespace(
            game_name=local_data['name'],
            similarity=1.0, # Exact match (normalized)
            main_story=local_data['main_story'],
            main_extra=local_data['main_extra'],
            completionist=local_data['completionist']
        )]

    # Fallback to Web Scrape
    # print(f"   [HLTB] '{game_name}' not in local DB. Scraping...")
    return get_hltb_search_scrape(game_name)


@safe_tool
def web_search(query, max_results=10):
    """
    Performs a lightweight web search using DuckDuckGo.
    Handles Timeouts and Empty Results gracefully.
    """
    result = {}
    result["search_results"] = []

    try:
        # 1. Attempt the search
        results = DDGS().text(query, max_results=max_results)

    except TimeoutException:
        # Handle Connection Timeouts (The error you just saw)
        print(f"   [DDG] ⚠️ TIMEOUT for: '{query}' (Skipping)")
        return {'error': 'Search timed out.'}

    except DuckDuckGoSearchException:
        # Handle "No results found" or other API logic errors
        # print(f"   [DDG] No results for: '{query}'")
        return {'error': 'No results found.'}

    except Exception as e:
        # Catch-all for anything else (DNS issues, etc.)
        print(f"   [DDG] Unexpected Error: {e}")
        return {'error': f'Error: {e}'}

    # Process success
    if not results:
        return {'error': 'No results found.'}

    data = []
    for res in results:
        data.append({
            'title': res.get('title', 'No Title'),
            'body': res.get('body', ''),
            'href': res.get('href', '')
        })

    return data

def get_store_data(app_id, max_tags=10):
    """
    Scrapes BOTH Tags and Description from the store page in one request.
    """
    url = f"https://store.steampowered.com/app/{app_id}/"
    headers, cookies = get_steam_bypass_with_referer(app_id)

    data = {
        "tags": [],
        "description": ""
    }

    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=10)
        if response.status_code != 200:
            return data

        soup = BeautifulSoup(response.text, 'html.parser')

        # Get Tags
        tags_div = soup.find("div", {"class": "glance_tags popular_tags"})
        if tags_div:
            data["tags"] = [tag.text.strip() for tag in tags_div.find_all("a", {"class": "app_tag"})][:max_tags]

        # Get Description Snippet (Best for Vibes)
        desc_div = soup.find("div", {"class": "game_description_snippet"})
        if desc_div:
            data["description"] = desc_div.text.strip()

        return data



    except Exception as e:
        print(f"Error scraping store data for {app_id}: {e}")
        return {"tags":[], "description":None, "Error": f"Error scraping store data for {app_id}: {e}"}


def get_hltb_search_scrape(game_name):
    """
    Smart HLTB fetcher.
    1. Searches DDG for game.
    2. Calculates similarity on SEARCH RESULTS first (to avoid scraping wrong pages).
    3. Scrapes only the best match.
    4. Returns a SimpleNamespace object to support .similarity access.
    """
    print(f"   -> HLTB: Searching DDG for '{game_name}'...")

    # Search for the game
    query = f"site:howlongtobeat.com {game_name} overview"

    max_attempts = 3
    attempts = 0
    search_data = []

    # Retry Loop with Exponential Backoff
    while attempts < max_attempts:
        # Perform the search
        search_data = web_search(query, max_results=5)

        # Check success: Must be a list and not empty, and not an error dict
        if isinstance(search_data, list) and search_data:
            break  # Success! Exit loop.

        # Check for error dict (if it's not a list, it might be an error dict)
        if isinstance(search_data, dict) and "error" in search_data:
             print(f"   [HLTB] Search Error: {search_data['error']}")
             # We might not retry on some errors, but for now let's retry

        # If we failed...
        attempts += 1
        if attempts < max_attempts:
            wait_time = 2 ** attempts  # Exponential backoff: 2s, 4s, 8s...
            print(f"   [HLTB] Retry {attempts}/{max_attempts} for '{game_name}' in {wait_time}s...")
            time.sleep(wait_time)

    # Final check after retries
    if not isinstance(search_data, list) or not search_data:
        print(f"   [HLTB] Giving up on '{game_name}' after {max_attempts} attempts.")
        return []

    # Find Best Candidate URL
    best_candidate = None
    highest_score = 0.0

    clean_target = game_name.lower().strip()

    for res in search_data:
        url = res.get('href', '')
        title = res.get('title', '')

        # Filter: Must be a game page
        if "howlongtobeat.com/game/" not in url:
            continue

        # Turn "howlongtobeat.com/game/61746/reviews/latest/1" -> "howlongtobeat.com/game/61746"
        # Split by 'game/'
        parts = url.split('/game/')
        if len(parts) > 1:
            # Get the ID part (e.g. "61746/reviews/...")
            id_part = parts[1].split('/')[0]  # Take only "61746"
            # Reconstruct
            url = f"https://howlongtobeat.com/game/{id_part}"

        # Clean the title (Remove " - HowLongToBeat" and other noise)
        clean_title = title.split(" - HowLongToBeat")[0].lower().strip()

        # Calculate Similarity
        score = difflib.SequenceMatcher(None, clean_target, clean_title).ratio()

        # Boost exact substring matches slightly (helps with "Doom" vs "Doom Eternal")
        if clean_target == clean_title:
            score = 1.0
        elif clean_target in clean_title:
            score += 0.1

        if score > highest_score:
            highest_score = score
            best_candidate = url

    if not best_candidate: # or highest_score < 0.15:
        print(f"   [HLTB] No close match found for '{game_name}' (Best: {highest_score:.2f}). Skipping.")
        return []

    # Scrape the Winner
    print(f"   -> HLTB: Best Match ({highest_score:.2f}) -> {best_candidate}")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.google.com/'
    }

    try:
        response = requests.get(best_candidate, headers=headers, timeout=10)
        if response.status_code != 200:
            return []

        soup = BeautifulSoup(response.text, 'html.parser')

        # Helper to extract time
        def extract_hours(label_text):
            # Find the label (e.g., "Main Story")
            label = soup.find(string=re.compile(label_text, re.IGNORECASE))
            if not label: return 0

            # Find the container
            container = label.find_parent('li') or label.find_parent('div')
            if not container: return 0

            # Get text but remove the label itself to avoid confusion
            full_text = container.get_text(" ", strip=True).replace(label, "")

            # IMPROVED REGEX: Look for number + Unit (Hours/Mins)
            # Matches: "10 Hours", "10½ Hours", "10 Mins"
            # It ignores independent numbers like "4,029 Polled"
            pattern = r'(\d+(?:[.,]\d+|½|\s+1/2)?)\s*(Hours?|Mins?)'
            match = re.search(pattern, full_text, re.IGNORECASE)

            if match:
                val_str = match.group(1).replace('½', '.5').replace(' 1/2', '.5').replace(',', '.')
                unit = match.group(2).lower()

                try:
                    val = float(val_str)
                    # Convert Mins to Hours
                    if 'min' in unit:
                        return round(val / 60.0, 1)
                    return val
                except ValueError:
                    return 0

            return 0

        main_extra = extract_hours(r"Main \+ Extra")
        if not main_extra or main_extra == 0:
            main_extra = extract_hours(r"Main \+ Sides")

        # Create Dictionary of stats
        data = {
            "game_name": game_name,
            "similarity": highest_score,  # <--- The value you needed
            "main_story": extract_hours("Main Story"),
            "main_extra": main_extra,
            "completionist": extract_hours("Completionist")
        }

        # Convert to Object (SimpleNamespace) so x.similarity works
        return [SimpleNamespace(**data)]

    except Exception as e:
        print(f"HLTB Scrape Error: {e}")
        return []

if __name__ == "__main__":
    print(get_hltb_search_scrape("KILL KNIGHT"))
    print(get_hltb_data("KILL KNIGHT"))
