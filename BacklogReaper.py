import difflib
import json
from http.client import responses
from platform import system
from time import sleep
from typing import Any
from urllib.parse import unquote
from xml.etree.ElementTree import tostring

# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.
import requests
from steam_web_api import Steam
import config
import steamspypi
from howlongtobeatpy import HowLongToBeat
from bs4 import BeautifulSoup
from collections import defaultdict

import vault
from vault import get_realtime_tags, calculate_status

max_tags = 10


def search_steam_store(term, limit=10):
    """
    Scrapes the Steam Search page for games matching the term.
    Returns: List of dicts {name, price, review_summary, url, img}
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

    app_info = get_steam_app_info(game_name)  # get info with steamid
    if not app_info:
        return {}
    appid = app_info['id'][0]
    app_details = get_steam_app_details(appid)  # get details for description
    game_info = get_steamspy_game_info(appid)  # get steamspy info
    summary = get_reviews_summary(appid) # get steam reviews totals
    how_long_to_beat = HowLongToBeat().search(game_name) # get time to beat
    discount = get_steam_app_discount(game_name) # get steam discount information

    if how_long_to_beat is not None and len(how_long_to_beat) > 0:
        how_long_to_beat_hours = {
            "main_story" : how_long_to_beat[0].main_story,
            "main_extra" : how_long_to_beat[0].main_extra,
            "completionist" : how_long_to_beat[0].completionist,
            "all_styles" : how_long_to_beat[0].all_styles
        }
        print(how_long_to_beat_hours)
    else:
        how_long_to_beat_hours = {}

    best_deal = get_game_deals(game_name, appid)

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
    average_forever = game_info.get('average_forever')
    median_forever = game_info.get('median_forever')
    ccu = game_info.get('ccu')
    short_description = app_details['short_description']

    def fmt_price(p):
        try:
            if not p: return "0.00"
            val = int(p)
            if val == 0: return "Free"
            return f"{val / 100:.2f}"
        except:
            return p

    # Default price values
    price_data = {}
    final_formatted = fmt_price(game_info.get('price', 0))
    initial_formatted = fmt_price(game_info.get('initialprice', 0))
    discount_percent = game_info.get('discount', 0)

    if int(discount_percent, 0) > 0:
        price_str = f"{final_formatted} (MSRP: {initial_formatted} | -{discount_percent}% OFF)"
    else:
        price_str = final_formatted

    if positive is not None and negative is not None and positive + negative != 0:
        approval = round(positive / (positive + negative), 2)

    payload = {
        "title": game_info['name'],
        "description": short_description,
        "price": price_str,
        "discount": discount,
        "best_deal": best_deal,
        "developer": game_info['developer'],
        "publisher": game_info['publisher'],
        "genre": game_info['genre'],
        "total_positive": positive,
        "total_negative": negative,
        "user_score": f"{approval * 100}% Positive",  # Calculated approval
        "playtime_avg": f"{average_forever} minutes",  # Tells AI if it's replayable
        "median_forever": f"{median_forever} minutes",
        "how_long_to_beat_hours" : how_long_to_beat_hours, # Various values taken from how long to beat
        "ccu" : ccu,
        "tags": top_tags  # The top tags sorted
    }

    return payload

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

        # 2. Calculate Relevance (Jaccard Index)
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

    # 3. Sort by Relevance (Shared Tags) then Playtime
    relevant_games.sort(key=lambda x: (x['shared_tags'], x['playtime']), reverse=True)

    # 4. Construct the Report
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

def query_game_info(games):
    """
    Queries the SteamSpy API for information about the games in the provided list.

    Args:
        games: A list of games to query information for.
    """

    for game in games:
        attempts = 0
        while True:
            try:

                sleep(1)
                #gameinfo = steam.apps.get_app_details(game['appid'], "US", "metacritic")

                data_request = dict()
                data_request['request'] = 'appdetails'
                data_request['appid'] = game['appid']

                gameinfo = steamspypi.download(data_request)

                print(gameinfo)

                if gameinfo is not None and 'appid' in  gameinfo:


                    approval = 0
                    positive = gameinfo.get('positive')
                    negative = gameinfo.get('negative')
                    average_forever = gameinfo.get('average_forever')
                    median_forever = gameinfo.get('median_forever')
                    ccu = gameinfo.get('ccu')

                    if positive is not None and negative is not None and positive + negative !=0:
                        approval = round(positive / (positive + negative), 2)

                    game['approval'] = approval
                    game['average_forever'] = average_forever
                    game['median_forever'] = median_forever
                    game['ccu'] = ccu

                    if 'tags' not in gameinfo:
                        print(f"  -> No DNA found. Skipping tags.")
                        continue

                        # WEIGHTING ALGORITHM
                        # We add the playtime minutes to the tag's score.
                        # The more you play, the heavier the tag becomes in your profile.
                    game['tags'] = gameinfo.get('tags', {})
                    print(game['tags'])
                    print("{0} OK".format(game['name']))

                    break
                else:
                    print("nodata")
                    break


            except ValueError:
                attempts+=1
                sleep(2)
                print("Oops! API being a bitch. {0}: Try again...".format(attempts))
                if attempts > 3:
                    print("Sorry, there was a problem.  Try again later...")
                    break



def make_pipe_list_games(steam_games: list):
    """
    Creates a pipe-separated list of games from the provided list of games.

    Args:
        steam_games: A list of games to create the pipe-separated list from.

    Returns:
        A string containing the pipe-separated list of games.
    """
    heading = "appid|name|playtime_forever|rtime_last_played|approval|average_forever|median_forever|ccu"
    piped_text = heading + "\n"
    for game in steam_games:
        #print((key))
        #print()
        game_line = ("{0}|{1}|{2}|{3}|{4}|{5}|{6}|{7}\n"
                    .format(game['appid'], game['name'], game['playtime_forever'],  game['rtime_last_played'],game['approval'],  game['average_forever'], game['median_forever'], game['ccu']))
        piped_text += game_line

    return piped_text

def fetch_info_from_api(username):
    """
    Fetches the owned games for the user specified in the config file.

    Returns:
        A list of owned games.
    """
    print("contacting STEAM API, please respond and not say bullshit quota lies...\n")

    steam = Steam(config.STEAM_API_KEY)
    userData = steam.users.search_user(username)
    steamId = userData['player']['steamid']
    userGames = steam.users.get_owned_games(steamId, True, False)
    gameCount = userGames['game_count']
    games = userGames['games']

    print(userGames)
    quit(0)
    query_game_info(games)



    print("done with STEAM crap thanks god.\n\n")
    return(games)


def make_gameinfo_dict(piped_text: str):
    """
    Creates a dictionary of games from a pipe-separated string.

    Args:
        piped_text: A pipe-separated string of games.

    Returns:
        A dictionary of games.
    """
    game = dict()
    games_list = dict()
    header_line = piped_text.splitlines()[0].split("|")
    for line in piped_text.splitlines():

        if line.startswith("appid"):
            header_line = line.split("|")

        else:
            i = 0
            game = dict()
            for values in line.split("|"):
                game[header_line[i]] = values
                i += 1

            games_list[line.split("|")[0]] = game




    return games_list

def sort_and_crop(games):
    """
    Sorts and crops the list of games.

    Args:
        games: A dictionary of games to sort and crop.

    Returns:
        A list of cropped games.
    """
    # Sort based on Values
    sorted_games = dict(sorted(games.items(), key=lambda x: (x[1]['playtime_forever'], -float(x[1]['approval']))))


    # cropping of the list of games based on playtime and approval
    cropped = list()
    for game in sorted_games.items():
        if game[1]['playtime_forever'] <= game[1]['median_forever'] and float(game[1]['approval']) >= 0.7:
            cropped.append(game[1])
    print("Chopped list: " + str(len(cropped)))
    return cropped

def count_games():
    """
    Counts the total number of games and the number of unplayed games for the user specified in the config file.
    """
    steam = Steam(config.STEAM_API_KEY)
    user_data = steam.users.search_user(config.STEAM_USER)
    steam_id = user_data['player']['steamid']
    print()
    user_games = steam.users.get_owned_games(steam_id, True, False)
    unplayed_games = 0
    total_games = 0
    for game in user_games['games']:
        if game['playtime_forever'] == 0:
            unplayed_games += 1

        total_games += 1

    print(f"Total games: {total_games} Unplayed: {unplayed_games}")

