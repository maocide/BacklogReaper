
import difflib
import json
import re
import urllib
from time import sleep
from typing import Any
from urllib.parse import unquote

import concurrent
import requests
import trafilatura
import steamspypi
from howlongtobeatpy import HowLongToBeat
from bs4 import BeautifulSoup
import vault, ai_tools
from ai_tools import aiCall, clean_json_for_ai
from vault import get_realtime_tags, calculate_status
from basc_py4chan import Board
import ddgs
import concurrent.futures
from datetime import datetime
from steam_web_api import Steam
import config

max_tags = 10
steam_id = None

def resolve_steam_id(username_or_id):
    """
    Resolves a Steam username, vanity URL, or ID into the mandatory 64-bit numeric SteamID.
    """

    global steam_id

    if steam_id:
        return steam_id

    steam = Steam(config.STEAM_API_KEY)

    # Check if it's already a numeric ID
    if username_or_id.isdigit() and len(username_or_id) == 17:
        return username_or_id

    # Try resolving as a Vanity URL (The most common case)
    # This hits: http://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/
    try:
        # The library might expose this, but sometimes it's hidden.
        # If steam.users.resolve_vanity_url(username_or_id) exists, use that.
        # Otherwise, 'search_user' usually does the trick.

        user_data = steam.users.search_user(username_or_id)

        # search_user returns a payload like: {'player': {'steamid': '765...', ...}}
        if 'player' in user_data and 'steamid' in user_data['player']:
            return user_data['player']['steamid']

    except Exception as e:
        print(f"Error resolving Steam ID: {e}")

    return None

def search_steam_store(term, limit=10):
    """
    Scrapes the Steam Search page for games matching the term.
    Returns: List of dicts {name, price, reviews, link}
    """
    # URL Encode the search term
    encoded_term = urllib.parse.quote(term)
    url = f"https://store.steampowered.com/search/?term={encoded_term}&category1=998"  # 998 = Games only (no DLC)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        results = []
        rows = soup.select('#search_resultsRows > a')

        for row in rows[:limit]:
            title = row.select_one('.title').text.strip()

            # Extract AppID from URL
            href = row['href']
            appid_match = re.search(r'/app/(\d+)', href)
            appid = appid_match.group(1) if appid_match else "Unknown"

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

            results.append({
                "appid": appid,
                "name": title,
                "price": price,
                "reviews": reviews,
                "link": href
            })

        return results

    except Exception as e:
        print(f"Error scraping Steam: {e}")
        return []


def get_similar_games(game_name):
    """
    Calls steam api and steamspy to get recommended similar games and their details

    Args:
        :param game_name: the name of the game to search for
    Returns:
        :return: the game details and a max of 9 similar games details according to steam
    """
    # get app info from api
    app = get_steam_app_info(game_name)
    target_appid = app["id"][0]

    # cookies to not get blocked by age gate
    cookies = {'birthtime': '568022401', 'mature_content': '1'}
    # This URL is what the Steam Client uses to populate the "More Like This" section
    url = f"https://store.steampowered.com/recommended/morelike/app/{target_appid}/"
    response = requests.get(url, cookies=cookies, timeout=10)

    soup = BeautifulSoup(response.content, 'html.parser')

    # 1. Target the specific grid container.
    # The main "Similar Items" list usually has the id="released" in this specific view.
    container = soup.find('div', id="released")

    # 2. Find all the "capsules" (the clickable game images)
    # We limit to the first 5 for this example, remove [:5] to get them all
    items = container.find_all('a', class_='similar_grid_capsule')[:9]

    games_found = []

    for item in items:
        url = item.get('href')

        # 3. Extract the title from the URL
        # URL format: https://store.steampowered.com/app/ID/GAME_NAME/?snr=...
        try:
            # Split the URL by '/'
            parts = url.split('/')

            # In standard Steam URLs, the name is usually at index 5
            # 0=https:, 1=, 2=store..., 3=app, 4=ID, 5=Name
            game_slug = parts[5]

            # Clean up the name (remove underscores, decode URL characters)
            game_title = game_slug.replace('_', ' ')

            games_found.append({
                "title": game_title,
                "url": url
            })
        except IndexError:
            continue

    # Output results
    print(f"Found {len(games_found)} games:")
    similar_games = []
    similar_games.append(get_global_game_info(game_name))

    for game in games_found:
        print(f"- {game['title']}")

        payload = get_global_game_info(game['title'])

        print(payload)

        #print(app_info)
        #print(app_details)
        #print(game_info)
        sleep(1)

        similar_games.append(payload)

    return similar_games


