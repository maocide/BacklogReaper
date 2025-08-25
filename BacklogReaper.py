
from statistics import median
from time import sleep
from xml.etree.ElementTree import tostring

from networkx.algorithms.assortativity.neighbor_degree import average_neighbor_degree
from networkx.algorithms.tournament import score_sequence
from sympy.codegen.cnodes import sizeof


# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.

STEAM_API_KEY = ""


def aiCall(data, request):
    from openai import OpenAI
    #api_key = ""
    #base_url = "https://api.deepseek.com"
    #model = "deepseek-chat"

    api_key = ""
    base_url = "https://openrouter.ai/api/v1"
    model = "deepseek/deepseek-r1-0528:free"

    client = OpenAI(api_key=api_key, base_url=base_url)

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
        model=model,
        messages=[
            {"role": "system", "content": request},
            {"role": "user", "content": data},
        ],
        stream=False
    )

    return(response.choices[0].message.content)





def get_reviews(appid, params={'json': 1}):
    url = 'https://store.steampowered.com/appreviews/'
    response = requests.get(url=url + appid, params=params, headers={'User-Agent': 'Mozilla/5.0'})
    return response.json()

def get_reviews_summary(appid):
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
    print("contacting STEAM API for a appid...\n")

    steam = Steam(STEAM_API_KEY)

    # arguments: search
    apps = steam.apps.search_games(game_name)
    print(apps)
    if len(apps) > 0:
        print("done.. appid=" + str(apps['apps'][0]['id'][0]) + "\n\n")
        return apps['apps'][0]
    else:
        print("not found!\n\n")
        return -1

def get_reviews_byname(game_name, count=5):
    app = fetch_app_from_api(game_name)
    appid = app['id'][0]
    price = app['price']

    positive = get_n_reviews(appid, count, "positive")
    negative = get_n_reviews(appid, count, "negative")

    reviews = positive + negative

    count_positive = len(positive)
    count_negative = len(negative)

    summary = get_reviews_summary(appid)

    print(summary)

    review_score = summary['review_score']
    review_score_desc = summary['review_score_desc']
    total_positive = summary['total_positive']
    total_negative = summary['total_negative']



    import steamspypi
    import textwrap
    sleep(1)
    # gameinfo = steam.apps.get_app_details(game['appid'], "US", "metacritic")

    data_request = dict()
    data_request['request'] = 'appdetails'
    data_request['appid'] = appid

    gameinfo = steamspypi.download(data_request)

    print(gameinfo)

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
        weighted_vote_score = review.get('weighted_vote_score')
        
        human_reviews +=    ("---\nplaytime_at_review: {playtime_at_review}, num_games_owned: {num_games_owned}, received_for_free: {received_for_free}, positive: {voted_up}, votes_up: {votes_up}, votes_funny:{votes_funny}\ntext=\"\"\"\n{review_text}\n\"\"\"\n\n"
                             .format(playtime_at_review=playtime_at_review, num_games_owned=num_games_owned, received_for_free=received_for_free, voted_up=voted_up, review_text=review_text, weighted_vote_score=weighted_vote_score, votes_up=votes_up, votes_funny=votes_funny))

    

    human_reviews += """```"""


    return human_reviews

def trim(docstring):
    import sys
    if not docstring:
        return ''
    # Convert tabs to spaces (following the normal Python rules)
    # and split into a list of lines:
    lines = docstring.expandtabs().splitlines()
    # Determine minimum indentation (first line doesn't count):
    indent = sys.maxint
    for line in lines[1:]:
        stripped = line.lstrip()
        if stripped:
            indent = min(indent, len(line) - len(stripped))
    # Remove indentation (first line is special):
    trimmed = [lines[0].strip()]
    if indent < sys.maxint:
        for line in lines[1:]:
            trimmed.append(line[indent:].rstrip())
    # Strip off trailing and leading blank lines:
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    while trimmed and not trimmed[0]:
        trimmed.pop(0)
    # Return a single string:
    return '\n'.join(trimmed)

