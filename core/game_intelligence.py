
import difflib
import json
import platform
import re
import statistics
import urllib
import urllib.parse
from collections import Counter
from pprint import pprint
import time
from time import sleep
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote
import concurrent
import requests
import trafilatura
from ddgs import DDGS
from curl_cffi import requests as curl_requests
import steamspypi
from bs4 import BeautifulSoup
from thefuzz import fuzz
import core.vault as vault
import core.vibe_engine as vibe_engine
import core.text_utils as text_utils
from core.ai_tools import aiCall, clean_json_for_ai, get_summarizer_model
from core.vault import calculate_status
import concurrent.futures
from datetime import datetime
from steam_web_api import Steam
import core.settings as settings
from core.safe_tool import safe_tool
from core.web_tools import get_hltb_data, get_store_data, get_steam_bypass, get_steam_bypass_with_referer

max_tags = 10
steam_id = None

def resolve_steam_id(username_or_id):
    """
    Resolves a Steam username, vanity URL, or ID into the mandatory 64-bit numeric SteamID.
    """

    global steam_id

    if steam_id:
        return steam_id

    steam = Steam(settings.STEAM_API_KEY)

    # Check if it's already a numeric ID
    if username_or_id and username_or_id.isdigit() and len(username_or_id) == 17:
        return username_or_id

    # Try resolving as a Vanity URL (The most common case)
    # This hits: https://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/
    try:
        user_data = steam.users.search_user(username_or_id)

        # search_user: {'player': {'steamid': '765...', ...}}
        if 'player' in user_data and 'steamid' in user_data['player']:
            return user_data['player']['steamid']

    except Exception as e:
        print(f"Error resolving Steam ID: {e}")

    return None

def get_steam_avatar(username_or_id):
    """
    Fetches the URL of the user's full-size Steam avatar.
    Handles both SteamIDs (digits) and Vanity URLs (names).
    """
    global steam_id

    if not steam_id:
        steam_id = resolve_steam_id(settings.STEAM_USER)

    # Resolve Vanity URL if input is not digits (e.g., "maocide")
    if steam_id:
        resolve_url = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/"
        params = {'key': settings.STEAM_API_KEY, 'vanityurl': username_or_id}
        try:
            r = requests.get(resolve_url, params=params)
            data = r.json()
            if data['response']['success'] == 1:
                steam_id = data['response']['steamid']
            else:
                print(f"Error resolving vanity URL: {data}")
                return None  # Or return a default asset path
        except Exception as e:
            print(f"API Error: {e}")
            return None

    # Get Player Summary (contains the avatar)
    summary_url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
    params = {'key': settings.STEAM_API_KEY, 'steamids': steam_id}

    try:
        r = requests.get(summary_url, params=params)
        data = r.json()
        players = data['response']['players']

        if players:
            # Returns the URL for the 184x184px image
            return players[0]['avatarfull']
    except Exception as e:
        print(f"API Error: {e}")

    return None

_wishlist_ids_cache = {"fetched_at": 0.0, "appids": set()}


def get_wishlist_appids(force_refresh: bool = False) -> Set[int]:
    """Retrieve and cache the user's Steam Wishlist AppIDs for fast O(1) badge lookups."""
    global _wishlist_ids_cache, steam_id
    now = time.time()
    if not force_refresh and _wishlist_ids_cache["appids"] and (now - _wishlist_ids_cache["fetched_at"]) < 300:
        return _wishlist_ids_cache["appids"]

    try:
        if not steam_id:
            steam_id = resolve_steam_id(settings.STEAM_USER)
        if steam_id:
            steam = Steam(settings.STEAM_API_KEY)
            raw = steam.users.get_profile_wishlist(steam_id)
            if isinstance(raw, list):
                ids = {int(x["appid"]) for x in raw if isinstance(x, dict) and "appid" in x and str(x["appid"]).isdigit()}
                _wishlist_ids_cache["fetched_at"] = now
                _wishlist_ids_cache["appids"] = ids
                return ids
    except Exception as e:
        print(f"Warning: Failed to fetch wishlist appids: {e}")
    return _wishlist_ids_cache["appids"]


def is_game_wishlisted(appid: Any) -> bool:
    """Return True if the game is present on the user's Steam Wishlist."""
    if not appid or not str(appid).isdigit():
        return False
    return int(appid) in get_wishlist_appids()


@safe_tool
def search_steam_store(
    term: str = "",
    tags: Optional[List[str]] = None,
    specials_only: bool = False,
    sort_by: str = "relevance",
    ownership: str = "all",
    limit: int = 10,
):
    """
    Scrapes the Steam Search page for games matching keywords, genre/mechanic tags, and sales filters.
    - term: keyword/title query (optional if tags or specials_only are provided)
    - tags: genre/mechanic tags projected onto official Steam tag IDs via VibeEngine
    - specials_only: if True, returns only games currently discounted or on sale (&specials=1)
    - sort_by: 'relevance' (default), 'recent' (Released_DESC), 'reviews' (Reviews_DESC), 'lowest_price' (Price_ASC)
    - ownership: 'all' (default), 'unowned' (only unowned games), or 'owned'
    - limit: max results to return
    """
    query_parts = ["category1=998"]  # Games only (no DLC/soundtracks)

    clean_term = (term or "").strip()
    if clean_term:
        encoded_term = urllib.parse.quote(clean_term)
        query_parts.append(f"term={encoded_term}")

    # Resolve semantic tags to Steam tag IDs via VibeEngine
    if tags:
        vibe = vibe_engine.VibeEngine.get_instance()
        resolved_tags = vibe.resolve_steam_tag_ids(tags)
        tag_ids = [str(t["tagid"]) for t in resolved_tags if "tagid" in t]
        if tag_ids:
            query_parts.append(f"tags={','.join(tag_ids)}")

    if specials_only:
        query_parts.append("specials=1")

    sort_lower = (sort_by or "relevance").lower()
    if sort_lower in ("recent", "release_date", "new"):
        query_parts.append("sort_by=Released_DESC")
    elif sort_lower in ("reviews", "score", "rating"):
        query_parts.append("sort_by=Reviews_DESC")
    elif sort_lower in ("lowest_price", "price_asc", "price"):
        query_parts.append("sort_by=Price_ASC")

    url = f"https://store.steampowered.com/search/?{'&'.join(query_parts)}"

    headers, cookies = get_steam_bypass()
    response = requests.get(url, headers=headers, cookies=cookies, timeout=10)
    soup = BeautifulSoup(response.text, 'html.parser')

    results = []
    rows = soup.select('#search_resultsRows > a')
    wishlist_ids = get_wishlist_appids()

    for row in rows:
        title_el = row.select_one('.title')
        if not title_el:
            continue
        title = title_el.text.strip()

        # Extract AppID from URL
        href = row.get('href', '')
        appid_match = re.search(r'/app/(\d+)', href)
        appid = appid_match.group(1) if appid_match else "N/A"

        # Check ownership and wishlist status
        is_owned = False
        is_wishlisted = False
        if appid and appid.isdigit():
            aid = int(appid)
            is_owned = vault.is_game_owned(aid)
            is_wishlisted = aid in wishlist_ids

        # Filter by library ownership if requested
        if ownership == "unowned" and is_owned:
            continue
        if ownership == "owned" and not is_owned:
            continue

        # Extract Price & Discount (modern Steam markup uses .discount_block/.discount_final_price)
        price = "N/A"
        discount = "None"
        pct_el = row.select_one('.discount_pct')
        if pct_el:
            discount = pct_el.text.strip() or "None"

        final_el = row.select_one('.discount_final_price')
        if final_el:
            price = final_el.text.strip() or "N/A"
        else:
            discount_block = row.select_one('.discount_block')
            if discount_block:
                raw_txt = discount_block.text.strip()
                if "Free" in raw_txt:
                    price = "Free"
                elif raw_txt:
                    price = raw_txt
            else:
                price_div = row.select_one('.search_price')
                if price_div:
                    raw_price = price_div.text.strip().split('$')
                    price = f"${raw_price[-1]}" if len(raw_price) > 1 else price_div.text.strip()

        if "free" in price.lower():
            price = "Free"

        # Extract Reviews
        review_span = row.select_one('.search_review_summary')
        reviews = "Unknown"
        if review_span:
            reviews = review_span.get('data-tooltip-html', '').split('<br>')[0]

        # Extract Release Date
        released_div = row.select_one('.search_released')
        release_date = released_div.text.strip() if released_div else "Unknown"

        results.append({
            "appid": appid,
            "name": title,
            "release_date": release_date,
            "price": price,
            "discount": discount,
            "reviews": reviews,
            "link": href,
            "owned": is_owned,
            "on_wishlist": is_wishlisted,
        })

        if len(results) >= limit:
            break

    return results

@safe_tool
def get_similar_games(game_name):
    """
    Calls steam api and steamspy to get recommended similar games and their details

    Args:
        :param game_name: the name of the game to search for
    Returns:
        :return: the game details and a max of 9 similar games details according to steam
    """
    # Get app info from api
    app = get_steam_app_info(game_name)
    if not app:
        return {"error": f"Game '{game_name}' not found on Steam."}

    target_appid = app["id"][0]

    headers, cookies = get_steam_bypass_with_referer(target_appid)
    # This URL is what the Steam Client uses to populate the "More Like This" section
    url = f"https://store.steampowered.com/recommended/morelike/app/{target_appid}/"
    response = requests.get(url, headers=headers, cookies=cookies, timeout=10)

    soup = BeautifulSoup(response.content, 'html.parser')

    # Target the specific grid container.
    # The main "Similar Items" list usually has the id="released" in this specific view.
    container = soup.find('div', id="released")

    if container:
        items = container.find_all('a', class_='similar_grid_capsule')[:9]
    else:
        items = soup.find_all('a', class_='similar_grid_capsule')[:9]

    if not items:
        return {"error": f"Could not extract 'More Like This' store capsules for '{game_name}'."}

    games_found = []

    for item in items:
        url = item.get('href')

        # Extract the title from the URL
        # URL format: https://store.steampowered.com/app/ID/GAME_NAME/?snr=...
        try:
            # Use urllib to robustly parse the URL path
            parsed = urllib.parse.urlparse(url)
            # path is usually /app/123/Name_Of_Game/
            path_segments = [s for s in parsed.path.split('/') if s]

            if len(path_segments) >= 3 and path_segments[0] == 'app':
                game_id = int(path_segments[1])
                game_slug = path_segments[2]
            else:
                continue

            # Clean up the name (remove underscores, decode URL characters)
            game_title = urllib.parse.unquote(game_slug).replace('_', ' ')

            games_found.append({
                "title": game_title,
                "appid": game_id,
                "url": url
            })
        except (IndexError, ValueError):
            continue

    print(f"Found {len(games_found)} games:")
    similar_games = []

    # Add target game first (Main Thread)
    similar_games.append(get_global_game_info(game_name, appid=target_appid))

    # Fetch similar games in parallel using ThreadPoolExecutor
    # Limiting to 4 workers to prevent overwhelming SteamSpy/Steam APIs
    # (Since get_global_game_info spawns its own threads, we keep this outer pool small)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_game = {
            executor.submit(get_global_game_info, game['title'], appid=game['appid']): game
            for game in games_found
        }

        for future in concurrent.futures.as_completed(future_to_game):
            game = future_to_game[future]
            print(f"- Fetched: {game['title']}")
            try:
                payload = future.result()
                similar_games.append(payload)
            except Exception as e:
                print(f"Error fetching details for {game['title']}: {e}")
                # Optional: Append error placeholder or skip

    return similar_games