def get_game_deals(title, appid):
    # --- STEP 1: Find the Game ---
    search_url = "https://www.cheapshark.com/api/1.0/games"
    search_params = {
        "title": title,
        "steamAppID": appid
    }

    print("Searching CheapShark for game...")
    try:
        response = requests.get(search_url, params=search_params)
        response.raise_for_status()

        # Parse the JSON list
        games_list = response.json()

        if not games_list:
            print("No games found!")
            return

        # The API returns a list, so we take the first item [0]
        first_match = games_list[0]

        # Extract the specific ID we need
        raw_deal_id = first_match['cheapestDealID']
        deal_id = unquote(raw_deal_id)
        game_name = first_match['external']

        print(f"   Found: {game_name}")
        print(f"   Deal ID: {deal_id}")

        # --- STEP 2: Use the ID for the Second Request ---
        deal_url = "https://www.cheapshark.com/api/1.0/deals"
        deal_params = {
            "id": deal_id
        }

        print("\nFetching CheapShark specific deal details...")
        deal_response = requests.get(deal_url, params=deal_params)
        deal_response.raise_for_status()

        deal_data = deal_response.json()

        # Print the final details
        print("\n--- Deal Details ---")
        print(f"Store ID: {deal_data['gameInfo']['storeID']}")
        print(f"Price: ${deal_data['gameInfo']['salePrice']}")
        print(f"Retail: ${deal_data['gameInfo']['retailPrice']}")

        store_url = "https://www.cheapshark.com/api/1.0/stores"
        store_params = {}

        store_response = requests.get(store_url)
        store_response.raise_for_status()

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

    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
    except (KeyError, IndexError) as e:
        print(f"Error parsing JSON data: {e}")

    except requests.exceptions.RequestException as e:
        # Handle connection errors or bad responses
        print(f"Error making request: {e}")


def scrape_steam_forums(appid, gamename):
    """
    Scrapes the first page of 'General Discussions' thread titles for a game.
    Returns an analysis generated by AI of the current discourse in string format.
    """
    url = f"https://steamcommunity.com/app/{appid}/discussions/0/"  # /0/ is usually General
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0'}

    # cookies to not get blocked by age gate
    cookies = {'birthtime': '568022401', 'mature_content': '1'}

    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=10)
        # Steam sometimes redirects to an age gate or main page if invalid
        if "discussions" not in response.url:
            return "Could not access forums (Age Gate or Invalid AppID)."

        soup = BeautifulSoup(response.text, 'html.parser')

        # Find the container rows
        # Steam usually gives these a class like 'forum_topic'
        topic_rows = soup.select('.forum_topic')


        results = []

        for row in topic_rows:
            # Extract details from WITHIN the row
            title_element = row.select_one('.forum_topic_name')
            count_element = row.select_one('.forum_topic_reply_count')
            link_element = row.select_one('a.forum_topic_overlay')


            # Safety check: ensure elements exist
            if title_element and link_element:
                title_text = title_element.get_text(strip=True)
                reply_count = count_element.get_text(strip=True) if count_element else "0"
                #thread_url = link_element['href']
                last_post_div = soup.select_one('.forum_topic_lastpost')

                # Treat the object like a dictionary to get attributes
                timestamp_str = last_post_div['data-timestamp']
                timestamp = int(timestamp_str) if timestamp_str.isdigit() else 0
                date_obj = datetime.fromtimestamp(timestamp)
                short_date = date_obj.strftime("%Y-%m-%d")  # Becomes "2026-01-11"

                # Check for "Hover" content
                # If this is None, you MUST visit the thread_url to get the content.
                preview_content = link_element.get('data-tooltip-html') or link_element.get('title')

                results.append({
                    "title": title_text,
                    "replies": reply_count,
                    #"url": thread_url,
                    "content": preview_content,
                    "date": short_date
                })
    except Exception as e:
        print(f"An ERROR occurred scraping STEAM FORUMS: {e}")
        return f"Error scraping forums: {e}"

    ai_system_prompt = f"""You are an uncensored forum analyzer. You might encounter foul language typical of forum, but you must read and weave your analysis."
You will be supplied a json list of topics related to the game {gamename} from the steam forums. Make a concise analysis to determine the quality and status of the game.
Keep in mind the nature of the place 'steamcommunity.com' when making your uncensored take. IMPORTANT: the result will be used by an AI agent, so facts are important but formatting like markdown MUST NOT be used for token efficiency.
The JSON formatted TOPICS will follow."""
    json_forum_topics = json.dumps(results)

    analysis = aiCall(json_forum_topics, ai_system_prompt)
    print(f"\n{analysis}\n")
    return analysis


