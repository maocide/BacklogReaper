import sqlite3
import time
import random

import requests
from bs4 import BeautifulSoup
from steam_web_api import Steam
import config
from howlongtobeatpy import HowLongToBeat


# Config
DB_NAME = 'backlog_vault.db'


def calculate_status(game):
    """
    Classifies the relationship with the game based on HLTB data.
    """
    playtime_min = game.get('playtime_forever', 0)
    playtime_hrs = playtime_min / 60.0

    hltb_main = game.get('hltb_main', 0)
    hltb_comp = game.get('hltb_completionist', 0)

    # The "Tourist" (Bought it, barely touched it)
    if playtime_min < 60:
        return "Untouched"

    # The "Addict" (Played way past the completionist time)
    # Multiplayer games, Roguelikes, or obsessive behaviors fall here.
    if hltb_comp > 0 and playtime_hrs > (hltb_comp * 1.2):
        return "ADDICTED"

    # The "Finisher" (Beat the main story)
    if hltb_main > 0 and playtime_hrs >= (hltb_main * 0.8):
        return "Finished"

    # The "Dropper" (Played significantly but stopped before the end)
    # If you played > 2 hours but < 30% of the story, you likely bounced off.
    if hltb_main > 0 and playtime_hrs > 2 and playtime_hrs < (hltb_main * 0.3):
        return "DROPPED"

    # 5. Default
    return "Played"

def get_realtime_tags(app_id):
    url = f"https://store.steampowered.com/app/{app_id}/"
    cookies = {'birthtime': '568022401', 'mature_content': '1'}
    try:
        response = requests.get(url, cookies=cookies, timeout=10)
        if response.status_code != 200: return []
        soup = BeautifulSoup(response.text, 'html.parser')
        tags_div = soup.find("div", {"class": "glance_tags popular_tags"})
        if tags_div:
            return [tag.text.strip() for tag in tags_div.find_all("a", {"class": "app_tag"})][:5]
        return []
    except Exception as e:
        print(f"Error scraping tags for {app_id}: {e}")
        return []

def get_connection():
    """
    Creates a fresh connection.
    check_same_thread=False allows basic multi-threaded usage,
    but it's safer to just open/close per function.
    """
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # Allows dict-like access (row['name'])
    return conn


