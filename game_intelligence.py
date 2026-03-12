
import difflib
import platform
import re
import urllib
import urllib.parse
from pprint import pprint
from time import sleep
from typing import Any
from urllib.parse import unquote
import concurrent
import requests
import steamspypi
from bs4 import BeautifulSoup
from thefuzz import fuzz
import vault
import vibe_engine
from ai_tools import clean_json_for_ai
from vault import calculate_status
import concurrent.futures
from datetime import datetime
from steam_web_api import Steam
import settings
from safe_tool import safe_tool
from web_tools import get_hltb_data, get_store_data, get_steam_bypass, get_steam_bypass_with_referer

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
    # This hits: http://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/
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

@safe_tool
def search_steam_store(term, limit=10):
    """
    Scrapes the Steam Search page for games matching the term.
    Returns: List of dicts {name, price, reviews, link}
    """
    # URL Encode the search term
    encoded_term = urllib.parse.quote(term)
    url = f"https://store.steampowered.com/search/?term={encoded_term}&category1=998"  # 998 = Games only (no DLC)

    headers, cookies = get_steam_bypass()

    response = requests.get(url, headers=headers, cookies=cookies, timeout=10)
    soup = BeautifulSoup(response.text, 'html.parser')

    results = []
    rows = soup.select('#search_resultsRows > a')

    for row in rows[:limit]:
        title = row.select_one('.title').text.strip()

        # Extract AppID from URL
        href = row['href']
        appid_match = re.search(r'/app/(\d+)', href)
        appid = appid_match.group(1) if appid_match else "N/A"

        # Extract Price (Handle sales and free games)
        price_div = row.select_one('.search_price')
        price = "N/A"
        if price_div:
            # If discounted, text might be "$19.99$9.99". We want the last part.
            raw_price = price_div.text.strip().split('$')
            price = f"${raw_price[-1]}" if len(raw_price) > 1 else price_div.text.strip()
            if "Free" in price: price = "Free"

        # Extract Reviews (e.g., "Very Positive")
        review_span = row.select_one('.search_review_summary')
        reviews = "Unknown"
        if review_span:
            # The data-tooltip-html attribute often has the detailed score
            reviews = review_span.get('data-tooltip-html', '').split('<br>')[0]

        # Check ownership (Safe cast)
        is_owned = False
        if appid and appid.isdigit():
            is_owned = vault.is_game_owned(int(appid))

        results.append({
            "appid": appid,
            "name": title,
            "price": price,
            "reviews": reviews,
            "link": href,
            "owned": is_owned
        })

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

    # Find all the "capsules" (the clickable game images)
    # We limit to the first 5 for this example, remove [:5] to get them all
    items = container.find_all('a', class_='similar_grid_capsule')[:9]

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
                response = requests.get(url, params=params)
                if response.status_code == 429:
                    wait_time = backoff_factor * (2 ** i)
                    print(f"Rate limited (429). Retrying in {wait_time}s...")
                    sleep(wait_time)
                    continue
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
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

    if positive is not None and negative is not None and positive + negative != 0:
        approval = round(positive / (positive + negative), 2)

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
        "title": game_info['name'],
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
        "developer": game_info['developer'],
        "publisher": game_info['publisher'],
        "genre": game_info['genre'],
        "total_positive": positive,
        "total_negative": negative,
        "user_score": f"{approval * 100}% Positive",  # Calculated approval
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
def generate_contextual_dna(game_name, limit=10):
    """
    Hybrid Search: Combines Tag Intersection (Gameplay) + Vector Vibe (Atmosphere).
    """
    # Get Target Data
    target_payload = get_global_game_info(game_name)
    if not target_payload or "error" in target_payload:
        return {"error": f"Could not find data for {game_name}"}

    target_tags_list = target_payload.get('tags', [])
    target_tags_set = {t.lower() for t in target_tags_list}

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
        if game['name'].lower() == game_name.lower(): continue

        # SCORE A: TAG MATCH (Gameplay)
        game_tags = {t.strip().lower() for t in (game['tags'] or "").split(',')}
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
def get_reviews(appid, params={'json': 1}):
    """
    Gets the reviews for a given appid from the Steam store.

    Args:
        appid: The id of the app to get the reviews for.
        params: The parameters to be sent with the request.

    Returns:
        A json object containing the reviews.
    """
    url = 'https://store.steampowered.com/appreviews/'
    headers, cookies = get_steam_bypass_with_referer(appid)
    response = requests.get(url=url + str(appid), params=params, headers=headers, cookies=cookies)

    # print(response.url)
    return response.json()

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
        'json': 1,
        'filter': 'all',
        #'language': 'english',
        #'day_range': 9223372036854775807,
        'review_type': 'all',
        'purchase_type': 'all'
    }

    response = get_reviews(str(appid), params)

    return response['query_summary']