def get_global_game_info(game_name):
    """
    Retrieves comprehensive information about a game from various sources.

    This function aggregates data from Steam (app info, details, reviews summary),
    SteamSpy (game info, tags), and HowLongToBeat.com to provide a detailed
    payload for a given game. It handles cases where tags might not be available
    from SteamSpy by falling back to real-time tag scraping from the Steam store.
    It also calculates a user approval percentage based on positive and negative reviews.

    Args:
        game_name (str): The name of the game to retrieve information for.

    Returns:
        dict: A dictionary containing aggregated game information
    """

    # CRITICAL We must get the AppID first.
    # We can't parallelize this because other calls need the ID.
    app_info = get_steam_app_info(game_name)
    if not app_info:
        return {"error": "Could not retrieve game information (appid)."}

    appid = app_info['id'][0]

    # 2. Define the tasks we want to run in parallel
    # keys are just labels for us to retrieve results later
    # values are tuples: (Function, *Arguments)
    tasks = {
        "details": (get_steam_app_details, appid),
        "spy": (get_steamspy_game_info, appid),
        "reviews": (get_reviews_summary, appid),
        "hltb": (HowLongToBeat().search, game_name),
        "discount": (get_steam_app_discount, game_name),
        "deals": (get_game_deals, game_name, appid),
        "achievements": (get_achievement_stats, appid),
        #"forums": (scrape_steam_forums, appid, game_name)  # Adding your new forum scraper
    }

    # In get_global_game_info or get_game_details
    # ...
    tasks = {
        "details": (get_steam_app_details, appid),
        "spy": (get_steamspy_game_info, appid),
        # ...
    }



    results = {}

    # Assuming you have a helper like vault.is_game_owned(appid)
    if vault.is_game_owned(appid):
        tasks["achievements"] = (get_achievement_stats, appid)
    else:
        # Just return a placeholder so the Agent knows why it's missing
        results["achievements"] = "Game not owned."

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
    achievements = results.get("achievements")
    #steam_community = results.get("forums", "No forum data.")

    if how_long_to_beat and len(how_long_to_beat) > 0:
        how_long_to_beat_hours = {
            "main_story" : how_long_to_beat[0].main_story,
            "main_extra" : how_long_to_beat[0].main_extra,
            "completionist" : how_long_to_beat[0].completionist,
            "all_styles" : how_long_to_beat[0].all_styles
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
        top_tags = get_realtime_tags(appid) # fallback to steam scraping to get tags

    approval = 0

    #print(app_details)

    positive = summary.get('total_positive')
    negative = summary.get('total_negative')
    # average_forever = round(game_info.get('average_forever') / 60, 1) # Moved up
    # median_forever = round(game_info.get('median_forever')/ 60, 1) # Moved up
    ccu = str(game_info.get('ccu')) if game_info.get('ccu') != 0 else "N/A" # For ai values of 0, implies missing.
    short_description = app_details['short_description']

    def fmt_price(p):
        try:
            if p is None: return "0.00"
            val = int(p)
            if val == 0: return "Free"
            return f"{val / 100:.2f}"
        except:
            return str(p)

    # Default price values
    price_data = {}
    final_formatted = fmt_price(game_info.get('price', 0))
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

    # --- PRICE PER HOUR CALCULATION ---
    price_per_hour = "N/A (No Data)"
    price_per_hour_low = "N/A (No Data)"

    try:
        # 1. Get Main Story Hours
        main_hours = 0
        if how_long_to_beat and len(how_long_to_beat) > 0:
            main_hours = float(how_long_to_beat[0].main_story)

        if main_hours > 0:
            # 2. Calculate for Official Steam Price
            # game_info['price'] is usually in Cents (e.g. 1999 for $19.99)
            steam_price_cents = game_info.get('price')
            if steam_price_cents is not None:
                steam_price = float(steam_price_cents) / 100.0
                pph = steam_price / main_hours
                price_per_hour = f"${pph:.2f}/h"

            # 3. Calculate for Lowest Found Price (CheapShark)
            if best_deal and 'price' in best_deal:
                # best_deal['price'] is usually a string "14.99"
                deal_price = float(best_deal['price'])
                pph_low = deal_price / main_hours
                price_per_hour_low = f"${pph_low:.2f}/h"
        else:
            # Explicitly state why
            price_per_hour = "N/A (No HLTB Data)"
            price_per_hour_low = "N/A (No HLTB Data)"

    except Exception as e:
        print(f"Error calculating PPH: {e}")

    payload = {
        "title": game_info['name'],
        "description": short_description,
        "market_analysis": {
            "price_per_hour": price_per_hour,
            "price_per_hour_low": price_per_hour_low,
            "official_current": price_str,
            "lowest_recorded": f"${best_deal['price']} ({best_deal['store']})" if best_deal else "N/A"
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
        "achievements": achievements,
        #"steam_community": steam_community
    }

    return payload


def get_batch_game_details(game_names: list[str]) -> dict:
    """
    Retrieves details for multiple games simultaneously.
    Use this when the user mentions multiple games to save time.

    Args:
        game_names: A list of strings, e.g. ["Hades", "Bastion", "Pyre"]

    Returns:
        Dict keyed by game name containing the info payload.
    """
    print(f"--- BATCH FETCHING {len(game_names)} GAMES ---")

    results = {}

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
                results[name] = data
            except Exception as e:
                print(f"Batch error for {name}: {e}")
                results[name] = {"error": str(e)}

    return results

def generate_contextual_dna(game_name, limit=10):
    """
    Generates a DNA report specific to the GENRE of the target game.
    Ignores your 5000 hours in Dota if the target is a Racing game.
    """
    target_payload = get_global_game_info(game_name)

    # Extract tags from the payload
    # (Your payload has 'tags': ['Action', 'Indie'...])
    target_tags = target_payload.get('tags', [])
    print(f"Target Tags: {target_tags}")

    games = vault.get_all_games()

    # 1. Clean Target Tags
    # Ensure list format and lowercase for matching
    if not target_tags: return "NO DATA!"  # RETURN NOTHING!

    target_set = {t.lower() for t in target_tags}

    relevant_games = []

    for game in games:
        if not game['tags']: continue

        # Calculate Relevance (Jaccard Index)
        # How many tags does this library game share with the target?
        lib_tags = {t.strip().lower() for t in game['tags'].split(',')}

        intersection = len(target_set.intersection(lib_tags))

        # We only care if there is meaningful overlap (at least 2 shared tags)
        if intersection >= 2:
            # Score = Overlap * Playtime Weight (so we see favorites first)
            # But we cap playtime weight so 1000h doesn't crush 20h
            relevant_games.append({
                "name": game['name'],
                "playtime": game['playtime_forever'],
                "shared_tags": intersection,
                "status": calculate_status(game)  # Helper function for status
            })

    # Sort by Relevance (Shared Tags) then Playtime
    relevant_games.sort(key=lambda x: (x['shared_tags'], x['playtime']), reverse=True)

    # Construct the Report
    top_relevant = relevant_games[:limit]

    if not top_relevant:
        return "[GENRE WARNING] User has ZERO experience in this genre. They are a tourist."


    report = f"""
[RELEVANT GAMING HISTORY]
The user is looking at a game with tags: {list(target_set)[:max_tags]}
Here is their track record with SIMILAR games:
"""

    for g in top_relevant:
        playtime_hr = int(g['playtime'] / 60)
        # Add HLTB context: "111h (ADDICTED | Story: 15h)"
        hltb_context = f" | Story: {g.get('hltb_main', '?')}h" if g.get('hltb_main') else ""

        report += f"- {g['name']}: {playtime_hr}h ({g['status']}{hltb_context}) [Matches {g['shared_tags']} tags]\n"

    return report

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
    response = requests.get(url=url + appid, params=params, headers={'User-Agent': 'Mozilla/5.0'})
    # Print the final constructed URL
    print(response.url)
    return response.json()

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


def get_n_reviews(appid, n, review_type="all"):
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
        'num_per_page': 100
    }

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


def get_steam_app_info(game_name: str):
    """
    Fetches the app id for a given game name, using fuzzy logic to find the
    best match among the search results.
    """
    print(f"Hunting appid for '{game_name}'...")

    steam = Steam(config.STEAM_API_KEY)

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

        # 1. THE GOLDEN TICKET: Exact Match
        if title_clean == target_clean:
            print(f" -> EXACT MATCH FOUND: {title} ({app['id']})")
            return app

        # 2. The "Close Enough" Metric (0.0 to 1.0)
        # SequenceMatcher calculates how many edits it takes to turn A into B
        score = difflib.SequenceMatcher(None, target_clean, title_clean).ratio()

        # Bonus: specific fix for "The" (e.g., "Witcher 3" vs "The Witcher 3")
        if target_clean in title_clean:
            score += 0.1  # Boost partial contains

        print(f"    - Checking: '{title}' | Score: {score:.2f}")

        if score > highest_score:
            highest_score = score
            best_match = app

    # Threshold Check: If the best match is trash, trust Steam's sorting (index 0)
    # 0.6 is a decent cutoff for "vaguely similar"
    if highest_score < 0.4:
        print(f" -> Best match score ({highest_score:.2f}) is pathetic. Defaulting to Steam's top pick.")
        return candidates[0]

    print(f" -> Winner: {best_match['name']} ({best_match['id']}) with score {highest_score:.2f}\n")
    return best_match

def get_steam_app_discount(game_name:str):
    steam = Steam(config.STEAM_API_KEY)

    # arguments: app_id
    app = steam.apps.search_games(game_name, fetch_discounts = True)
    return app["apps"][0].get('discount')

def get_steam_app_details(appid: int) -> Any:
    """
    Gets the app info for a given game name from the Steam API.

    Args:
        appid: The steam id of the game to get the app info for.

    Returns:
        A dictionary containing the app id and price.
    """
    steam = Steam(config.STEAM_API_KEY)

    # arguments: app_id
    app = steam.apps.get_app_details(appid)
    return app[str(appid)].get('data')

def get_steam_reviews(appid, count):
    """
    Gets the reviews for a given appid from the Steam store.

    Args:
        appid: The id of the app to get the reviews for.
        count: The number of positive and negative reviews to get.

    Returns:
        A dictionary containing the reviews, the review summary, and the number of positive and negative reviews.
    """
    positive = get_n_reviews(appid, count, "positive")
    negative = get_n_reviews(appid, count, "negative")

    reviews = positive + negative

    count_positive = len(positive)
    count_negative = len(negative)

    summary = get_reviews_summary(appid)

    return {'reviews': reviews, 'summary': summary, 'count_positive': count_positive, 'count_negative': count_negative}

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

def get_reviews_byname(game_name, count=5):
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
            "voted_up",
            "votes_up",
            "timestamp_created",
            "playtime_at_review",
            "playtime_forever"
        ]
    }

    app = get_steam_app_info(game_name)

    appid = app['id'][0]

    steam_reviews = get_steam_reviews(appid, count)

    steam_reviews = clean_json_for_ai(steam_reviews,
                                      transformations=review_schema["transformations"],
                                      keep_keys=review_schema["keep_keys"])

    return steam_reviews

