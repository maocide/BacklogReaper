import sqlite3
import time
import requests
from bs4 import BeautifulSoup
from steam_web_api import Steam
import config
from howlongtobeatpy import HowLongToBeat

# Config
DB_NAME = 'backlog_vault.db'


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


# MOVED FROM BACKLOGREAPER TO FIX CIRCULAR IMPORTS
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