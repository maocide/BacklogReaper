"""
Steam Store, Catalog, Pricing, Deals, and Market Intelligence.
"""

import concurrent.futures
from datetime import datetime
import difflib
import json
import platform
from pprint import pprint
import re
import time
from time import sleep
from typing import Any, Dict, List, Optional, Set, Tuple
import urllib
import urllib.parse
from urllib.parse import unquote

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests
import requests
from steam_web_api import Steam
import steamspypi
from thefuzz import fuzz

import core.settings as settings
import core.text_utils as text_utils
import core.vault as vault
import core.vibe_engine as vibe_engine
from core.ai_tools import clean_json_for_ai
from core.safe_tool import safe_tool
from core.vault import calculate_status
from core.web_tools import (
    get_hltb_data,
    get_steam_bypass,
    get_steam_bypass_with_referer,
    get_store_data,
)

max_tags = 10
steam_id = None
_wishlist_ids_cache = {"fetched_at": 0.0, "appids": set()}


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