def get_reviews_byname_formatted(game_name, count=5):
    """
    Gets the reviews for a given game name.

    Args:
        game_name: The name of the game to get the reviews for.
        count: The number of positive and negative reviews to get.

    Returns:
        A string containing the formatted reviews.
    """
    app = get_steam_app_info(game_name)

    appid = app['id'][0]
    price = app['price']

    steam_reviews = get_steam_reviews(appid, count)
    sleep(1) # Must be preserved to keep the api from chocking.
    #gameinfo = get_steamspy_game_info(appid)

    global_gameinfo = get_global_game_info(game_name)

    return format_reviews_for_ai(price, steam_reviews, global_gameinfo)

def format_reviews_for_ai(price, steam_reviews, gameinfo):
    """
    Formats the reviews and game info into a single string for the AI to analyze.

    Args:
        price: The price of the game.
        steam_reviews: A dictionary containing the reviews, the review summary, and the number of positive and negative reviews.
        gameinfo: A json object containing the game info from SteamSpy.

    Returns:
        A string containing the formatted reviews.
    """
    import textwrap
    reviews = steam_reviews['reviews']
    summary = steam_reviews['summary']
    count_positive = steam_reviews['count_positive']
    count_negative = steam_reviews['count_negative']

    review_score = summary['review_score']
    review_score_desc = summary['review_score_desc']
    total_positive = summary['total_positive']
    total_negative = summary['total_negative']

    title = gameinfo.get('title')

    human_reviews = f"""\
    "{title}" data will follow:
    ```json
    {gameinfo}
    ```
    
    total positive reviews: {total_positive} total negative: {total_negative} score: {review_score} score description: {review_score_desc}
    votes_up is how much a review is voted up, votes_funny is how much is voted funny.
    Popular reviews, {count_positive} positive and {count_negative} negative as sample for {title} will follow:
    ```
    """

    human_reviews = textwrap.dedent(human_reviews)

    for review in reviews:
        playtime_at_review = review.get('author').get('playtime_at_review')
        num_games_owned = review.get('author').get('num_games_owned')
        received_for_free = review.get('received_for_free')
        voted_up = review.get('voted_up')
        review_text = review.get('review')
        votes_up = review.get('votes_up')
        votes_funny = review.get('votes_funny')

        human_reviews +=    ("---\nplaytime_at_review: {playtime_at_review}, num_games_owned: {num_games_owned}, received_for_free: {received_for_free}, positive: {voted_up}, votes_up: {votes_up}, votes_funny:{votes_funny}\ntext=\"\"\"\n{review_text}\n\"\"\"\n\n"
                             .format(playtime_at_review=playtime_at_review, num_games_owned=num_games_owned, received_for_free=received_for_free, voted_up=voted_up, review_text=review_text, votes_up=votes_up, votes_funny=votes_funny))



    human_reviews += """```"""


    return human_reviews