@safe_tool
def get_game_deals(title, appid):
    def fetch_with_retry(url, params=None, retries=3, backoff_factor=1.0):
        for i in range(retries):
            try:
                response = curl_requests.get(url, params=params, impersonate="chrome120", timeout=10)
                if response.status_code == 429:
                    wait_time = backoff_factor * (2 ** i)
                    print(f"Rate limited (429). Retrying in {wait_time}s...")
                    sleep(wait_time)
                    continue
                response.raise_for_status()
                return response
            except Exception as e:
                wait_time = backoff_factor * (2 ** i)
                print(f"Request failed: {e}. Retrying in {wait_time}s...")
                sleep(wait_time)
                if i == retries - 1:
                    # Return None instead of raising to let safe_tool handle or return clean error
                    print(f"Max retries reached for {url}")
                    return None
        return None

    # Find the Game
    search_url = "https://www.cheapshark.com/api/1.0/games"
    search_params = {
        "title": title,
        "steamAppID": appid
    }

    print("Searching CheapShark for game...")
    response = fetch_with_retry(search_url, params=search_params)
    if not response:
        return {"error": "Failed to fetch deals after retries."}

    # Parse the JSON list
    games_list = response.json()

    if not games_list:
        print("No games found!")
        return {"error": "No deals found."}

    # The API returns a list, so we take the first item [0]
    first_match = games_list[0]

    # Extract the specific ID we need
    raw_deal_id = first_match['cheapestDealID']
    deal_id = unquote(raw_deal_id)
    game_name = first_match['external']

    print(f"   Found: {game_name}")
    print(f"   Deal ID: {deal_id}")

    # Use the ID for the Second Request
    deal_url = "https://www.cheapshark.com/api/1.0/deals"
    deal_params = {
        "id": deal_id
    }

    print("\nFetching CheapShark specific deal details...")
    deal_response = fetch_with_retry(deal_url, params=deal_params)
    if not deal_response:
        return {"error": "Failed to fetch specific deal details after retries."}

    deal_data = deal_response.json()

    # Print the final details
    print("\n--- Deal Details ---")
    print(f"Store ID: {deal_data['gameInfo']['storeID']}")
    print(f"Price: ${deal_data['gameInfo']['salePrice']}")
    print(f"Retail: ${deal_data['gameInfo']['retailPrice']}")

    store_url = "https://www.cheapshark.com/api/1.0/stores"
    store_params = {}

    store_response = fetch_with_retry(store_url)
    if not store_response:
        return {"error": "Failed to fetch stores list after retries."}

    store_data = store_response.json()
    store_name = ""
    for store in store_data:
        if store["storeID"] == deal_data['gameInfo']['storeID']:
            store_name = store["storeName"]
            break


    best_deal = {
        "store" : store_name,
        "price" : deal_data['gameInfo']['salePrice']
    }


    #print(best_deal)
    return best_deal
    # print(json.dumps(deal_data, indent=2))

@safe_tool
def get_global_game_info(game_name, appid=None):
    """
    Retrieves comprehensive information about a game from various sources.

    This function aggregates data from Steam (app info, details, reviews summary),
    SteamSpy (game info, tags), and HowLongToBeat.com to provide a detailed
    payload for a given game. It handles cases where tags might not be available
    from SteamSpy by falling back to real-time tag scraping from the Steam store.
    It also calculates a user approval percentage based on positive and negative reviews.

    Args:
        game_name (str): The name of the game to retrieve information for.
        appid (int|str): Optional AppID to skip the search step.

    Returns:
        dict: A dictionary containing aggregated game information
    """

    # Must get the AppID first
    if appid is None:
        app_info = get_steam_app_info(game_name)
        if not app_info:
            return {"error": "Could not retrieve game information (appid)."}

        appid = app_info['id'][0]

    # Define the tasks we want to run in parallel
    tasks = {
        "details": (get_steam_app_details, appid),
        "spy": (get_steamspy_game_info, appid),
        "reviews": (get_reviews_summary, appid),
        "hltb": (get_hltb_data, game_name),
        "discount": (get_steam_app_discount, game_name),
        "deals": (get_game_deals, game_name, appid),
    }



    results = {}

    is_owned = vault.is_game_owned(appid)
    # Achievements not here
    # if is_owned:
    #     tasks["achievements"] = (get_achievement_stats, appid)
    # else:
    #     # Just return a placeholder so the Agent knows why it's missing
    #     results["achievements"] = "Game not owned."

    # Launch threads
    # max_workers=8 is usually plenty for network requests
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        # Submit all tasks
        future_to_key = {
            executor.submit(func, *args): key
            for key, (func, *args) in tasks.items()
        }

        # Wait for them to complete
        for future in concurrent.futures.as_completed(future_to_key):
            key = future_to_key[future]
            try:
                results[key] = future.result()
            except Exception as e:
                print(f"Task '{key}' failed: {e}")
                results[key] = None  # Handle failure gracefully

    # Unpack Results (Logic remains mostly the same, just reading from 'results' dict)
    app_details = results.get("details") or {}
    game_info = results.get("spy") or {}
    summary = results.get("reviews") or {}
    how_long_to_beat = results.get("hltb")
    discount = results.get("discount")
    best_deal = results.get("deals")
    #achievements = results.get("achievements")
    #steam_community = results.get("forums", "No forum data.")



    if how_long_to_beat and len(how_long_to_beat) > 0:
        best_match = max(how_long_to_beat, key=lambda x: x.similarity)
        how_long_to_beat_hours = {
            "main_story" : best_match.main_story,
            "main_extra" : best_match.main_extra,
            "completionist" : best_match.completionist
        }
        print(how_long_to_beat_hours)
    else:
        how_long_to_beat_hours = {}

    # Handle missing playtime data clearly for AI
    avg_forever_val = game_info.get('average_forever', 0)
    med_forever_val = game_info.get('median_forever', 0)

    playtime_avg_str = f"{round(avg_forever_val / 60, 1)} h" if avg_forever_val > 0 else "No Data"
    median_forever_str = f"{round(med_forever_val / 60, 1)} h" if med_forever_val > 0 else "No Data"

    all_tags = game_info.get('tags', {})
    # Sort by votes (high to low) and take the top 5
    if not all_tags is None and len(all_tags) > 0:
        top_tags = sorted(all_tags, key=all_tags.get, reverse=True)[:max_tags]
    else:
        top_tags = get_store_data(appid, max_tags)["tags"] # fallback to steam scraping to get tags

    approval = 0

    #print(app_details)

    positive = summary.get('total_positive')
    negative = summary.get('total_negative')
    # average_forever = round(game_info.get('average_forever') / 60, 1) # Moved up
    # median_forever = round(game_info.get('median_forever')/ 60, 1) # Moved up
    ccu = str(game_info.get('ccu')) if game_info.get('ccu') != 0 else "N/A" # For ai values of 0, implies missing.
    short_description = app_details.get('short_description', 'No description available.')

    def fmt_price(p):
        try:
            if p is None: return "N/A"
            val = int(p)
            if val == 0: return "N/A"
            return f"{val / 100:.2f}"
        except:
            return str(p)

    # Default price values
    price_data = {}
    final_formatted = fmt_price(game_info.get('price', "N/A"))
    initial_formatted = fmt_price(game_info.get('initialprice', 0))
    discount_percent = game_info.get('discount', 0)

    try:
        disc_val = int(discount_percent)
    except:
        disc_val = 0

    if disc_val > 0:
        price_str = f"{final_formatted} (MSRP: {initial_formatted} | -{discount_percent}% OFF)"
    else:
        price_str = final_formatted

    total_reviews = None
    approval = 0.0
    if positive is not None and negative is not None and (positive + negative) != 0:
        total_reviews = positive + negative
        approval = round((positive / total_reviews) * 100, 1)

    # PRICE PER HOUR CALCULATION
    price_per_hour = "N/A (No Data)"
    price_per_hour_low = "N/A (No Data)"
    user_price_per_hour = "N/A (Not Owned)"

    try:
        # Get Main Story Hours
        main_hours = 0
        if how_long_to_beat and len(how_long_to_beat) > 0:
            main_hours = float(how_long_to_beat[0].main_story)

        if main_hours > 0:
            # Calculate for Official Steam Price
            # game_info['price'] is usually in Cents (e.g. 1999 for $19.99)
            steam_price_cents = game_info.get('price')
            if steam_price_cents is not None:
                steam_price = float(steam_price_cents) / 100.0
                pph = steam_price / main_hours
                price_per_hour = f"${pph:.2f}/h"

            # Calculate for Lowest Found Price (CheapShark)
            if best_deal and isinstance(best_deal, dict) and 'price' in best_deal:
                # best_deal['price'] is usually a string "14.99"
                deal_price = float(best_deal['price'])
                pph_low = deal_price / main_hours
                price_per_hour_low = f"${pph_low:.2f}/h"
        else:
            # Explicitly state why
            price_per_hour = "N/A (No HLTB Data)"
            price_per_hour_low = "N/A (No HLTB Data)"

        # User Cost Per Hour (Your Cost / Your Playtime)
        # Use Current Store Price as proxy for "Your Cost" since we don't have purchase history
        game_in_vault = vault.get_game_by_appid(appid)
        if game_in_vault:
             user_playtime_hrs = game_in_vault.get('playtime_forever', 0) / 60.0
             if user_playtime_hrs > 0.5: # Minimum 30 mins to avoid division by near-zero or massive numbers
                 current_price_cents = game_info.get('price', 0)
                 # Treat '0' as Free
                 if current_price_cents is not None:
                     current_price = float(current_price_cents) / 100.0
                     user_pph = current_price / user_playtime_hrs
                     user_price_per_hour = f"${user_pph:.2f}/h"
             else:
                 user_price_per_hour = "N/A (Low Playtime)"

    except Exception as e:
        print(f"Error calculating PPH: {e}")

    payload = {
        "title": game_info.get('name') or app_details.get('name') or game_name,
        "owned": is_owned,
        "description": short_description,
        "market_analysis": {
            "price_per_hour": price_per_hour,
            "price_per_hour_low": price_per_hour_low,
            "user_price_per_hour": user_price_per_hour,
            "official_current": price_str,
            "lowest_recorded": f"${best_deal.get('price')} ({best_deal.get('store')})" if isinstance(best_deal, dict) and 'price' in best_deal else "N/A"
        },
        "price": price_str,
        "discount": discount,
        "best_deal": best_deal,
        "developer": game_info.get('developer') or ", ".join(app_details.get('developers', [])) or "N/A",
        "publisher": game_info.get('publisher') or ", ".join(app_details.get('publishers', [])) or "N/A",
        "genre": game_info.get('genre') or ", ".join(g.get('description', '') for g in app_details.get('genres', [])) or "N/A",
        "total_positive": positive,
        "total_negative": negative,
        "total_reviews": total_reviews,
        "user_score": f"{approval}% Positive" if total_reviews else "N/A",  # Calculated approval
        "playtime_avg": playtime_avg_str,  # Tells AI if it's replayable
        "median_forever": median_forever_str,
        "how_long_to_beat_hours" : how_long_to_beat_hours, # Various values taken from how long to beat
        "ccu" : str(ccu) if ccu != 0 else "N/A",
        "tags": top_tags,  # The top tags sorted
        #"achievements": achievements,
        #"steam_community": steam_community
    }

    return payload