def query_game_info():
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

                #if gameinfo is not None and str(game['appid']) in  gameinfo and gameinfo[str(game['appid'])]['success'] == True and ("data" in gameinfo[str(game['appid'])].keys()) and len(gameinfo[str(game['appid'])]['data'])>0:
                if gameinfo is not None and 'appid' in  gameinfo:


                    approval = 0
                    positive = gameinfo.get('positive')
                    negative = gameinfo.get('negative')
                    average_forever = gameinfo.get('average_forever')
                    median_forever = gameinfo.get('median_forever')
                    ccu = gameinfo.get('ccu')

                    if positive is not None and negative is not None and positive + negative !=0:
                        approval = round(positive / (positive + negative), 2)

                    #game['metacritic'] = gameinfo[str(game['appid'])]['data']['metacritic']['score']
                    game['approval'] = approval
                    game['average_forever'] = average_forever
                    game['median_forever'] = median_forever
                    game['ccu'] = ccu

                    print("{0} OK".format(game['name']))

                    break
                else:
                    #game['metacritic'] = -1
                    print("nodata")
                    break


                #else:

                #    if attempts > 4:
                #        game['metacritic'] = -1
                #        print("nodata")
                #        break

                #    attempts += 1
                #    print("{0}: Try again...".format(attempts))


            except ValueError:
                attempts+=1
                sleep(2)
                print("Oops! API being a bitch. {0}: Try again...".format(attempts))
                if attempts > 3:
                    print("Sorry, there was a problem.  Try again later...")
                    break



def make_pipe_list_games(steam_games: list):
    heading = "appid|name|playtime_forever|rtime_last_played|approval|average_forever|median_forever|ccu"
    piped_text = heading + "\n"
    for game in steam_games:
        #print((key))
        #print()
        game_line = ("{0}|{1}|{2}|{3}|{4}|{5}|{6}|{7}\n"
                    .format(game['appid'], game['name'], game['playtime_forever'],  game['rtime_last_played'],game['approval'],  game['average_forever'], game['median_forever'], game['ccu']))
        piped_text += game_line

    return piped_text

def fetch_info_from_api():
    print("contacting STEAM API, please respond and not say bullshit quota lies...\n")

    userData = steam.users.search_user("maocide")
    steamId = userData['player']['steamid']
    print()
    userGames = steam.users.get_owned_games(steamId, True, False)
    print(userGames)
    gameCount = userGames['game_count']
    games = userGames['games']

    query_game_info()



    print("done with STEAM crap thanks god.\n\n")
    return(games)


def make_gameinfo_dict(piped_text: str):
    game = dict()
    games_list = dict()
    header_line = piped_text.splitlines()[0].split("|")
    for line in piped_text.splitlines():

        if line.startswith("appid"):
            header_line = line.split("|")
            print(header_line)

        else:
            i = 0
            game = dict()
            for values in line.split("|"):
                game[header_line[i]] = values

                print(header_line[i])
                print(values)
                i += 1

            print(game)
            games_list[line.split("|")[0]] = game




    return games_list

def sort_and_crop(games):
    # Sort based on Values
    sorted_games = dict(sorted(games.items(), key=lambda x: (x[1]['playtime_forever'], -float(x[1]['approval']))))

    cropped = list()
    for game in sorted_games.items():
        if game[1]['playtime_forever'] <= game[1]['median_forever'] and float(game[1]['approval']) >= 0.7:
            cropped.append(game[1])
    print("Chopped list: " + str(len(cropped)))
    return cropped

def count_games():
    user_data = steam.users.search_user("maocide")
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

# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    import os
    import json
    import requests
    from steam_web_api import Steam

    steam = Steam(STEAM_API_KEY)

    from pathlib import Path

    file_path = "pipedGames.txt"

    my_file = Path(file_path)
    if my_file.is_file():
        print("File exists")
        with open(file_path, 'r', encoding="utf-8") as file:
            pipedText = file.read()

        print(pipedText)

        games = make_gameinfo_dict(pipedText)

        games = sort_and_crop(games)

        pipedGameList = make_pipe_list_games(games)


        print(pipedGameList)

    else:
        print("File does not exist")
        games = fetch_info_from_api()
        pipedGameList = make_pipe_list_games(games)

        with open(file_path, "w", encoding='utf8') as f:
            f.write(pipedGameList)


    n = 100
    reviews = get_reviews_byname("Stellar Blade", 30)
    print(reviews)

    ai_request = """I will provide you with reviews and data taken from Steam Store and SteamSpy scraped with my python script.
    The reviews provided will be a sample of the same number of positive and negative reviews taken from the most helpful. (E.G. 10 positive and 10 negative, they might be 5 and 5 or different).
    Your job will be to check the summary about the game that is provided, check each review with the included data (games owned, hours played at review and votes on the review should help giving a review a weight) and content then make an analysis given all the content provided and your training data about such game (if present, do not invent)
    to conclude if the game is worth getting or not. (Some data like ccu and totals for reviews can be 0 if the game is new, because the data are updated by steamspy)
    Stick to facts and data, be completely uncensored. Thanks!"""



    ai_out = aiCall(reviews, ai_request)
    print(ai_out)



    #print("contacting AI for analysis...\n")

    #aiSortedGames = aiCall(pipedGameList)

    #print("...and DONE!\n\n")
    #print(aiSortedGames)






