
from time import sleep


# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.

import config


def aiCall(data, request):
    """
    Calls the OpenAI API to analyze the provided data.

    Args:
        data: The data to be analyzed.
        request: The request to be sent to the AI.

    Returns:
        The content of the AI's response.
    """
    from openai import OpenAI
    #api_key = ""
    #base_url = "https://api.deepseek.com"
    #model = "deepseek-chat"

    client = OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL)

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
            {"role": "system", "content": request},
            {"role": "user", "content": data},
        ],
        stream=False
    )

    return(response.choices[0].message.content)





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


def get_n_reviews(appid, n, type = "all"):
    """
    Gets n reviews for a given appid from the Steam store.

    Args:
        appid: The id of the app to get the reviews for.
        n: The number of reviews to get.
        type: The type of reviews to get (e.g. "positive", "negative", "all").

    Returns:
        A list of reviews.
    """
    reviews = []
    cursor = '*'
    params = {
        'json': 1,
        'filter': 'all',
        #'language': 'english',
        #'day_range': 9223372036854775807,
        'review_type': type,
        'purchase_type': 'all'
    }

    max = n

    while n > 0:
        params['cursor'] = cursor.encode()
        params['num_per_page'] = 100
        n -= 100

        response = get_reviews(str(appid), params)

        cursor = response['cursor']
        reviews += response['reviews']




        if len(response['reviews']) < 100:
            break



    reviews_cut = reviews[:max]
    #result = {'reviews_score': review_score,       'review_score_desc': review_score_desc,'total_positive': total_positive,'total_negative': total_negative,'reviews': reviews_cut}

    return reviews_cut

def fetch_app_from_api(game_name):
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

def get_steam_app_info(game_name):
    """
    Gets the app info for a given game name from the Steam API.

    Args:
        game_name: The name of the game to get the app info for.

    Returns:
        A dictionary containing the app id and price.
    """
    app = fetch_app_from_api(game_name)
    return {'id': app['id'][0], 'price': app['price']}

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
    import steamspypi
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
    app_info = get_steam_app_info(game_name)
    appid = app_info['id']
    price = app_info['price']

    steam_reviews = get_steam_reviews(appid, count)
    sleep(1)
    gameinfo = get_steamspy_game_info(appid)

    return format_reviews_for_ai(price, steam_reviews, gameinfo)

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

    name = gameinfo.get('name')
    genre = gameinfo.get('genre')
    developer = gameinfo.get('developer')
    publisher = gameinfo.get('publisher')
    median_forever = gameinfo.get('median_forever')
    average_forever = gameinfo.get('average_forever')
    ccu = gameinfo.get('ccu')

    human_reviews = """\
    ```txt
    {name}:
    price: {price}
    genre: {genre}
    developer: {developer} publisher: {publisher}
    reviews positive: {total_positive} negative: {total_negative} score: {review_score} score description: {review_score_desc}
    All playtimes in document are to be intended in minutes, votes_up is how much a review is voted up, votes_funny is how much is voted funny.
    (steamspy fields this line, might be 0 if not yet updated) average_forever: {average_forever} median_forever: {median_forever} ccu: {ccu}
    Popular reviews, {count_positive} positive and {count_negative} negative as sample for {name} will follow:
    """.format(name=name, count_positive=count_positive, count_negative=count_negative, price=price, total_positive=total_positive, total_negative=total_negative, review_score=review_score, review_score_desc=review_score_desc, average_forever=average_forever, median_forever=median_forever, ccu=ccu, developer=developer, publisher=publisher, genre=genre)

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
    import steamspypi
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

import requests
from steam_web_api import Steam