@safe_tool
def get_batch_game_details(game_names: list[str]) -> list:
    """
    Retrieves details for multiple games simultaneously.
    Use this when the user mentions multiple games to save time.

    Args:
        game_names: A list of strings, e.g. ["Hades", "Bastion", "Pyre"]

    Returns:
        List of game info payloads.
    """
    print(f"BATCH FETCHING {len(game_names)} GAMES")

    results = []

    # We use a ThreadPool to run the heavy get_global_game_info function
    # (which ALREADY uses threads, so we are nesting threads, but it's fine for I/O)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # Map the future to the game name so we know which result is which
        future_to_name = {
            executor.submit(get_global_game_info, name): name
            for name in game_names
        }

        for future in concurrent.futures.as_completed(future_to_name):
            name = future_to_name[future]
            try:
                data = future.result()
                # Ensure the name is present if not already (get_global_game_info usually adds 'title')
                if isinstance(data, dict) and "title" not in data:
                    data["title"] = name
                results.append(data)
            except Exception as e:
                print(f"Batch error for {name}: {e}")
                results.append({"title": name, "error": str(e)})

    return results


@safe_tool
def generate_contextual_dna(game_name, limit=10, status=None):
    """
    Hybrid Search: Combines Tag Intersection (Gameplay) + Vector Vibe (Atmosphere),
    with optional backlog `status` filtering (e.g. ['Unplayed']).
    """
    # Get Target Data
    target_payload = get_global_game_info(game_name)
    if not target_payload or "error" in target_payload:
        return {"error": f"Could not find data for {game_name}"}

    target_tags_list = target_payload.get('tags', [])
    target_tags_set = {t.lower() for t in target_tags_list}
    target_norm = text_utils.normalize_title(target_payload.get('name') or game_name)
    req_status = {s.lower() for s in status} if status else None

    # Prepare Vibe Query
    # We repeat the tags to scream at the AI that the GENRE matters
    tags_str = ", ".join(target_tags_list)
    desc = target_payload.get('description', '')
    vibe_query = f"{game_name}. {tags_str}. {tags_str}. {desc}"

    # Get All Games & Vibe Scores
    library = vault.get_all_games()
    library_ids = [g['appid'] for g in library]

    vibe = vibe_engine.VibeEngine.get_instance()
    # Auto-ingest if needed
    if not vibe.cache: vibe.ingest_library()

    # Get all vibe scores in one go
    vibe_map = vibe.get_batch_scores(vibe_query, library_ids)

    scored_games = []

    for game in library:
        if text_utils.normalize_title(game['name']) == target_norm or game['name'].lower() == game_name.lower():
            continue

        game_status = calculate_status(game)
        if req_status and game_status.lower() not in req_status:
            continue

        # SCORE A: TAG MATCH (Gameplay)
        game_tags = {t.strip().lower() for t in (game['tags'] or "").split(',') if t.strip()}
        if not game_tags:
            tag_score = 0
        else:
            # Jaccard Index: Intersection / Union
            intersection = len(target_tags_set.intersection(game_tags))
            union = len(target_tags_set.union(game_tags))
            tag_score = intersection / union if union > 0 else 0

        # SCORE B: VIBE MATCH (Atmosphere)
        vibe_score = vibe_map.get(game['appid'], 0)

        # 70% Mechanics, 30% Vibes
        final_score = (tag_score * 0.7) + (vibe_score * 0.3)

        # Filter trash matches
        if final_score > 0.25:
            scored_games.append({
                "game": game,
                "status": game_status,
                "score": final_score,
                "tag_overlap": len(target_tags_set.intersection(game_tags))
            })

    # Sort and Format
    scored_games.sort(key=lambda x: x['score'], reverse=True)

    results = []
    for item in scored_games[:limit]:
        g = item['game']
        results.append({
            "name": g['name'],
            "appid": g['appid'],
            "status": item['status'],
            "match_score": f"{int(item['score'] * 100)}%",
            "hltb_main_hours": f"{round(g['hltb_main'] / 60, 1)}h" if g.get('hltb_main') else "N/A",
            "hltb_completionist_hours": f"{round(g['hltb_completionist'] / 60, 1)}h" if g.get('hltb_completionist') else "N/A",
            "hours": f"{round(g.get('playtime_forever', 0) / 60, 1)}h",
            "tags": g.get('tags', '').split(',')[:5]
        })

    return results


def get_current_os_for_steam():
    """
    Detects the local operating system and maps it to the
    Steam API's expected 'os' parameter format.
    """
    sys_name = platform.system().lower()

    if sys_name == "linux":
        # This catches standard Linux desktop and SteamOS (Steam Deck)
        return "linux"
    elif sys_name == "darwin":
        # Python registers macOS as 'darwin'
        return "mac"
    elif sys_name == "windows":
        return "windows"
    else:
        # Fallback for unsupported/other OS types
        return "all"

@safe_tool
def get_reviews(appid, params=None):
    """
    Gets the reviews for a given appid from the Steam WebAPI.
    Uses the modern IUserReviewsService endpoint since the old store endpoint was deprecated.

    Args:
        appid: The id of the app to get the reviews for.
        params: The parameters to be sent with the request.

    Returns:
        A dict containing the reviews and query_summary.
    """
    if params is None:
        params = {}

    url = 'https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/'
    clean_params = params.copy()
    clean_params['appid'] = str(appid)
    if 'cursor' not in clean_params:
        clean_params['cursor'] = '*'
    if 'json' in clean_params:
        clean_params.pop('json')

    try:
        response = requests.get(url, params=clean_params, timeout=10)
        if response.status_code != 200:
            return {"success": 0, "reviews": [], "query_summary": {"num_reviews": 0}}
        data = response.json()
        resp_body = data.get('response', {})
        if resp_body:
            resp_body['success'] = 1
        return resp_body
    except Exception as e:
        print(f"Error fetching reviews for {appid}: {e}")
        return {"success": 0, "reviews": [], "query_summary": {"num_reviews": 0}}

@safe_tool
def get_reviews_summary(appid):
    """
    Gets the review summary for a given appid from the Steam store.

    Args:
        appid: The id of the app to get the review summary for.

    Returns:
        A json object containing the review summary.
    """
    reviews = []
    cursor = '*'
    params = {
        'filter': 'all',
        'review_type': 'all',
        'purchase_type': 'all'
    }

    response = get_reviews(str(appid), params)
    if isinstance(response, dict):
        return response.get('query_summary', {})
    return {}


@safe_tool
def get_n_reviews(appid, n, review_type="all", filter_os=True):
    reviews = []
    # Use a set for O(1) duplicate lookups
    seen_ids = set()
    cursor = '*'

    params = {
        'filter': 'all',
        'language': 'english',  # Usually safer to specify, or Steam defaults to user's IP locale
        'review_type': review_type,
        'purchase_type': 'all',
        'filter_offtopic_activity': 1,
        'num_per_page': 100,

    }

    if filter_os:
        params['os'] = get_current_os_for_steam()

    last_cursor = ""

    while len(reviews) < n:
        params['cursor'] = cursor

        # Call your helper function (assuming it returns the json dict)
        response = get_reviews(str(appid), params)

        # Check for API failure or empty response
        if not response or response.get('success') != 1:
            print("API request failed or finished.")
            break

        query_summary = response.get('query_summary', {})
        if query_summary.get('num_reviews', 0) == 0:
            print("No more reviews found.")
            break

        # Process the new batch
        fetched_reviews = response.get('reviews', [])

        for r in fetched_reviews:
            # Use Steam's unique recommendationid
            rid = r.get('recommendationid')

            # Only add if we haven't seen this ID and we haven't reached the limit
            if rid not in seen_ids:
                reviews.append(r)
                seen_ids.add(rid)

            # optimization: break inner loop immediately if we hit limit
            if len(reviews) >= n:
                break

        cursor = response.get('cursor')

        print(f"{len(reviews)}/{n} reviews collected.")

        # Safety break for infinite loops (Steam API quirk)
        if last_cursor == cursor:
            print("Cursor stuck, stopping.")
            break

        last_cursor = cursor

    print(f"Finished with {len(reviews)} reviews")
    return reviews


@safe_tool
def get_steam_app_info(game_name: str):
    """
    Fetches the app id for a given game name, using fuzzy logic to find the
    best match among the search results.
    """
    print(f"Hunting appid for '{game_name}'...")

    steam = Steam(settings.STEAM_API_KEY)

    # Strip trademark symbols & punctuation noise for Steam's suggest endpoint.
    search_term = text_utils.normalize_title(game_name, convert_roman=False) or game_name.strip()

    # Fetch list of candidates (Steam usually returns 5-20 results)
    results = steam.apps.search_games(search_term)

    if 'apps' not in results or not results['apps']:
        print(" -> Not found in the Steam void.\n")
        return None

    candidates = results['apps']
    best_match = None
    highest_score = 0.0

    target_norm = text_utils.normalize_title(game_name, convert_roman=True)

    print(f" -> Analyzing {len(candidates)} candidates...")

    for app in candidates:
        title = app['name']
        title_norm = text_utils.normalize_title(title, convert_roman=True)

        # Normalized Exact Match (handles ™/® and Roman numerals like Dark Souls 3 <-> III)
        if title_norm and title_norm == target_norm:
            print(f" -> EXACT MATCH FOUND: {title} ({app['id']})")
            return app

        score = text_utils.score_title_match(game_name, title)
        print(f"    - Checking: '{title}' | Score: {score:.2f}")

        if score > highest_score:
            highest_score = score
            best_match = app

    # Threshold Check: If the best match is trash, trust Steam's sorting (index 0)
    # 0.6 is a decent cutoff for "vaguely similar"
    if highest_score < 0.4:
        print(f" -> Best match score ({highest_score:.2f}) is bad. Defaulting to Steam's top pick.")
        return candidates[0]

    print(f" -> Winner: {best_match['name']} ({best_match['id']}) with score {highest_score:.2f}\n")
    return best_match