def get_achievement_stats(appid = -1, game_name = ""):
    """
    Fetches User Achievement progress + Global Rarity.
    Returns a summary string for the Agent.
    """
    steam = Steam(config.STEAM_API_KEY)

    # Resolve AppID
    if appid == -1 and len(game_name) > 0:
        app_info = get_steam_app_info(game_name)
        appid = app_info['id'][0]
        if not app_info:
            return f"Could not find game: {game_name}"
    elif appid != -1:
        pass
    else:
        return f"Specify appid or game name."

    global steam_id
    steam_id = resolve_steam_id(config.STEAM_USER)  # You need the numeric 64-bit ID here
    if not steam_id:
        return "Error: Could not resolve Steam ID. Check settings."

    try:
        # 1. Get User Data
        user_achievements = steam.apps.get_user_achievements(steam_id, appid)

        # Handle "Profile Private" or "No Stats" errors
        if 'playerstats' not in user_achievements:
            if user_achievements.get('error'):
                return f"Error: {user_achievements.get('error')} (Is your profile public?)"
            return f"No achievement data found for {game_name}."

        user_data = user_achievements['playerstats'].get('achievements', [])
        if not user_data:
            return f"No achievements found for {game_name} (It might not have any)."

        # Get Global Percentages
        global_url = f"http://api.steampowered.com/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v0002/?gameid={appid}&format=json"
        global_resp = requests.get(global_url, timeout=5).json()
        global_data = {a['name']: a['percent'] for a in
                       global_resp.get('achievementpercentages', {}).get('achievements', [])}

        # Get Schema (Readable Names)
        schema_url = f"http://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/?key={config.STEAM_API_KEY}&appid={appid}"
        schema_resp = requests.get(schema_url, timeout=5).json()

        name_map = {}
        if 'game' in schema_resp and 'availableGameStats' in schema_resp['game']:
            for ach in schema_resp['game']['availableGameStats']['achievements']:
                name_map[ach['name']] = ach['displayName']

        # PROCESS DATA
        unlocked = []
        locked = []

        for ach in user_data:
            api_name = ach['apiname']
            # Safety: Some hidden achievements might not have a display name in the schema yet
            real_name = name_map.get(api_name, api_name)
            percent = global_data.get(api_name, 0.0)

            item = {
                "name": real_name,
                "percent": percent,
                "timestamp": ach.get('unlocktime', 0),  # unlocktime key might be missing if locked
                "achieved": ach.get('achieved', 0)
            }

            if item['achieved'] == 1:
                unlocked.append(item)
            else:
                locked.append(item)

        # 5. Stats Calculation
        total = len(user_data)
        count = len(unlocked)
        completion_rate = int((count / total) * 100) if total > 0 else 0

        # Find Rarest Unlocked
        unlocked.sort(key=lambda x: x['percent'])  # Sort by rarity (asc)
        rarest = unlocked[0] if unlocked else None

        # Find Latest Unlocked
        unlocked.sort(key=lambda x: x['timestamp'], reverse=True)  # Sort by time (desc)
        latest = unlocked[0] if unlocked else None

        # Formulate the Report
        report = [f"Achievement Status for {game_name}:"]
        report.append(f"- Completion: {count}/{total} ({completion_rate}%)")

        if rarest:
            report.append(f"- Rarest Unlocked: '{rarest['name']}' (Only {rarest['percent']}% of players have this)")

        # if latest:
        #     date_str = datetime.fromtimestamp(latest['timestamp']).strftime('%Y-%m-%d')
        #     report.append(f"- Latest Unlock: '{latest['name']}' on {date_str}")

        if unlocked:
            count = 0
            total = len(unlocked) if len(unlocked) < 3 else 3
            report.append(f"- Last {total} Unlocked:")
            for item in unlocked:
                date_str = datetime.fromtimestamp(item['timestamp']).strftime('%Y-%m-%d %H:%M')
                report.append(f"- '{item['name']}' on {date_str}")
                count += 1
                if count >= total: break

        if completion_rate < 100 and locked:
            # Find the "Most Common" locked achievement (The easiest one they missed)
            locked.sort(key=lambda x: x['percent'], reverse=True)
            easiest_miss = locked[0]
            report.append(
                f"- Next Step: '{easiest_miss['name']}' ({easiest_miss['percent']}% of players have this)")

        return "\n".join(report)

    except Exception as e:
        return f"Error fetching achievements: {e}"