def init_db():
    """
    Creates local sql lite db
    """
    with get_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS games (
            appid INTEGER PRIMARY KEY,
            name TEXT,
            playtime_forever INTEGER,
            rtime_last_played INTEGER,  -- <--- (Unix Timestamp)
            genre TEXT,
            tags TEXT,
            hltb_main INTEGER,
            hltb_completionist INTEGER,
            is_multiplayer INTEGER DEFAULT 0, -- <--- NEEDS TO BE POPULATED
            last_updated REAL
        )''')
        conn.commit()





def update(username):
    """
    Updates or inserts inside the local database
    """
    print("--- OPENING THE VAULT ---")

    # Initialize DB just in case
    init_db()

    MP_TAGS = {
        "multiplayer", "co-op", "online co-op", "coop",
        "local co-op", "online pvp", "pvp", "mmo",
        "massively multiplayer", "cross-platform multiplayer"
    }

    steam = Steam(config.STEAM_API_KEY)
    user_data = steam.users.search_user(username)
    steam_id = user_data['player']['steamid']
    owned_games = steam.users.get_owned_games(steam_id, True, False)['games']

    print(f"Found {len(owned_games)} games. Checking for missing intel...")

    # Open connection for the duration of the update
    with get_connection() as conn:
        c = conn.cursor()

        for game in owned_games:
            appid = game['appid']
            name = game['name']
            playtime = game['playtime_forever']
            last_played = game.get('rtime_last_played', 0)

            main_story = 0
            completionist = 0
            is_multiplayer = 0


            # Check cache
            c.execute("SELECT last_updated FROM games WHERE appid=?", (appid,))
            row = c.fetchone()

            # Fast Path: Update playtime and move on
            if row:
                c.execute("UPDATE games SET playtime_forever=? WHERE appid=?", (playtime, appid))
                conn.commit()
                continue

            # Slow Path: New Game
            print(f"New recruit detected: {name} ({appid})")

            tags_str = ""
            try:
                # Use the LOCAL function, not the one from 'br'
                tags_list = get_realtime_tags(appid)
                tags_str = ",".join(tags_list)

                time.sleep(1)
            except:
                pass

            if tags_str:
                # Convert string "Action, Indie" -> set("action", "indie")
                current_tags = {t.strip().lower() for t in tags_str.split(',')}

                # Check for intersection
                if not current_tags.isdisjoint(MP_TAGS):
                    is_multiplayer = 1

            try:
                # HLTB is slow, maybe wrap this in a try/catch block for connection errors
                hltb_results = HowLongToBeat().search(name)
                if hltb_results:
                    best_match = max(hltb_results, key=lambda x: x.similarity)
                    main_story = best_match.main_story
                    completionist = best_match.completionist
            except Exception as e:
                print(f"HLTB failed: {e}")

            c.execute('''INSERT OR REPLACE INTO games VALUES (?,?,?,?,?,?,?,?,?,?)''',
                      (appid, name, playtime, last_played, "", tags_str, main_story, completionist, is_multiplayer, time.time()))
            conn.commit()


    print("Vault update complete.")


def get_games_count():
    try:
        # If the DB file doesn't exist, SQLite usually creates it automatically here,
        # but it will be empty (no tables).
        with get_connection() as conn:
            c = conn.cursor()

            # This will raise an OperationalError if the 'games' table is missing
            c.execute("SELECT count(0) AS 'c' FROM games")

            rows = c.fetchall()
            if rows:
                return dict(rows[0])['c']
            else:
                return 0

    except sqlite3.OperationalError:
        # This catches errors like "no such table: games"
        return 0

    except Exception as e:
        # Catch connection errors if the DB server is down or unreachable
        print(f"An unexpected error occurred: {e}")
        return 0


def get_all_games():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM games ORDER BY playtime_forever DESC")
        rows = c.fetchall()
        # Convert to list of dicts immediately to avoid threading issues with Row objects later
        return [dict(row) for row in rows]


def get_all_tags():
    """
    Returns a sorted list of unique tags found in the user's library.
    """
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT tags FROM games")
        rows = c.fetchall()

    unique_tags = set()
    for row in rows:
        if row['tags']:
            # Split "Action, Indie, RPG" -> ["Action", "Indie", "RPG"]
            tags = [t.strip() for t in row['tags'].split(',')]
            unique_tags.update(tags)

    return sorted(list(unique_tags))


def advanced_search(tags=None, exclude_tags=None, min_playtime=None, max_playtime=None, hltb_max=None, status=None, sort_by='shortest'):
    """
    Filters the vault based on criteria.
    """
    if tags is None: tags = []
    if exclude_tags is None: exclude_tags = []
    if status is None: status = []

    # Normalize inputs for matching
    req_tags = {t.lower() for t in tags}
    ex_tags = {t.lower() for t in exclude_tags}
    req_status = {s.lower() for s in status}

    # The AI often sends 0 when it means "unlimited" or "don't care".
    # We must convert 0 to None so the logic below skips the check.
    if min_playtime == 0: min_playtime = None
    if max_playtime == 0: max_playtime = None
    if hltb_max == 0: hltb_max = None

    # Fetch ALL games (It's 2000 rows, Python eats this for breakfast)
    # We fetch all because Python string processing is more robust than SQLite 'LIKE'
    all_games = get_all_games()

    results = []

    for game in all_games:
        # 1. STATUS FILTER (Computed on the fly)
        game_status = calculate_status(game)

        if req_status and game_status.lower() not in req_status:
            continue

        # 2. TAGS FILTER
        game_tags = {t.strip().lower() for t in (game['tags'] or "").split(',')}

        # Check Excludes (Critical)
        if not ex_tags.isdisjoint(game_tags):
            continue

        # Check Includes
        #if req_tags and not req_tags.issubset(game_tags):
        #    continue
        if len(req_tags) and len(req_tags.difference(game_tags)) == len(req_tags): # if it has no requested tags then skip
            continue

        # 3. PLAYTIME FILTER (in Minutes)
        pt = game['playtime_forever']
        if min_playtime is not None and pt < min_playtime: continue
        if max_playtime is not None and pt > max_playtime: continue

        # 4. HLTB FILTER (in Hours)
        main_story = game['hltb_main'] or 0
        if hltb_max is not None:
            if main_story == 0: continue  # Skip games with no data if searching by length
            if main_story > hltb_max: continue

        # If we survived all filters, add to results
        # Inject the calculated status so the AI sees it
        game['calculated_status'] = game_status
        results.append(game)

    # Final Sorting
    if sort_by == 'shortest':
        results.sort(key=lambda x: x['hltb_main'] if x['hltb_main'] > 0 else 999)
    elif sort_by == 'longest':
        results.sort(key=lambda x: x['hltb_main'], reverse=True)
    elif sort_by == 'name':
        results.sort(key=lambda x: x['name'])
    elif sort_by == 'random':
        random.shuffle(results)

    return results