@safe_tool
def get_steam_app_discount(game_name:str):
    steam = Steam(settings.STEAM_API_KEY)

    app = steam.apps.search_games(game_name, fetch_discounts = True)
    if not app or not app.get("apps"):
        return {"error": f"Game '{game_name}' not found on Steam."}
    return app["apps"][0].get('discount')

@safe_tool
def get_steam_app_details(appid: int) -> Any:
    """
    Gets the app info for a given game name from the Steam API.

    Args:
        appid: The steam id of the game to get the app info for.

    Returns:
        A dictionary containing the app metadata.
    """
    try:
        store_url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=US"
        headers, cookies = get_steam_bypass_with_referer(appid)
        response = requests.get(store_url, headers=headers, cookies=cookies, timeout=5)
        if response.status_code == 200:
            resp = response.json()
            if resp and str(appid) in resp and resp[str(appid)].get('success'):
                return resp[str(appid)].get('data')
    except Exception:
        pass

    try:
        steam = Steam(settings.STEAM_API_KEY)
        app = steam.apps.get_app_details(appid)
        return app[str(appid)].get('data')
    except Exception:
        return {}

def _normalize_review_record(raw_review: dict) -> dict:
    """Flatten nested Steam `author` review metrics onto top-level keys without mutating input."""
    r = dict(raw_review)
    author = r.get("author") if isinstance(r.get("author"), dict) else {}
    if "playtime_at_review" not in r:
        r["playtime_at_review"] = author.get("playtime_at_review")
    if "playtime_forever" not in r:
        r["playtime_forever"] = author.get("playtime_forever")
    if "author_num_reviews" not in r:
        r["author_num_reviews"] = author.get("num_reviews")
    if "author_games_owned" not in r and author.get("num_games_owned") is not None:
        r["author_games_owned"] = author.get("num_games_owned")
    return r