def web_search(query, max_results=10):
    """
    Performs a lightweight web search using DuckDuckGo.
    Returns a string summary of the top results.
    """
    print(f"--- WEB SEARCH: {query} ---")
    result = {}
    try:
        results = ddgs.DDGS().text(query, max_results=max_results)

        if not results:
            result['message'] = 'No results found.'

        data = []
        for i, res in enumerate(results, 1):
            title = res.get('title', 'No Title')
            body = res.get('body', '')
            href = res.get('href', '')
            data.append(
                {
                    'title': title,
                    'body': body,
                    'href': href
                }
            )

        result["search_results"] = data


    except Exception as e:
        result['message'] = "Error searching web: {e}"

    return result



def get_webpage(url):
    """
    Visits a webpage and extracts the main readable text using Trafilatura.
    automatically strips ads, menus, and boilerplate.
    """
    print(f"--- REAPER VISITING: {url} ---")

    try:
        # Download the HTML
        # Trafilatura handles user-agents and headers automatically
        downloaded = trafilatura.fetch_url(url)

        if downloaded is None:
            return "Error: Could not retrieve the webpage (Network error or empty response)."

        # Extract Main Content
        # include_tables=False: Skips complex tables that might confuse the LLM
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            include_links=False
        )

        if not text:
            return "Error: Page content was empty or unreadable."

        # Collapse Whitespace (Trafilatura does this mostly, but good to be safe)
        clean_text = text.replace("\n", " ").strip()

        # Safety Truncate
        # Limit to prevent token explosion
        limit = 6500
        if len(clean_text) > limit:
            clean_text = clean_text[:limit] + "... [TRUNCATED FOR CONTEXT SAFETY]"
            print("WARNING: Page content was truncated to {limit} characters.".format(limit=limit))

        return clean_text

    except Exception as e:
        return f"Error processing page: {e}"


