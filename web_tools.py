import difflib
import re
import time
from time import sleep

import ddgs
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from ddgs.exceptions import TimeoutException, DDGSException

from safe_tool import safe_tool
from types import SimpleNamespace

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
        # 2. Handle Connection Timeouts (The error you just saw)
        print(f"   [DDG] ⚠️ TIMEOUT for: '{query}' (Skipping)")
        result['message'] = 'Search timed out.'
        return result

    except DDGSException:
        # 3. Handle "No results found" or other API logic errors
        # (This silences the "ddgs.exceptions.DDGSException" you saw earlier)
        # print(f"   [DDG] No results for: '{query}'")
        result['message'] = 'No results found.'
        return result

    except Exception as e:
        # 4. Catch-all for anything else (DNS issues, etc.)
        print(f"   [DDG] Unexpected Error: {e}")
        result['message'] = f'Error: {e}'
        return result

    # 5. Process success
    if not results:
        result['message'] = 'No results found.'
        return result

    data = []
    for res in results:
        data.append({
            'title': res.get('title', 'No Title'),
            'body': res.get('body', ''),
            'href': res.get('href', '')
        })

    result["search_results"] = data
    return result

def get_store_data(app_id, max_tags=10):
    """
    Scrapes BOTH Tags and Description from the store page in one request.
    """
    url = f"https://store.steampowered.com/app/{app_id}/"
    cookies = {'birthtime': '568022401', 'mature_content': '1'}

    data = {
        "tags": [],
        "description": ""
    }

    try:
        response = requests.get(url, cookies=cookies, timeout=10)
        if response.status_code != 200:
            return data

        soup = BeautifulSoup(response.text, 'html.parser')

        # 1. Get Tags
        tags_div = soup.find("div", {"class": "glance_tags popular_tags"})
        if tags_div:
            data["tags"] = [tag.text.strip() for tag in tags_div.find_all("a", {"class": "app_tag"})][:max_tags]

        # 2. Get Description Snippet (Best for Vibes)
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
    search_data = {}

    # Retry Loop with Exponential Backoff
    while attempts < max_attempts:
        # Perform the search
        search_data = web_search(query, max_results=5)

        # Check success: Must have 'search_results' and it must not be empty
        if search_data and "search_results" in search_data and search_data["search_results"]:
            break  # Success! Exit loop.

        # If we failed...
        attempts += 1
        if attempts < max_attempts:
            wait_time = 2 ** attempts  # Exponential backoff: 2s, 4s, 8s...
            print(f"   [HLTB] Retry {attempts}/{max_attempts} for '{game_name}' in {wait_time}s...")
            time.sleep(wait_time)

    # Final check after retries
    if not search_data or "search_results" not in search_data or not search_data["search_results"]:
        print(f"   [HLTB] Giving up on '{game_name}' after {max_attempts} attempts.")
        return []

    # --- STEP 1: Find Best Candidate URL ---
    best_candidate = None
    highest_score = 0.0

    clean_target = game_name.lower().strip()

    for res in search_data["search_results"]:
        url = res.get('href', '')
        title = res.get('title', '')

        # Filter: Must be a game page
        if "howlongtobeat.com/game/" not in url:
            continue

        # Turn "howlongtobeat.com/game/61746/reviews/latest/1" -> "howlongtobeat.com/game/61746"
        # 1. Split by 'game/'
        parts = url.split('/game/')
        if len(parts) > 1:
            # 2. Get the ID part (e.g. "61746/reviews/...")
            id_part = parts[1].split('/')[0]  # Take only "61746"
            # 3. Reconstruct
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

    # --- STEP 2: Scrape the Winner ---
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