def _compute_review_telemetry(appid, sample_size: int = 60) -> dict:
    """
    Sweep the most recent global reviews via `IUserReviewsService` and compute
    neutral composition metrics (purchase type, hours at review, reviewer history, daily cluster).
    """
    resp = get_reviews(
        str(appid),
        {
            "filter": "recent",
            "review_type": "all",
            "purchase_type": "all",
            "language": "all",
            "filter_offtopic_activity": 0,
            "num_per_page": min(max(int(sample_size), 1), 100),
        },
    )
    reviews = resp.get("reviews", []) if isinstance(resp, dict) else []
    n = len(reviews)
    if n == 0:
        return {"sample_size": 0}

    pos_count = 0
    steam_purchase_count = 0
    non_steam_or_free_count = 0
    free_copy_count = 0
    refunded_count = 0
    early_access_count = 0
    playtimes_hours = []
    under_1h_count = 0
    low_history_count = 0
    day_counts: Counter = Counter()

    for rev in reviews:
        if rev.get("voted_up"):
            pos_count += 1
        steam_buy = bool(rev.get("steam_purchase"))
        free_copy = bool(rev.get("received_for_free"))
        if steam_buy:
            steam_purchase_count += 1
        if (not steam_buy) or free_copy:
            non_steam_or_free_count += 1
        if free_copy:
            free_copy_count += 1
        if rev.get("refunded"):
            refunded_count += 1
        if rev.get("written_during_early_access"):
            early_access_count += 1

        author = rev.get("author") if isinstance(rev.get("author"), dict) else {}
        pt_mins = author.get("playtime_at_review")
        if isinstance(pt_mins, (int, float)):
            playtimes_hours.append(pt_mins / 60.0)
            if pt_mins < 60:
                under_1h_count += 1

        num_rev = author.get("num_reviews")
        if isinstance(num_rev, int) and num_rev <= 2:
            low_history_count += 1

        ts = rev.get("timestamp_created")
        if isinstance(ts, (int, float)) and ts > 0:
            day_counts[datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")] += 1

    telemetry = {
        "sample_size": n,
        "sample_positive_pct": round((pos_count / n) * 100.0, 1),
        "steam_purchase_pct": round((steam_purchase_count / n) * 100.0, 1),
        "non_steam_or_free_pct": round((non_steam_or_free_count / n) * 100.0, 1),
        "received_for_free_pct": round((free_copy_count / n) * 100.0, 1),
        "low_playtime_under_1h_pct": round((under_1h_count / len(playtimes_hours)) * 100.0, 1) if playtimes_hours else None,
        "median_playtime_at_review_hours": round(statistics.median(playtimes_hours), 1) if playtimes_hours else None,
        "low_history_accounts_pct": round((low_history_count / n) * 100.0, 1),
        "refunded_pct": round((refunded_count / n) * 100.0, 1),
        "early_access_pct": round((early_access_count / n) * 100.0, 1),
    }
    if n >= 10 and day_counts:
        peak_day, peak_count = day_counts.most_common(1)[0]
        telemetry["peak_day"] = {"date": peak_day, "count": peak_count}
    return telemetry


@safe_tool
def get_steam_reviews(appid, count):
    """
    Gets a hybrid mix of OS-specific and general reviews alongside global summary
    and neutral recent-sample composition telemetry.
    """
    os_count = count // 2
    all_count = count - os_count

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        f_pos_os = executor.submit(get_n_reviews, appid, os_count, "positive", True)
        f_neg_os = executor.submit(get_n_reviews, appid, os_count, "negative", True)
        f_pos_all = executor.submit(get_n_reviews, appid, all_count, "positive", False)
        f_neg_all = executor.submit(get_n_reviews, appid, all_count, "negative", False)
        f_summary = executor.submit(get_reviews_summary, appid)
        f_telemetry = executor.submit(_compute_review_telemetry, appid, 60)

        pos_os = f_pos_os.result() or []
        neg_os = f_neg_os.result() or []
        pos_all = f_pos_all.result() or []
        neg_all = f_neg_all.result() or []
        summary = f_summary.result() or {}
        telemetry = f_telemetry.result() or {"sample_size": 0}

    def merge_and_dedupe(list1, list2):
        merged = {}
        for review in list1 + list2:
            rid = review.get('recommendationid')
            if rid not in merged:
                merged[rid] = _normalize_review_record(review)
        return list(merged.values())

    positive = merge_and_dedupe(pos_os, pos_all)
    negative = merge_and_dedupe(neg_os, neg_all)
    reviews = positive + negative

    summary = clean_json_for_ai(
        summary,
        ['review_score', 'review_score_desc', 'total_negative', 'total_positive', 'total_reviews'],
    )

    return {
        'reviews': reviews,
        'summary': summary,
        'telemetry': telemetry,
        'fetch_positive': len(positive),
        'fetch_negative': len(negative),
    }

@safe_tool
def get_steamspy_game_info(appid):
    """
    Gets the game info for a given appid from the SteamSpy API.

    Args:
        appid: The id of the app to get the game info for.

    Returns:
        A json object containing the game info.
    """
    data_request = dict()
    data_request['request'] = 'appdetails'
    data_request['appid'] = appid
    return steamspypi.download(data_request)

def _summarize_reviews_with_llm(game_name: str, summary: dict, reviews: list) -> tuple:
    """Condense sampled Steam reviews into a tight consensus digest using the configured summarizer model."""
    if not reviews:
        return None, None, None
    if not settings.OPENAI_API_KEY or not get_summarizer_model():
        return None, None, "LLM API key or model not configured."

    bullets = []
    for idx, r in enumerate(reviews[:40], 1):
        verdict = "POS" if r.get("voted_up") else "NEG"
        src = "Free" if r.get("received_for_free") else ("Steam" if r.get("steam_purchase") else "Key/Other")
        hrs = r.get("playtime_at_review", "N/A")
        acct_n = r.get("author_num_reviews", "?")
        ea = " EA" if r.get("written_during_early_access") else ""
        ref = " Refunded" if r.get("refunded") else ""
        snippet = str(r.get("review", "")).replace("\r\n", " ").replace("\n", " ").strip()[:360]
        bullets.append(f"{idx}. [{verdict} | {src} | {hrs} | {acct_n} revs{ea}{ref}] {snippet}")

    pos = summary.get("total_positive", 0)
    neg = summary.get("total_negative", 0)
    tot = summary.get("total_reviews", pos + neg)
    system_prompt = (
        f"You are summarizing Steam user reviews for '{game_name}' ({pos} pos / {neg} neg, {tot} total). "
        "Synthesize ONLY facts present in the supplied reviews into 3 concise bullet sections without fluff:\n"
        "- Praise: ...\n- Complaints: ...\n- Technical/Notes: ...\n"
        "Preserve minority criticisms cleanly even on well-reviewed games, and never invent features not stated."
    )
    try:
        digest, in_tok, out_tok = aiCall(
            "\n".join(bullets),
            system_prompt,
            return_tokens=True,
            model=get_summarizer_model(),
        )
        return digest.strip(), {"in": in_tok, "out": out_tok}, None
    except Exception as e:
        return None, None, str(e)


@safe_tool
def get_reviews_byname(game_name, count=10, summarize=False):
    """
    Gets the reviews and neutral recent-sample telemetry for a given game name.
    When `summarize=True`, fetches a broader batch and condenses it via sub-LLM digest.
    """
    review_schema = {
        "transformations": {
            "timestamp_created": "date",
            "playtime_forever": "minutes_to_hours",
            "playtime_at_review": "minutes_to_hours",
            "votes_up": "int",
        },
        "keep_keys": [
            "review",
            "playtime_at_review",
            "playtime_forever",
            "author_num_reviews",
            "author_games_owned",
            "voted_up",
            "steam_purchase",
            "received_for_free",
            "written_during_early_access",
            "primarily_steam_deck",
            "refunded",
            "votes_funny",
            "votes_up",
            "timestamp_created",
        ],
    }

    app = get_steam_app_info(game_name)
    if not app:
        return {"error": f"Game '{game_name}' not found on Steam."}

    appid = app['id'][0]
    fetch_count = max(int(count), 20) if summarize else int(count)
    steam_reviews = get_steam_reviews(appid, fetch_count)
    if isinstance(steam_reviews, dict) and "error" in steam_reviews:
        return steam_reviews

    cleaned_reviews = clean_json_for_ai(
        steam_reviews['reviews'],
        transformations=review_schema["transformations"],
        keep_keys=review_schema["keep_keys"],
    )

    if summarize:
        digest, tokens, err = _summarize_reviews_with_llm(
            app.get("name", game_name),
            steam_reviews.get("summary", {}),
            cleaned_reviews,
        )
        if digest:
            steam_reviews["summary_digest"] = digest
        if tokens:
            steam_reviews["_tokens"] = tokens
        if err:
            steam_reviews["digest_error"] = err
        # Keep only up to 4 anchor quotes alongside a digest (2 pos + 2 neg)
        pos_quotes = [r for r in cleaned_reviews if r.get("voted_up")][:2]
        neg_quotes = [r for r in cleaned_reviews if not r.get("voted_up")][:2]
        steam_reviews["reviews"] = pos_quotes + neg_quotes
    else:
        steam_reviews["reviews"] = cleaned_reviews

    return steam_reviews


@safe_tool
def evaluate_game(game_name: str, deep: bool = False):
    """
    Composite game investigator combining library ownership/status, Steam & CheapShark
    store/pricing/HLTB details, global + recent review telemetry, and optional (`deep=True`)
    sub-LLM review digest + community consensus in a single round-trip.
    """
    app = get_steam_app_info(game_name)
    if not app:
        return {"error": f"Game '{game_name}' not found on Steam."}

    appid = int(app["id"][0])
    canonical_name = app.get("name") or game_name

    vault_entry = vault.get_game_by_appid(appid)
    vault_status = None
    if vault_entry:
        vault_status = {
            "appid": appid,
            "name": vault_entry.get("name", canonical_name),
            "status": calculate_status(vault_entry),
            "hours": round((vault_entry.get("playtime_forever") or 0) / 60.0, 1),
            "last_played": vault.format_time_ago(vault_entry.get("rtime_last_played", 0)),
        }

    # Lazy import avoids circular top-level dependency with community_sentiment
    import core.community_sentiment as community_sentiment

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        f_details = executor.submit(get_global_game_info, canonical_name)
        f_reviews = executor.submit(get_reviews_byname, canonical_name, 8, deep)
        f_sentiment = executor.submit(community_sentiment.get_community_sentiment, canonical_name) if deep else None

        details = f_details.result()
        reviews = f_reviews.result()
        sentiment = f_sentiment.result() if f_sentiment else None

    total_in = 0
    total_out = 0
    for block in (reviews, sentiment):
        if isinstance(block, dict) and "_tokens" in block:
            tok = block.pop("_tokens") or {}
            total_in += tok.get("in", 0)
            total_out += tok.get("out", 0)

    payload = {
        "appid": appid,
        "game_name": canonical_name,
        "vault_status": vault_status,
        "details": details,
        "reviews": reviews,
        "community_sentiment": sentiment,
    }
    if total_in > 0 or total_out > 0:
        payload["_tokens"] = {"in": total_in, "out": total_out}

    return payload

@safe_tool
def get_achievement_stats(appid=-1, game_name="", page=None):
    """
    Fetches Achievement stats.
    Default: Returns a "Dashboard" summary (Stats + Top 3 Easiest Locked).
    If 'page' is set (int), returns a list of locked achievements for browsing.
    """
    # Resolve ID
    steam = Steam(settings.STEAM_API_KEY)
    if appid == -1 and game_name:
        app_info = get_steam_app_info(game_name)
        if not app_info: return {"error": f"Game not found: {game_name}"}
        appid = app_info['id'][0]

    steam_id = resolve_steam_id(settings.STEAM_USER)
    if not steam_id: return {"error": "Could not resolve Steam ID."}

    try:
        # Fetch Schema for Descriptions
        schema_url = f"https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/?key={settings.STEAM_API_KEY}&appid={appid}"
        headers, cookies = get_steam_bypass_with_referer(appid)
        schema_http = requests.get(schema_url, headers=headers, cookies=cookies, timeout=5)
        schema_resp = schema_http.json() if schema_http.status_code == 200 else {}

        # Build Map: API Name -> {Display Name, Description}
        ach_details = {}
        available_stats = schema_resp.get('game', {}).get('availableGameStats', {})
        for item in available_stats.get('achievements', []):
            ach_details[item['name']] = {
                "real_name": item.get('displayName', item['name']),
                "desc": item.get('description', "No description provided.")
            }

        # Fetch Global %
        global_url = f"https://api.steampowered.com/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v0002/?gameid={appid}&format=json"
        global_http = requests.get(global_url, headers=headers, cookies=cookies, timeout=5)
        global_resp = global_http.json() if global_http.status_code == 200 else {}
        global_map = {a['name']: a['percent'] for a in
                      global_resp.get('achievementpercentages', {}).get('achievements', [])}

        user_ach_url = f"https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/?appid={appid}&key={settings.STEAM_API_KEY}&steamid={steam_id}"
        user_resp = requests.get(user_ach_url, timeout=5)

        user_data = {}
        try:
            user_data = user_resp.json()
        except ValueError:
            user_data = {}
        ps_error = (user_data.get('playerstats') or {}).get('error', '')

        # Steam returns 403 if the game is unowned, unplayed, or private
        if user_resp.status_code == 403:
            return {
                "error": f"No achievement data found. The user likely does not own '{game_name}' or has 0 hours played."}
        # Steam returns 400 with "Requested app has no stats" when a game has no Steam achievements configured
        elif user_resp.status_code == 400 and "no stats" in ps_error.lower():
            return {
                "game": game_name or str(appid),
                "appid": int(appid),
                "view": "no_achievements",
                "has_achievements": False,
                "message": "This game does not have Steam Achievements.",
            }
        elif user_resp.status_code != 200:
            detail = f" ({ps_error})" if ps_error else ""
            return {"error": f"Steam API returned status code {user_resp.status_code}{detail}."}

        # Final safety check on the JSON structure
        if 'playerstats' not in user_data or not user_data['playerstats'].get('success', False):
            return {"error": ps_error or "Could not parse player stats. Profile might actually be private."}

        user_achievements = user_data['playerstats'].get('achievements', [])

        if not user_achievements:
            return {
                "game": game_name or str(appid),
                "appid": int(appid),
                "view": "no_achievements",
                "has_achievements": False,
                "message": "This game does not have Steam Achievements.",
            }

        # Process Data
        unlocked_list = []
        locked_list = []

        for ach in user_achievements:
            api_name = ach['apiname']
            details = ach_details.get(api_name, {"real_name": api_name, "desc": ""})

            entry = {
                "name": details['real_name'],
                "description": details['desc'],
                "rarity": global_map.get(api_name, 0.0),
                "unlocked": ach.get('achieved', 0),
                "unlock_time": ach.get('unlocktime', 0)  # Keep raw timestamp for sorting
            }

            if entry['unlocked']:
                # Convert timestamp for readability only on unlocked
                entry['date'] = datetime.fromtimestamp(entry['unlock_time']).strftime('%Y-%m-%d %H:%M')
                unlocked_list.append(entry)
            else:
                locked_list.append(entry)

        # Calc Stats
        total = len(user_achievements)
        count = len(unlocked_list)
        percent_complete = int((count / total) * 100) if total > 0 else 0

        # Mode Selection: Pagination vs Dashboard

        # PAGINATION MODE
        if page is not None:
            # Sort locked by most common (easiest) first
            locked_list.sort(key=lambda x: x['rarity'], reverse=True)

            items_per_page = 10
            start = page * items_per_page
            end = start + items_per_page

            return {
                "game": game_name,
                "view": "locked_list",
                "page": page,
                "total_locked": len(locked_list),
                "achievements": locked_list[start:end]
            }

        # DASHBOARD MODE (Default)
        # Sort unlocked by time (newest first)
        unlocked_list.sort(key=lambda x: x['unlock_time'], reverse=True)
        # Sort locked by rarity (highest % first = easiest)
        locked_list.sort(key=lambda x: x['rarity'], reverse=True)

        ach_schema = {
            # TRANSFORMATIONS: 'field_name': 'rule'
            "transformations": {
                "unlocked": "bool_text"
            },
            # ALLOWLIST: Only keep these fields
            "keep_keys": [
                'date',
                'description',
                'name',
                'rarity',
                'unlocked'
            ]
        }

        unlocked_list = clean_json_for_ai(unlocked_list,
                                                     transformations=ach_schema["transformations"],
                                                     keep_keys=ach_schema["keep_keys"])

        locked_list =  clean_json_for_ai(locked_list,
                                                     transformations=ach_schema["transformations"],
                                                     keep_keys=ach_schema["keep_keys"])

        return {
            "game": game_name,
            "stats": {
                "completion_percent": percent_complete,
                "total": total,
                "unlocked_count": count
            },
            # Give the agent context on what they just finished
            "latest_unlocks": unlocked_list[:10],
            # Give the agent 'ammo' to suggest the next step
            "recommended_next": locked_list[:3]
        }

    except Exception as e:
        return {"error": str(e)}

@safe_tool
def get_user_wishlist(sort_by='recent', page=0, page_size=10):
    """
    Fetches the user's Steam Wishlist using a Hybrid API + Parallel Scrape method.
    Resolves the 'Redirect/Login' issue by using the official API for the list,
    and then fetching details only for the requested items.
    """

    global steam_id

    if not steam_id:
        steam_id = resolve_steam_id(settings.STEAM_USER)

    if not steam_id:
        return {"error": "Could not resolve Steam ID."}

    print(f"FETCHING WISHLIST FOR ID: {steam_id} (Page {page})")

    try:
        steam = Steam(settings.STEAM_API_KEY)

        # Get Raw List of AppIDs (Fast & Reliable)
        # Returns: [{'appid': 123, 'priority': 1, 'date_added': 12345}, ...]
        # This call bypasses the 'wishlistdata' URL redirect issue.
        raw_wishlist = steam.users.get_profile_wishlist(steam_id)

        # print(raw_wishlist)

        if not raw_wishlist:
            return {
                "error": "Wishlist is empty, or Steam Privacy Settings for 'Game details' are set to Private/Friends Only. Tell the user they must set 'Game details' to Public to use this feature."}

        # SORTING (Metadata Pre-Sort)
        if sort_by in ['cheapest', 'discount']:
            # If the wishlist is messy, 'recent' is the best baseline.
            # We want to find deals on games you actually remember adding first.
            raw_wishlist.sort(key=lambda x: x.get('date_added', 0), reverse=True)
        elif sort_by == 'priority':
            raw_wishlist.sort(key=lambda x: x.get('priority', 999))
        elif sort_by == 'recent':
            raw_wishlist.sort(key=lambda x: x.get('date_added', 0), reverse=True)

        # PAGINATION & SLICING
        is_price_sort = sort_by in ['cheapest', 'discount']

        # If looking for deals, we fetch a large 'chunk' (50) based on the current page.
        # This allows the Agent to say "Let me check the NEXT 50 games for deals..."
        chunk_size = 50 if is_price_sort else page_size

        start_idx = page * chunk_size
        end_idx = start_idx + chunk_size
        items_to_process = raw_wishlist[start_idx:end_idx]

        if not items_to_process:
            return []  # End of list reached

        # Define Worker for Parallel Fetching
        def fetch_details_worker(item):
            appid = item['appid']
            # Default structure
            res = {
                "name": f"AppID {appid}",
                "priority": item.get('priority', 999),
                "price": "N/A",
                "discount": 0,
                "appid": appid,
                "date_added": datetime.fromtimestamp(item.get('date_added', 0)).strftime("%Y-%m-%d %H:%M"),
            }
            # pprint(item)
            try:
                # Fetch details from Store API
                store_url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=US"

                headers, cookies = get_steam_bypass_with_referer(appid)
                response = requests.get(store_url, headers=headers, cookies=cookies, timeout=5)

                # Check for the 429 Rate Limit Bomb
                if response.status_code == 429:
                    res['error'] = "RATE_LIMITED"
                    res['price'] = "Rate Limited"
                    return res

                resp = response.json()

                if resp and str(appid) in resp and resp[str(appid)]['success']:
                    data = resp[str(appid)]['data']
                    res['name'] = data.get('name', res['name'])

                    if data.get('is_free'):
                        res['price'] = "Free"
                    else:
                        price_data = data.get('price_overview')
                        if price_data:
                            res['price'] = price_data.get('final_formatted', 'N/A')
                            res['discount'] = price_data.get('discount_percent', 0)

            except Exception as e:
                res['error'] = str(e)
                res['price'] = "Error"

            return res

        # Execute Parallel Fetch
        enriched_results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            enriched_results = list(executor.map(fetch_details_worker, items_to_process))

        # POST-FETCH SORTING & TRIMMING
        if is_price_sort:
            def get_price_float(item):
                p = item.get('price', 'N/A')
                if p == 'Free': return 0.0
                if p == 'N/A' or p == 'Error': return 9999.0
                # Remove currency symbols safely
                clean = ''.join(c for c in str(p) if c.isdigit() or c == '.')
                try:
                    return float(clean)
                except ValueError:
                    return 9999.0

            if sort_by == 'cheapest':
                enriched_results.sort(key=get_price_float)
            elif sort_by == 'discount':
                enriched_results.sort(key=lambda x: x['discount'], reverse=True)

            # We fetched 50, sorted them by best deal, now return the top 10 of THIS chunk
            enriched_results = enriched_results[:page_size]

        return enriched_results

    except Exception as e:
        print(f"Wishlist Logic Error: {e}")
        return {"error": f"Error: {e}"}


def process_friends_list(raw_friends):


    raw_friends.sort(key=lambda x: (x['personastate'], x['lastlogoff'], x['friend_since']), reverse=True)

    clean_list = []
    for f in raw_friends:
        # Filter: Skip Private Profiles (We can't scan their games anyway)
        if f.get('communityvisibilitystate', 0) != 3:
            continue

        clean_list.append(f)


    friends_schema = {
        # TRANSFORMATIONS: 'field_name': 'rule'
        "transformations": {
            "lastlogoff": "date",
        },
        # ALLOWLIST: Only keep these fields
        "keep_keys": [
            "steamid",
            "lastlogoff",
            "personaname",
            "status",
            "realname",
        ]
    }

    clean_list = clean_json_for_ai(clean_list,
                                      transformations=friends_schema["transformations"],
                                      keep_keys=friends_schema["keep_keys"])


    return clean_list


@safe_tool
def get_friends_who_own(game_names):
    """
    Checks which of the user's friends own a list of specific games.
    Fetches each friend's library ONLY ONCE and intersects it with the target games.
    """
    if not isinstance(game_names, list):
        game_names = [game_names]

    # Resolve all requested games to AppIDs
    target_games = {}  # Format: {appid: "Game Name"}
    for name in game_names:
        app = get_steam_app_info(name)
        if app:
            target_games[int(app['id'][0])] = app['name']

    if not target_games:
        return {"error": "None of the requested games could be found on Steam."}

    print(f"Scanning friends for {len(target_games)} games: {list(target_games.values())}...")

    # Get Friend List
    steam = Steam(settings.STEAM_API_KEY)
    user_id = resolve_steam_id(settings.STEAM_USER)

    try:
        friends_list = steam.users.get_user_friends_list(user_id)
    except Exception as e:
        return {"error": f"Could not fetch friend list: {e}"}

    if not friends_list or not friends_list["friends"]:
        return {"error": "No friends found (or profile is private)."}

    # Limit scanning to top 50 active friends
    friends_to_scan = process_friends_list(friends_list.get("friends", []))[:50]

    # Define the Worker Function
    def check_friend_library(friend):
        f_id = friend['steamid']
        try:
            # Fetch friend's library exactly ONCE
            games = steam.users.get_owned_games(f_id, include_appinfo=False)

            owned_targets = []
            if 'games' in games:
                for g in games['games']:
                    # Check if the friend's game matches ANY of our targets
                    if g['appid'] in target_games:
                        owned_targets.append({
                            "game": target_games[g['appid']],
                            "playtime": round(g.get('playtime_forever', 0) / 60, 1)
                        })

            # If they own at least one of the target games, return their profile
            if owned_targets:
                # Sort their owned target games by playtime so the agent sees their favorites first
                owned_targets.sort(key=lambda x: x['playtime'], reverse=True)
                friend["matched_games"] = owned_targets
                return friend

        except Exception:
            # Profile likely private
            pass
        return None

    # Execute Parallel Scan
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(check_friend_library, friends_to_scan))

    owners = [r for r in results if r]

    # Sort friends by how many of the target games they own, then by online status
    owners.sort(key=lambda x: (len(x['matched_games']), x.get('status', 0)), reverse=True)

    # Check which of these games the USER owns (for agent context)
    user_ownership = {name: vault.is_game_owned(appid) for appid, name in target_games.items()}

    return {
        "games_checked": list(target_games.values()),
        "user_owns": user_ownership,
        "friend_count": len(friends_list["friends"]),
        "owners_count": len(owners),
        "friends_data": owners
    }