@safe_tool
def get_n_reviews(appid, n, review_type="all", filter_os=True):
    reviews = []
    # Use a set for O(1) duplicate lookups
    seen_ids = set()
    cursor = '*'

    params = {
        'json': 1,
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

        if response['query_summary']['num_reviews'] == 0:
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

    # Fetch list of candidates (Steam usually returns 5-20 results)
    results = steam.apps.search_games(game_name)

    if 'apps' not in results or not results['apps']:
        print(" -> Not found in the Steam void.\n")
        return None

    candidates = results['apps']
    best_match = None
    highest_score = 0.0

    # Clean the input once
    target_clean = game_name.lower().strip()

    print(f" -> Analyzing {len(candidates)} candidates...")

    for app in candidates:
        title = app['name']
        title_clean = title.lower().strip()

        # Exact Match
        if title_clean == target_clean:
            print(f" -> EXACT MATCH FOUND: {title} ({app['id']})")
            return app

        # Close Enough Metric (0.0 to 1.0)
        # SequenceMatcher calculates how many edits it takes to turn A into B
        score = difflib.SequenceMatcher(None, target_clean, title_clean).ratio()

        # Specific fix for "The" ("Witcher 3" vs "The Witcher 3")
        if target_clean in title_clean:
            score += 0.1  # Boost partial contains

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
        A dictionary containing the app id and price.
    """
    steam = Steam(settings.STEAM_API_KEY)

    # arguments: app_id
    app = steam.apps.get_app_details(appid)
    return app[str(appid)].get('data')

@safe_tool
def get_steam_reviews(appid, count):
    """
    Gets a hybrid mix of OS-specific and general reviews for a given appid.
    """
    # Split the requested count in half
    os_count = count // 2
    all_count = count - os_count

    # Fetch OS-specific reviews (Tech perspective)
    pos_os = get_n_reviews(appid, os_count, "positive", filter_os=True)
    neg_os = get_n_reviews(appid, os_count, "negative", filter_os=True)

    # Fetch General reviews (Big picture perspective)
    pos_all = get_n_reviews(appid, all_count, "positive", filter_os=False)
    neg_all = get_n_reviews(appid, all_count, "negative", filter_os=False)

    # Helper function to merge and deduplicate by recommendationid
    def merge_and_dedupe(list1, list2):
        merged = {}
        for review in list1 + list2:
            rid = review.get('recommendationid')
            if rid not in merged:
                merged[rid] = review
        return list(merged.values())

    # Combine the lists
    positive = merge_and_dedupe(pos_os, pos_all)
    negative = merge_and_dedupe(neg_os, neg_all)

    reviews = positive + negative

    count_positive = len(positive)
    count_negative = len(negative)

    summary = get_reviews_summary(appid)
    summary = clean_json_for_ai(summary, ['review_score', 'review_score_desc', 'total_negative', 'total_positive', 'total_reviews'])

    return {
        'reviews': reviews,
        'summary': summary,
        'fetch_positive': count_positive,
        'fetch_negative': count_negative
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

@safe_tool
def get_reviews_byname(game_name, count=10):
    """
    Gets the reviews for a given game name.

    Args:
        game_name: The name of the game to get the reviews for.
        count: The number of positive and negative reviews to get.

    Returns:
        A dictionary containing the reviews, the review summary, and the number of positive and negative reviews.
    """
    # Define the rules for reviews
    review_schema = {
        # TRANSFORMATIONS: 'field_name': 'rule'
        "transformations": {
            "timestamp_created": "date",
            "playtime_forever": "minutes_to_hours",
            "playtime_at_review": "minutes_to_hours",
            "votes_up": "int",  # optional, usually stays int
        },
        # ALLOWLIST: Only keep these fields
        "keep_keys": [
            "review",
            "author",
            "playtime_at_review",
            "voted_up",
            "refunded",
            "votes_funny",
            "votes_up",
            "timestamp_created",
            "playtime_at_review",
            "playtime_forever"
        ]
    }

    app = get_steam_app_info(game_name)

    appid = app['id'][0]


    steam_reviews = get_steam_reviews(appid, count)

    steam_reviews["reviews"] = clean_json_for_ai(steam_reviews['reviews'],
                                      transformations=review_schema["transformations"],
                                      keep_keys=review_schema["keep_keys"])

    return steam_reviews

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
        schema_url = f"http://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/?key={settings.STEAM_API_KEY}&appid={appid}"
        headers, cookies = get_steam_bypass_with_referer(appid)
        schema_resp = requests.get(schema_url, headers=headers, cookies=cookies, timeout=5).json()


        # Build Map: API Name -> {Display Name, Description}
        ach_details = {}
        if 'game' in schema_resp and 'availableGameStats' in schema_resp['game']:
            for item in schema_resp['game']['availableGameStats']['achievements']:
                ach_details[item['name']] = {
                    "real_name": item.get('displayName', item['name']),
                    "desc": item.get('description', "No description provided.")
                }

        # Fetch Global %
        global_url = f"http://api.steampowered.com/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v0002/?gameid={appid}&format=json"
        global_resp = requests.get(global_url, headers=headers, cookies=cookies, timeout=5).json()
        global_map = {a['name']: a['percent'] for a in
                      global_resp.get('achievementpercentages', {}).get('achievements', [])}

        user_ach_url = f"http://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/?appid={appid}&key={settings.STEAM_API_KEY}&steamid={steam_id}"
        user_resp = requests.get(user_ach_url, timeout=5)

        # Steam returns 403 if the game is unowned or unplayed
        if user_resp.status_code == 403:
            return {
                "error": f"No achievement data found. The user likely does not own '{game_name}' or has 0 hours played."}
        elif user_resp.status_code != 200:
            return {"error": f"Steam API returned status code {user_resp.status_code}."}

        user_data = user_resp.json()

        # Final safety check on the JSON structure
        if 'playerstats' not in user_data or not user_data['playerstats'].get('success', False):
            return {"error": "Could not parse player stats. Profile might actually be private."}

        user_achievements = user_data['playerstats'].get('achievements', [])

        if not user_achievements:
            return {"error": "This game does not have Steam Achievements."}

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
                entry['date'] = datetime.fromtimestamp(entry['unlock_time']).strftime('%Y-%m-%d')
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

        return {
            "game": game_name,
            "stats": {
                "completion_percent": percent_complete,
                "total": total,
                "unlocked_count": count
            },
            # Give the agent context on what they just finished
            "latest_unlocks": unlocked_list[:3],
            # Give the agent 'ammo' to suggest the next step
            "recommended_next": locked_list[:5]
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
            return {"error": "Wishlist is empty or private."}

        # Sort (Metadata)
        # Sort by metadata *before* fetching details to save API calls.
        # cheapest/discount sorting is imperfect here because we don't have prices yet.
        # For those, we fetch the top 50 prioritized items and then sort them below.
        if sort_by == 'priority':
            raw_wishlist.sort(key=lambda x: x.get('priority', 999))
        elif sort_by == 'recent':
            raw_wishlist.sort(key=lambda x: x.get('date_added', 0), reverse=True)
        elif sort_by in ['cheapest', 'discount']:
            # optimization: default to priority for the fetch batch
            raw_wishlist.sort(key=lambda x: x.get('priority', 999))

        # Pagination / Slicing
        # If sorting by price, fetch a larger batch (up to 50) to find deals
        items_to_process = []
        is_price_sort = sort_by in ['cheapest', 'discount']

        if is_price_sort:
            # Fetch top 50 to find best deals/prices among them
            items_to_process = raw_wishlist[:50]
        else:
            start_idx = page * page_size
            end_idx = start_idx + page_size
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

            try:
                # Fetch details from Store API
                store_url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=US"
                # cc=US ensures dollar prices. Might one day include localization

                headers, cookies = get_steam_bypass_with_referer(appid)
                resp = requests.get(store_url, headers=headers, cookies=cookies, timeout=5).json()

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
                # print(f"Error fetching {appid}: {e}")
                res['error'] = str(e)
                res['price'] = "Error"

            return res

        # Execute Parallel Fetch
        enriched_results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            enriched_results = list(executor.map(fetch_details_worker, items_to_process))

        # Post-Fetch Sorting (If Price/Discount was requested)
        if is_price_sort:
            def get_price_float(item):
                p = item['price']
                if p == 'Free': return 0.0
                if p == 'N/A': return 9999.0
                # remove currency symbols
                clean = ''.join(c for c in p if c.isdigit() or c == '.')
                try:
                    return float(clean)
                except:
                    return 9999.0

            if sort_by == 'cheapest':
                enriched_results.sort(key=get_price_float)
            elif sort_by == 'discount':
                enriched_results.sort(key=lambda x: x['discount'], reverse=True)

            # Since we fetched 50, we now strictly paginate the result for the UI
            start_idx = page * page_size
            end_idx = start_idx + page_size
            enriched_results = enriched_results[start_idx:end_idx]

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
    url = "http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
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


if __name__ == "__main__":
    #print(get_achievement_stats(-1, "akane"))
    #pprint(get_friends_who_own(game_names=["Helldivers 2", "Peak"]))
    #pprint(get_reviews_byname(game_name="Marathon"))
    #pprint(compare_library_with_friend("Ash"))
    pprint(get_active_friends())