def scrape_reddit_search(game_name):
    """
    Scrapes Reddit search results via their public JSON endpoint.
    Use with caution: Rate limits are strict.
    """
    # 1. The "Magic" Header.
    # NEVER use 'python-requests/x.x'. Reddit blocks it instantly.
    # Use a real browser string or a descriptive bot name.
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    # 2. The JSON Endpoint
    # sort=relevance or top, t=year (to keep it recent)
    url = f"https://www.reddit.com/search.json?q={game_name}&sort=relevance&t=year&limit=5"

    try:
        resp = requests.get(url, headers=headers, timeout=5)

        # Rate Limit Fallback
        if resp.status_code == 429:
            print("Error: Reddit is rate-limiting the Reaper. (Trying WEB Search...)")
            return web_search(f"site:reddit.com {game_name}")

        data = resp.json()
        posts = data.get('data', {}).get('children', [])

        if not posts:
            return "No Reddit threads found."

        results = []
        for post in posts:
            p = post['data']

            body = p.get('selftext', '')

            # If body is empty, it might be an image/link post. Use the URL instead.
            if not body:
                url_preview = p.get('url_overridden_by_dest', p.get('url', ''))
                if url_preview:
                    body = f"[Link/Image Post]: {url_preview}"

            # Clean & Truncate (Critical for Token Economy)
            # Flatten newlines to keep JSON clean
            body = body.replace("\n", " ").strip()
            if len(body) > 500:
                body = body[:500] + "... [TRUNCATED]"
            # -------------------------

            results.append({
                'title': p.get('title', 'No Title'),
                'score': p.get('score', 0),
                'comments': p.get('num_comments', 0),
                'subreddit': p.get('subreddit_name_prefixed', 'r/gaming'),
                'body': body  # Matches web_search key name
            })

        if not results:
            print("Error: Reddit ignoring the Reaper. (Trying WEB Search...)")
            return web_search(f"site:reddit.com {game_name}")

        return {"results": results}

    except Exception as e:
        print(f"Error: Reddit search failed with error: {e}")
        return f"Reddit scrape failed: {e}"

def scrape_4chan_thread(board_name: str, thread_id: int):
    board = Board(board_name)
    thread = board.get_thread(thread_id)

    thread_result = {}

    if not thread is None:
        thread_text = f"Thread Topic: {thread.topic.subject}\n\n"  # OP's text

        thread_result["topic"] = thread.topic.subject
        thread_result["board"] = board_name
        thread_result["posts"] = []

        for post in thread.posts:
            post_result = {
                "datetime": post.datetime.isoformat(),
                "id": post.post_id,
                "text": post.text_comment
            }
            #thread_text += f"{post.post_id} {post.datetime}: {post.text_comment}\n\n"  # Replies
            thread_result["posts"].append(post_result)

    return thread_result


def find_4chan_thread(board_name: str, topic_search: str, threshold: float = 0.4) -> list:
    """
    Scans a 4chan board for threads matching the topic_search string.
    Returns list of thread IDs where similarity > threshold.
    """
    try:
        board = Board(board_name)
        threads = board.get_all_threads()
    except Exception as e:
        print(f"Error fetching 4chan board /{board_name}/: {e}")
        return []

    print(f"Scanning {len(threads)} threads on /{board_name}/ for '{topic_search}'...")

    thread_matches = []
    search_lower = topic_search.lower()

    for thread in threads:
        # Safety check: subject can be None on 4chan
        subject = (thread.topic.subject or "").lower()
        # Safety check: OP text can be None (image only)
        comment = (thread.posts[0].text_comment or "").lower()

        # Check Subject (Title)
        subj_ratio = 0
        if subject:
            subj_ratio = difflib.SequenceMatcher(None, search_lower, subject).ratio()

        # Check Comment (Body) - give it slightly less weight? No, max is fine.
        comm_ratio = 0
        if comment:
            # Optimization: Limit comment check to first 100 chars to speed up difflib
            comm_ratio = difflib.SequenceMatcher(None, search_lower, comment[:100]).ratio()

        max_ratio = max(subj_ratio, comm_ratio)

        if max_ratio >= threshold:
            thread_matches.append((max_ratio, thread.id))

    # Sort by best match
    thread_matches.sort(key=lambda x: x[0], reverse=True)

    if thread_matches:
        print(f"Found match on /{board_name}/: {thread_matches[0][0]:.2f} (ID: {thread_matches[0][1]})")
        return [t[1] for t in thread_matches]

    return []