@safe_tool
def compare_library_with_friend(friend_name):
    """
    Finds a friend by name, fetches their library, and compares it to the user's local Vault.
    """
    steam = Steam(settings.STEAM_API_KEY)
    user_id = resolve_steam_id(settings.STEAM_USER)

    # Fetch Friend List
    try:
        friends_list = steam.users.get_user_friends_list(user_id).get("friends", [])
    except Exception as e:
        return {"error": f"Could not fetch friend list: {e}"}

    if not friends_list:
        return {"error": "Your friend list is empty or private."}

    # Fuzzy Match the Friend's Name
    best_match = None
    best_score = 0

    for f in friends_list:
        name = f.get('personaname', '')
        score = fuzz.partial_ratio(friend_name.lower(), name.lower())
        if score > best_score:
            best_score = score
            best_match = f

    if not best_match or best_score < 70:
        return {"error": f"Could not find a friend matching '{friend_name}'. Are they on user list?"}

    target_id = best_match['steamid']
    target_name = best_match['personaname']
    print(f"Matched '{friend_name}' to friend: {target_name} ({target_id})")

    # Fetch Friend's Library
    try:
        friend_games = steam.users.get_owned_games(target_id, include_appinfo=True)
    except Exception:
        return {"error": f"{target_name}'s game library is private."}

    if 'games' not in friend_games:
        return {"error": f"Could not read {target_name}'s games (might be private)."}

    # Fetch Recently Played (Bypasses the missing timestamp for possible privacy filtered)
    recent_appids = {}
    try:
        recent_data = steam.users.get_user_recently_played_games(target_id)
        if 'games' in recent_data:
            # Map AppID to their 2-week playtime
            recent_appids = {g['appid']: g.get('playtime_2weeks', 0) for g in recent_data['games']}
    except Exception as e:
        print(f"Could not fetch recent games for {target_name}: {e}")

    friend_library = friend_games['games']



    ## Debug test code,
    # try:
    #     recent_data = steam.users.get_user_recently_played_games(target_id)
    #     if 'games' in recent_data:
    #         recent_appids = {g['appid']: g.get('playtime_2weeks', 0) for g in recent_data['games']}
    #
    #         print(f"DEBUG: {target_name} recently played these AppIDs: {list(recent_appids.keys())}")
    # except Exception as e:
    #     print(f"Could not fetch recent games for {target_name}: {e}")

    # Get Friend's RECENT Favorites
    # Sort primarily by Last Played, then by Playtime

    friend_library.sort(key=lambda x: (x.get('rtime_last_played', 0), x.get('playtime_forever', 0)), reverse=True)

    # pprint(friend_library)

    friend_top_played = []
    for g in friend_library:
        # Skip unplayed games immediately
        if g.get('playtime_forever', 0) <= 0:
            continue

        last_played_unix = g.get('rtime_last_played', 0)

        friend_top_played.append({
            "name": g.get('name', f"App {g['appid']}"),
            "playtime_hours": g.get('playtime_forever', 0),
            "last_played": last_played_unix
        })

        # Stop once we have 5 valid games
        if len(friend_top_played) >= 5:
            break

    # Cross-Reference with User's Vault
    shared_games = []
    user_vault_games = vault.get_all_games()
    user_appids = {g['appid']: g for g in user_vault_games}

    for g in friend_library:
        appid = g['appid']
        if appid in user_appids:
            local_game = user_appids[appid]

            # Is it a multiplayer game?
            tags = local_game.get('tags', '')
            is_mp = False
            if isinstance(tags, str) and any(t in tags for t in ['Multiplayer', 'Co-op', 'Online Co-Op']):
                is_mp = True
            elif isinstance(tags, list) and any(t in tags for t in ['Multiplayer', 'Co-op', 'Online Co-Op']):
                is_mp = True

            # TIME
            last_played_unix = g.get('rtime_last_played', 0)

            if appid in recent_appids:
                # We definitively know they played it in the last 14 days!
                last_played_str = "Active"
                # Give it a massive artificial timestamp so it sorts to the very top
                sort_weight = datetime.now().timestamp() + recent_appids[appid]
            elif last_played_unix > 0:
                dt = datetime.fromtimestamp(int(last_played_unix))
                last_played_str = dt.strftime("%Y-%m-%d")
                sort_weight = last_played_unix
            else:
                last_played_str = "N/A"
                sort_weight = last_played_unix

            shared_games.append({
                "name": local_game['name'],
                "is_multiplayer": is_mp,
                "sort_weight": sort_weight,  # Used exclusively for sorting
                "friend_last_played": last_played_str,
                "friend_playtime": g.get('playtime_forever', 0),
                "user_playtime": local_game.get('playtime_forever', 0) # Secondary sort, edge case when friend activity private
            })

    # Sort prioritizing Multiplayer games FIRST, then by custom Sort Weight, then playtimes
    shared_games.sort(key=lambda x: (x['is_multiplayer'], x['sort_weight'], x['friend_playtime'], x['user_playtime']), reverse=True)

    friends_schema = {
        # TRANSFORMATIONS: 'field_name': 'rule'
        "transformations": {
            "friend_playtime": "minutes_to_hours_or_na",
            "user_playtime": "minutes_to_hours_or_na",
            "playtime_hours": "minutes_to_hours_or_na",
            "last_played": "date",
        },
        # ALLOWLIST: Only keep these fields
        "keep_keys": [
            "name",
            "playtime_hours",
            "last_played",
            "is_multiplayer",
            "friend_last_played",
            "friend_playtime",
            "user_playtime",
            "friend_name",
            "status",
            "friend_recent_favorites",
            "total_shared_games",
            "top_shared_multiplayer",
            "top_shared"
        ]
    }

    result = {
        "friend_name": target_name,
        "status": "online" if best_match.get('personastate', 0) == 1 else "offline",
        "friend_recent_favorites": friend_top_played if friend_top_played else "N/A Privacy?",
        "total_shared_games": len(shared_games),
        "top_shared_multiplayer": [g for g in shared_games if g['is_multiplayer']][:7],
        "top_shared": [g for g in shared_games if not g['is_multiplayer']][:3]
    }

    result = clean_json_for_ai(result,
                                  transformations=friends_schema["transformations"],
                                  keep_keys=friends_schema["keep_keys"])

    return result



