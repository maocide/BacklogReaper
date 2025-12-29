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
from openai import OpenAI
import steamspypi
from howlongtobeatpy import HowLongToBeat
from bs4 import BeautifulSoup
from collections import defaultdict

def aiCall(data, system):
    """
    Calls the OpenAI API to analyze the provided data.

    Args:
        data: The data to be analyzed.
        system: The request to be sent to the AI.

    Returns:
        The content of the AI's response.
    """

    #api_key = ""
    #base_url = "https://api.deepseek.com"
    #model = "deepseek-chat"

    client = OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL, timeout=240.0)

    systemRequest ="""
    HUNT for hidden gems with cult followings or niche acclaim—prioritize games dismissed by mainstream critics but worshipped on forums.
    Input format: Pipe-separated values (PSV) with column headers in first line
    Processing instructions:
    1. Calculate backlog_score = (1000000 - playtime_forever) / 100  
    2. Flag games in 'best indie gems' or 'underrated masterpieces' lists with '[CULT]'
    3. Sort all records by backlog_score (descending)
    4. Format output as PSV with columns: appid|name|playtime_forever|backlog_score
    5. Limit output to top 100 rows if results exceed 100
    6. Output raw data only (no commentary)
    
    Expected output format:
    appid|name|playtime_forever|backlog_score
    [calculated data rows...]
    """

    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": data},
        ],
        stream=False
    )

    return(response.choices[0].message.content)


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


def get_realtime_tags(app_id):
    url = f"https://store.steampowered.com/app/{app_id}/"
    # Cookies are needed to bypass the "Age Gate" for mature games
    cookies = {'birthtime': '568022401', 'mature_content': '1'}

    try:
        response = requests.get(url, cookies=cookies, timeout=10)
        if response.status_code != 200:
            return []

        soup = BeautifulSoup(response.text, 'html.parser')

        # Steam stores tags in a specific div class "glance_tags"
        tags_div = soup.find("div", {"class": "glance_tags popular_tags"})

        if tags_div:
            # Extract the text from each tag link, strip whitespace
            tags = [tag.text.strip() for tag in tags_div.find_all("a", {"class": "app_tag"})]
            return tags[:5]  # Return top 5 most popular

        return []

    except Exception as e:
        print(f"Error scraping tags for {app_id}: {e}")
        return []


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
        top_tags = sorted(all_tags, key=all_tags.get, reverse=True)[:5]
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

    if positive is not None and negative is not None and positive + negative != 0:
        approval = round(positive / (positive + negative), 2)

    payload = {
        "title": game_info['name'],
        "description": short_description,  #
        "price": app_info['price'],  #
        "discount": discount,  #
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
        "tags": top_tags  # The top 5 tags sorted
    }

    return payload


def generate_user_dna(steam_games: list, sample_size=50):
    """
    Analyzes the user's ALREADY FETCHED game list to build a quantitative taste profile.
    Returns a JSON string containing top games and weighted tag data.
    """
    print(f"\n--- EXTRACTING RAW BEHAVIORAL DATA (JSON) ---")

    # 1. Filter and Sort
    # We ignore games played for less than 2 hours (120 mins) to filter out idle-card-farming trash.
    valid_games = [g for g in steam_games if int(g.get('playtime_forever', 0)) > 120]
    sorted_games = sorted(valid_games, key=lambda x: int(x['playtime_forever']), reverse=True)

    # We analyze a larger sample (top 50) to get better tag distribution
    target_games = sorted_games[:sample_size]

    tag_playtime_accumulator = defaultdict(int)
    total_minutes_analyzed = 0

    top_games_data = []

    for game in target_games:
        name = game.get('name', 'Unknown')
        playtime_min = int(game.get('playtime_forever', 0))

        total_minutes_analyzed += playtime_min

        # Add to top games list for the AI to see specific titles
        top_games_data.append({
            "title": name,
            "hours": round(playtime_min / 60, 1)
        })

        # Extract Tags
        tags = game.get('tags', [])

        # Normalize tags (handle dict vs list)
        # SteamSpy tags usually come as { "Tag": votes, "Tag2": votes }
        # We only care about the keys.
        tag_list = tags.keys() if isinstance(tags, dict) else tags

        # Weighting Algorithm:
        # We add the FULL playtime of the game to EACH of its top 5 tags.
        # This creates a "Time Spent in Genre" metric.
        if tag_list:
            count = 0
            for tag in tag_list:
                if count >= 5: break  # Cap at top 5 tags per game to reduce noise
                tag_playtime_accumulator[tag] += playtime_min
                count += 1

    # 2. Process Tag Statistics
    # Sort tags by total accumulated minutes
    sorted_tags = sorted(tag_playtime_accumulator.items(), key=lambda x: x[1], reverse=True)

    tag_profile = []
    for tag, minutes in sorted_tags[:15]:  # Top 15 dominant tags
        tag_profile.append({
            "tag": tag,
            "total_minutes": minutes,
            "share_of_time": round((minutes / total_minutes_analyzed) * 100, 1)  # % of analyzed time
        })

    # 3. Construct the Payload
    dna_payload = {
        "user_stats": {
            "total_analyzed_hours": round(total_minutes_analyzed / 60, 0),
            "sample_size": len(target_games)
        },
        "dominant_tags": tag_profile,
        "most_played_titles": top_games_data[:15]  # Only show top 15 specific games
    }

    return json.dumps(dna_payload, indent=2)

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

def get_steam_app_info(game_name:str):
    """
    Fetches the app id for a given game name from the Steam API.

    Args:
        game_name: The name of the game to fetch the app id for.

    Returns:
        The app id for the given game name, or -1 if not found.
    """
    print("contacting STEAM API for a appid...\n")

    steam = Steam(config.STEAM_API_KEY)

    # arguments: search
    apps = steam.apps.search_games(game_name)
    print(apps)
    if 'apps' in apps and len(apps['apps']) > 0:
        print("done.. appid=" + str(apps['apps'][0]['id']) + "\n\n")
        return apps['apps'][0]
    else:
        print("not found!\n\n")
        return -1

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

    human_reviews = """\
    "{title}" data will follow:
    ```json
    {gameinfo}
    ```
    
    total positive reviews: {total_positive} total negative: {total_negative} score: {review_score} score description: {review_score_desc}
    votes_up is how much a review is voted up, votes_funny is how much is voted funny.
    Popular reviews, {count_positive} positive and {count_negative} negative as sample for {title} will follow:
    ```txt
    """.format(title=title, count_positive=count_positive, count_negative=count_negative, gameinfo=json.dumps(gameinfo),
               total_positive=total_positive, total_negative=total_negative, review_score=review_score, review_score_desc=review_score_desc
               )

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