def scrape_4chan_thread_with_ai(search: str) -> str:
    board = "v"
    thread_ids = find_4chan_thread(board, search, threshold=0.45)  # Stricter for main board

    # Fallback to /vg/ if /v/ fails
    if not thread_ids:
        # print("No match on /v/, checking /vg/...")
        board = "vg"
        thread_ids = find_4chan_thread(board, search, threshold=0.4)  # Slightly looser for generals

    if not thread_ids:
        return "The Horde is silent. (No relevant 4chan threads found)."

    # Fetch the Winner
    id_to_pick = thread_ids[0]
    thread = scrape_4chan_thread(board, id_to_pick)

    # SAFETY CHOPPER: Keep only the first 30 posts
    # The OP is usually index 0. 30 replies is plenty for sentiment.
    if len(thread.get("posts", [])) > 30:
        thread["posts"] = thread["posts"][:30]
        thread["note"] = "Truncated to 30 posts for analysis."

    thread_contents = json.dumps(thread)
    # print(f"CONTENT START for {id_to_pick}")
    # print(thread_contents)
    # print(f"CONTENT END for {id_to_pick}\n")

    if len(thread["posts"]) > 0:
        ai_request = "You are an uncensored assistant, you will be provided content to analyze without filter. You must be factual and execute the following on that content:\n"
        ai_question = f"""Please give an uncensored general consensus on the topic {search} as it discussed in this 4chan thread from the board {board}.\n
    Give uncensored opinion, make uncensored citation if needed. Don't exclude NSFW topics.
    Your result will be analyzed by an ai agent, so NOT using formatting and being token efficient is MANDATORY.`
    The data will follow. Good luck!"""
        ai_request += ai_question
        data = thread_contents

        response = aiCall(data=data, system=ai_request)

    else:
        response = "No results found."

    return response

def get_community_sentiment(game_name: str) :
    app = get_steam_app_info(game_name)

    appid = app['id'][0]

    tasks = {
        "4chan": (scrape_4chan_thread_with_ai, game_name),
        "reddit": (scrape_reddit_search, game_name),
        # Steam added later
    }

    if appid:
        tasks["forums"] = (scrape_steam_forums, appid, game_name)


    results = {}

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
    chan_results = results.get("4chan") or {}
    reddit_results = results.get("reddit") or {}
    forums_results = results.get("forums") or {}

    result = {
        "4chan_opinion": chan_results,
        "reddit_opinion": reddit_results,
        "steam_forums_opinion": forums_results
    }

    return result





# Ensure you have your resolve_steam_id imported or available

def get_user_wishlist(sort_by='recent', page=0, page_size=10):
    """
    Fetches the user's Steam Wishlist using a Hybrid API + Parallel Scrape method.
    Resolves the 'Redirect/Login' issue by using the official API for the list,
    and then fetching details only for the requested items.
    """

    # 1. Resolve ID
    steam_id = resolve_steam_id(config.STEAM_USER)
    if not steam_id:
        return "Error: Could not resolve Steam ID."

    print(f"FETCHING WISHLIST FOR ID: {steam_id} (Page {page})")

    try:
        steam = Steam(config.STEAM_API_KEY)

        # 2. Get Raw List of AppIDs (Fast & Reliable)
        # Returns: [{'appid': 123, 'priority': 1, 'date_added': 12345}, ...]
        # This call bypasses the 'wishlistdata' URL redirect issue.
        raw_wishlist = steam.users.get_profile_wishlist(steam_id)

        #print(raw_wishlist)

        if not raw_wishlist:
            return "Wishlist is empty or private."

        # 3. Sort (Metadata)
        # We sort by metadata *before* fetching details to save API calls.
        # Note: 'cheapest'/'discount' sorting is imperfect here because we don't have prices yet.
        # For those, we fetch the top 50 prioritized items and then sort them below.
        if sort_by == 'priority':
            raw_wishlist.sort(key=lambda x: x.get('priority', 999))
        elif sort_by == 'recent':
            raw_wishlist.sort(key=lambda x: x.get('date_added', 0), reverse=True)
        elif sort_by in ['cheapest', 'discount']:
            # optimization: default to priority for the fetch batch
            raw_wishlist.sort(key=lambda x: x.get('priority', 999))

        # 4. Pagination / Slicing
        # If sorting by price, we fetch a larger batch (up to 50) to find deals.
        # Otherwise, we only fetch exactly what the page needs.
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

        # 5. Define Worker for Parallel Fetching
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
                # Fetch details from Store API (handles Name, Price, Discount)
                # We use the store API explicitly as it's cleaner for prices than get_app_details sometimes
                # But to keep it simple, we reuse the standard method you likely have, or raw request:
                store_url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=US"
                # cc=US ensures dollar prices. Change if needed.

                resp = requests.get(store_url, timeout=5).json()

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
                pass

            return res

        # 6. Execute Parallel Fetch
        enriched_results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            enriched_results = list(executor.map(fetch_details_worker, items_to_process))

        # 7. Post-Fetch Sorting (If Price/Discount was requested)
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
        return f"Error: {e}"


if __name__ == "__main__":
    #print(get_achievement_stats(game_name="megabonk"))
    print(get_webpage("https://www.reddit.com/r/Helldivers/comments/1n773qh/dragonroach_is_ridiculous_and_whoever_designed_it/"))