@safe_tool
def get_active_friends():
    """
    Fetches the user's friend list and runs a batch GetPlayerSummaries
    via direct HTTP request to see exactly who is online and what they are playing.
    """
    steam = Steam(settings.STEAM_API_KEY)
    user_id = resolve_steam_id(settings.STEAM_USER)

    # Get Friend List (Just the IDs) using the wrapper
    try:
        friends_list = steam.users.get_user_friends_list(user_id).get("friends", [])
    except Exception as e:
        return {"error": f"Could not fetch friend list: {e}"}

    if not friends_list:
        return {"error": "Your friend list is empty or private."}

    # Extract up to 100 SteamIDs (Steam's batch limit for this endpoint)
    friend_ids = [f['steamid'] for f in friends_list[:100]]
    comma_separated_ids = ",".join(friend_ids)

    # Get Player Summaries using direct HTTP request
    url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
    params = {
        "key": settings.STEAM_API_KEY,
        "steamids": comma_separated_ids
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        summaries = data.get('response', {}).get('players', [])
    except Exception as e:
        return {"error": f"Could not fetch player summaries via HTTP: {e}"}

    active_friends = []
    recently_offline = []

    for player in summaries:
        # personastate: 0 = Offline, 1 = Online, 2 = Busy, 3 = Away, 4 = Snooze, 5 = looking to trade, 6 = looking to play
        status_code = player.get('personastate', 0)

        # Sometimes users appear offline but Steam still broadcasts gameextrainfo
        current_game = player.get('gameextrainfo')
        name = player.get('personaname', 'Unknown')

        if status_code > 0 or current_game:
            # Map status code to text
            status_map = {1: "Online", 2: "Busy", 3: "Away", 4: "Snooze", 5: "Looking to Trade", 6: "Looking to Play"}
            status_text = status_map.get(status_code, "Offline")

            active_friends.append({
                "name": player.get('personaname', 'Unknown'),
                "status": status_text,
                "currently_playing": current_game if current_game else "Nothing"
            })
        else:
            # Catch the offline players
            last_logoff = player.get('lastlogoff', 0)
            if last_logoff > 0:

                recently_offline.append({
                    "name": name,
                    "last_seen": last_logoff  # For sorting
                })

    # Sort the offline list to get the most recent ones
    recently_offline.sort(key=lambda x: x['last_seen'], reverse=True)
    # Sort so people actually playing games are at the very top
    active_friends.sort(key=lambda x: (x['currently_playing'] != "Nothing", x['status'] == "Online"),
                        reverse=True)

    max_entries = 10
    max_offline = max_entries - len(active_friends) if max_entries - len(active_friends) > 0 else 0

    result = {
        "total_friends": len(friend_ids),
        "online_count": len(active_friends),
        "active_players": active_friends[:max_entries],
        "recently_offline": recently_offline[:max_offline]
    }

    friends_schema = {
        # TRANSFORMATIONS: 'field_name': 'rule'
        "transformations": {
            "last_seen": "datetime",
        },
        # ALLOWLIST: Only keep these fields
        "keep_keys": [
            "total_friends",
            "online_count",
            "active_players",
            "recently_offline",
            "name",
            "last_seen",
            "status",
            "currently_playing",
        ]
    }

    result = clean_json_for_ai(result,
                                  transformations=friends_schema["transformations"],
                                  keep_keys=friends_schema["keep_keys"])

    return result

@safe_tool
def get_steam_store_trends(category="specials"):
    """
    Fetches the current front-page trends directly from the Steam Store.
    Valid categories: 'specials' (current sales/deals), 'top_sellers', 'new_releases', 'coming_soon'.
    Use this to tell the user about major seasonal sales, what's popular, or new drops.
    """
    url = "https://store.steampowered.com/api/featuredcategories/?cc=US"
    valid_categories = ['specials', 'top_sellers', 'new_releases', 'coming_soon']

    # Auto-correct if the LLM hallucinates a category
    if category not in valid_categories:
        category = 'specials'

    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()

        items_raw = data.get(category, {}).get('items', [])

        if not items_raw:
            return {"error": f"No data found for category: {category}"}

        results = []
        # Limit to 25 to keep the LLM context window clean and focused
        for item in items_raw[:25]:
            original_price = (item.get('original_price') or 0) / 100
            final_price = (item.get('final_price') or 0) / 100
            discount = item.get('discount_percent') or 0

            if final_price == 0 and category == 'coming_soon':
                price_str = "TBA"
            else:
                price_str = f"${final_price:.2f}" if final_price > 0 else "Free"

            appid = item.get('id', '')
            is_owned = False
            if str(appid).isdigit():
                is_owned = vault.is_game_owned(int(appid))

            results.append({
                "appid": appid,
                "name": item.get('name', 'Unknown'),
                "discount": f"{discount}% OFF" if discount > 0 else "None",
                "price": price_str,
                "original": f"${original_price:.2f}" if original_price > 0 else "N/A",
                "owned": is_owned
            })

        return {
            "current_view": category,
            "total_items": len(results),
            "games": results
        }

    except Exception as e:
        return {"error": f"Could not fetch Steam store trends: {e}"}


def get_steam_guides_index(appid: int, limit: int = 8) -> List[dict]:
    """Scrape top-rated Steam community guides index (file IDs, titles, preview URLs)."""
    headers, cookies = get_steam_bypass_with_referer(appid)
    url = f"https://steamcommunity.com/app/{appid}/guides/?browsefilter=toprated&p=1"
    try:
        r = requests.get(url, headers=headers, cookies=cookies, timeout=10)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, 'html.parser')
        guides = []
        seen = set()
        for a in soup.find_all('a', href=True):
            href = a['href']
            if 'sharedfiles/filedetails/?id=' in href:
                m = re.search(r'id=(\d+)', href)
                if not m:
                    continue
                gid = m.group(1)
                if gid in seen:
                    continue
                seen.add(gid)
                title_text = a.get_text(separator=' ', strip=True)
                if not title_text:
                    continue
                guides.append({
                    "id": gid,
                    "title": title_text[:140],
                    "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={gid}"
                })
                if len(guides) >= limit:
                    break
        return guides
    except Exception as e:
        print(f"Warning: Failed to fetch Steam guides index for {appid}: {e}")
        return []


def get_steam_guide_details(guide_ids: List[str]) -> List[dict]:
    """Fetch official author descriptions and tags for guides via Steam Remote Storage API."""
    if not guide_ids:
        return []
    url = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
    data = {"itemcount": len(guide_ids)}
    for idx, gid in enumerate(guide_ids):
        data[f"publishedfileids[{idx}]"] = str(gid)
    try:
        r = requests.post(url, data=data, timeout=10)
        if r.status_code != 200:
            return []
        items = r.json().get("response", {}).get("publishedfiledetails", [])
        out = []
        for item in items:
            title = item.get("title")
            if not title:
                continue
            desc = item.get("description", "")
            clean_desc = re.sub(r'\[/?(?:b|i|u|h\d|url|code|quote|list|\*)\]', '', desc)
            clean_desc = re.sub(r'\[img\].*?\[/img\]', '', clean_desc)
            clean_desc = re.sub(r'\[url=[^\]]*\](.*?)\[/url\]', r'\1', clean_desc)
            clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()
            out.append({
                "id": str(item.get("publishedfileid")),
                "title": title,
                "desc": clean_desc[:2500],
                "views": item.get("views", 0),
                "subs": item.get("subscriptions", 0),
                "tags": [t.get("tag") for t in item.get("tags", []) if isinstance(t, dict)],
                "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={item.get('publishedfileid')}"
            })
        return out
    except Exception as e:
        print(f"Warning: Failed to fetch Steam guide details: {e}")
        return []


def get_web_wiki_index(game_name: str, limit: int = 5) -> List[dict]:
    """Search for community lore wikis and world setting articles."""
    query = f'"{game_name}" (wiki OR lore OR factions OR "world setting") -site:steampowered.com'
    try:
        results = DDGS().text(query, max_results=limit * 2)
        out = []
        for r in results:
            title = r.get("title", "")
            href = r.get("href", "")
            body = r.get("body", "")
            if not href or any(junk in href.lower() for junk in ["/category:", "/special:", "/file:", "login", "signup"]):
                continue
            if not text_utils.text_mentions_game(game_name, title, body, href):
                continue
            out.append({"title": title, "url": href, "snippet": body})
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        print(f"Warning: Web wiki search error for {game_name}: {e}")
        return []


def get_web_mechanics_index(game_name: str, limit: int = 4) -> List[dict]:
    """Fallback search for gameplay mechanics and guide articles if Steam guides are absent."""
    query = f'"{game_name}" (gameplay OR mechanics OR build OR guide) -site:steampowered.com'
    try:
        results = DDGS().text(query, max_results=limit * 2)
        out = []
        for r in results:
            title = r.get("title", "")
            href = r.get("href", "")
            body = r.get("body", "")
            if not href or any(junk in href.lower() for junk in ["/category:", "/special:", "/file:", "login", "signup"]):
                continue
            if not text_utils.text_mentions_game(game_name, title, body, href):
                continue
            out.append({"title": title, "url": href, "snippet": body})
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        print(f"Warning: Web mechanics search error for {game_name}: {e}")
        return []


def _extract_page_markdown(url: str, max_chars: int = 3500) -> str:
    """Download and extract clean article markdown from a URL using trafilatura."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        extracted = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            include_links=False,
            output_format="markdown",
        )
        if not extracted:
            return ""
        clean = re.sub(r'\n{3,}', '\n\n', extracted).strip()
        return clean[:max_chars]
    except Exception as e:
        print(f"Warning: Failed to extract markdown from {url}: {e}")
        return ""


def _select_wiki_sources_with_llm(
    game_name: str,
    mechanics_candidates: List[dict],
    lore_candidates: List[dict],
) -> Tuple[List[dict], List[dict], int, int]:
    """
    Sub-LLM Selector: Evaluates candidates from the Dual-Lane Index and picks
    the top 1-2 mechanics sources and top 1 lore source, filtering out translation mods and spam.
    """
    in_tok, out_tok = 0, 0
    if not mechanics_candidates and not lore_candidates:
        return [], [], 0, 0

    selector_system = f"""You are a research selector choosing the best source material for a video game wiki and lore dossier on '{game_name}'.
Review the candidate lists below:
1. 'mechanics_candidates': Select up to 2 best sources for gameplay mechanics, beginner loop, character classes, or buildcrafting. (Ignore joke/meme guides, translation mod notes, or video spam).
2. 'lore_candidates': Select up to 1 best source for world lore, factions, narrative setting, or universe premise.

Respond STRICTLY with valid JSON:
{{"selected_mechanics_ids": ["<id or url>", ...], "selected_lore_urls": ["<url>"]}}"""

    candidates_summary = {
        "game": game_name,
        "mechanics_candidates": [
            {"id": c.get("id") or c.get("url"), "title": c.get("title"), "snippet": (c.get("desc") or c.get("snippet", ""))[:160]}
            for c in mechanics_candidates[:8]
        ],
        "lore_candidates": [
            {"url": c.get("url"), "title": c.get("title"), "snippet": c.get("snippet", "")[:160]}
            for c in lore_candidates[:5]
        ]
    }

    selected_mech = []
    selected_lore = []

    try:
        raw_res, in_tok, out_tok = aiCall(
            data=json.dumps(candidates_summary),
            system=selector_system,
            return_tokens=True,
            model=get_summarizer_model(),
        )
        m = re.search(r'\{.*\}', raw_res, re.DOTALL)
        if m:
            parsed = json.loads(m.group(0))
            mech_keys = set(parsed.get("selected_mechanics_ids", []))
            lore_keys = set(parsed.get("selected_lore_urls", []))
            selected_mech = [c for c in mechanics_candidates if (c.get("id") in mech_keys or c.get("url") in mech_keys)][:2]
            selected_lore = [c for c in lore_candidates if c.get("url") in lore_keys][:1]
    except Exception as e:
        print(f"Warning: LLM source selection fallback: {e}")

    # Heuristic fallback if LLM returned empty or failed
    if not selected_mech and mechanics_candidates:
        ranked = sorted(
            mechanics_candidates,
            key=lambda c: any(k in (c.get("title", "") + " " + c.get("desc", "")).lower() for k in ["guide", "build", "basic", "mechanic", "class", "weapon"]),
            reverse=True
        )
        selected_mech = ranked[:2]

    if not selected_lore and lore_candidates:
        ranked = sorted(
            lore_candidates,
            key=lambda c: any(k in c.get("url", "").lower() for k in ["wiki", "fandom", "lore"]),
            reverse=True
        )
        selected_lore = ranked[:1]

    return selected_mech, selected_lore, in_tok, out_tok


@safe_tool
def compile_game_wiki(game_name: str) -> dict:
    """
    Compiles a comprehensive, factual Game Wiki & Lore Dossier for any game (including brand new releases)
    by pulling Steam Community Guides, community wikis, HowLongToBeat completion times, and Store specifications
    via a multi-stage selector and sub-LLM synthesis pipeline.
    """
    app_info = get_steam_app_info(game_name)
    if not app_info or 'id' not in app_info or not app_info['id']:
        return {"error": f"Game '{game_name}' not found on Steam."}

    appid = app_info['id'][0]
    canonical_name = app_info.get('name', [game_name])[0] if isinstance(app_info.get('name'), list) else app_info.get('name', game_name)

    total_in = 0
    total_out = 0

    # Stage 1: Parallel Fetch of Store Specs, HLTB, Steam Guides Index, and Web Lore Index
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        f_store = executor.submit(get_steam_app_details, appid)
        f_hltb = executor.submit(get_hltb_data, canonical_name)
        f_guides = executor.submit(get_steam_guides_index, appid, limit=8)
        f_lore = executor.submit(get_web_wiki_index, canonical_name, limit=5)

        store_data = f_store.result() or {}
        raw_hltb = f_hltb.result() or []
        guides_index = f_guides.result() or []
        lore_index = f_lore.result() or []

    hltb_data = {}
    if isinstance(raw_hltb, list) and raw_hltb:
        first = raw_hltb[0]
        if hasattr(first, '__dict__'):
            hltb_data = vars(first)
        elif isinstance(first, dict):
            hltb_data = first
    elif isinstance(raw_hltb, dict):
        hltb_data = raw_hltb

    # If Steam has 0 guides, engage web mechanics fallback
    mechanics_candidates = guides_index
    if not mechanics_candidates:
        mechanics_candidates = get_web_mechanics_index(canonical_name, limit=5)

    # Stage 2: Smart Sub-LLM Selector
    selected_mech, selected_lore, sel_in, sel_out = _select_wiki_sources_with_llm(
        canonical_name, mechanics_candidates, lore_index
    )
    total_in += sel_in
    total_out += sel_out

    # Stage 3: Fetch Content from Selected Sources
    mechanics_content_blocks = []
    sources_consulted = []

    # If selected mechanics sources are Steam guides, fetch details via API
    steam_guide_ids = [c["id"] for c in selected_mech if "id" in c]
    if steam_guide_ids:
        guide_details = get_steam_guide_details(steam_guide_ids)
        for gd in guide_details:
            mechanics_content_blocks.append(
                f"### [Steam Guide]: {gd['title']}\n**Tags:** {', '.join(gd.get('tags', []))}\n{gd['desc']}"
            )
            sources_consulted.append({"title": f"Steam Guide: {gd['title']}", "url": gd['url']})

    # For web mechanics sources (if any selected)
    for wm in selected_mech:
        if "url" in wm and "id" not in wm:
            txt = _extract_page_markdown(wm["url"], max_chars=3000)
            if txt:
                mechanics_content_blocks.append(f"### [Web Guide]: {wm.get('title', 'Guide')}\n{txt}")
                sources_consulted.append({"title": wm.get('title', 'Web Guide'), "url": wm["url"]})

    # For lore sources
    lore_content_blocks = []
    for wl in selected_lore:
        txt = _extract_page_markdown(wl["url"], max_chars=3500)
        if txt:
            lore_content_blocks.append(f"### [Wiki / Lore]: {wl.get('title', 'Lore')}\n{txt}")
            sources_consulted.append({"title": wl.get('title', 'Lore Wiki'), "url": wl["url"]})

    # Stage 4: Synthesizer Assembly
    store_meta = {
        "title": canonical_name,
        "appid": appid,
        "developer": ", ".join(store_data.get("developers", [])) if isinstance(store_data.get("developers"), list) else store_data.get("developers", "Unknown"),
        "publisher": ", ".join(store_data.get("publishers", [])) if isinstance(store_data.get("publishers"), list) else store_data.get("publishers", "Unknown"),
        "release_date": (store_data.get("release_date") or {}).get("date", "Unknown") if isinstance(store_data.get("release_date"), dict) else "Unknown",
        "genres": [g.get("description") for g in store_data.get("genres", []) if isinstance(g, dict)],
        "short_description": store_data.get("short_description", ""),
        "detailed_description": re.sub(r'<[^>]+>', ' ', (store_data.get("about_the_game") or store_data.get("detailed_description", ""))[:1800]),
    }

    combined_input = f"""
GAME INTEL:
- Title: {store_meta['title']} (AppID: {store_meta['appid']})
- Developer: {store_meta['developer']} | Publisher: {store_meta['publisher']}
- Release Date: {store_meta['release_date']}
- Genres: {', '.join(store_meta['genres'])}
- HowLongToBeat: Main Story {hltb_data.get('main_story', 'N/A')}h | Main+Extra {hltb_data.get('main_extra', 'N/A')}h | Completionist {hltb_data.get('completionist', 'N/A')}h
- Official Overview: {store_meta['short_description']}
- Official Feature Details: {store_meta['detailed_description'][:1200]}

COMMUNITY MECHANICS & BUILDS:
{chr(10).join(mechanics_content_blocks) if mechanics_content_blocks else "No community build guides available. Rely on official features."}

WORLD LORE & FACTIONS:
{chr(10).join(lore_content_blocks) if lore_content_blocks else "No extended lore wiki pages found. Rely on official premise."}
"""

    synth_system = f"""You are an elite video game intelligence researcher compiling a Game Wiki & Lore Dossier for an AI agent knowledge base.
Synthesize the provided official specs, HowLongToBeat estimates, community guides, and lore text for '{canonical_name}' into a dense, structured Markdown document.

Required Document Structure:
# {canonical_name} — Game Wiki & Lore Dossier

## 1. 📋 Overview & Meta
Table with: Title, Steam AppID, Developer, Publisher, Release Date, Status (Early Access / 1.0), Genres, HLTB Estimates (Main, Extra, Completionist).
Followed by a concise 1-2 sentence core premise summary.

## 2. 🌍 World, Setting & Narrative Premise
World setting, narrative hook, atmosphere, factions/lore background.

## 3. ⚔️ Core Gameplay Loop & Combat Mechanics
Perspective, run flow, progression loop, win/loss conditions, resource/economy rules.

## 4. 🧙 Classes, Builds & Synergies
Playable characters/classes, stat scaling, build archetypes, weapon/item synergies documented by player guides.

## 5. 💡 Pro Tips & Early-Game Strategy
Tactical advice, common beginner mistakes, shop/stat priorities from community guides.

Tone: Dense, objective, factual. Eliminate PR marketing adjectives, hype, and conversational filler."""

    try:
        dossier_text, syn_in, syn_out = aiCall(
            data=combined_input,
            system=synth_system,
            return_tokens=True,
            model=get_summarizer_model(),
        )
        total_in += syn_in
        total_out += syn_out
    except Exception as e:
        dossier_text = f"### 📖 {canonical_name} Dossier\nFailed to synthesize dossier: {e}\n\n**Official Premise:**\n{store_meta['short_description']}"

    return {
        "game": canonical_name,
        "appid": appid,
        "dossier": dossier_text,
        "hltb": hltb_data,
        "sources": sources_consulted,
        "_tokens": {"in": total_in, "out": total_out}
    }


if __name__ == "__main__":
    pprint(get_achievement_stats(game_name="KILL KNIGHT"))
    #pprint(get_friends_who_own(game_names=["Helldivers 2", "Peak"]))
    #pprint(get_reviews_byname(game_name="Marathon"))
    #pprint(compare_library_with_friend("Ash"))
    #pprint(get_active_friends())
    #pprint(get_user_wishlist(sort_by='discount', page=0, page_size=10))
    #pprint(get_steam_store_trends("new_releases"))
    #pprint(search_steam_store("",sort_by="recent"))
    pass

