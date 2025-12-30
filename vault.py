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
    Run this once on app startup to ensure the vault exists.
    """
    with get_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS games (
            appid INTEGER PRIMARY KEY,
            name TEXT,
            playtime_forever INTEGER,
            genre TEXT,
            tags TEXT,
            hltb_main INTEGER,
            hltb_completionist INTEGER,
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
    print("--- OPENING THE VAULT ---")

    # Initialize DB just in case
    init_db()

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
            except:
                pass

            main_story = 0
            completionist = 0
            try:
                # HLTB is slow, maybe wrap this in a try/catch block for connection errors
                hltb_results = HowLongToBeat().search(name)
                if hltb_results:
                    best_match = max(hltb_results, key=lambda x: x.similarity)
                    main_story = best_match.main_story
                    completionist = best_match.completionist
            except Exception as e:
                print(f"HLTB failed: {e}")

            c.execute('''INSERT OR REPLACE INTO games VALUES (?,?,?,?,?,?,?,?)''',
                      (appid, name, playtime, "", tags_str, main_story, completionist, time.time()))
            conn.commit()

            time.sleep(1)  # Be nice to Valve (they don't deserve it)

    print("Vault update complete.")

def get_games_count():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT count(0) AS 'c' FROM games ORDER BY playtime_forever DESC")
        rows = c.fetchall()
        if rows:
            return dict(rows[0])['c']
        else:
            return 0


def get_all_games():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM games ORDER BY playtime_forever DESC")
        rows = c.fetchall()
        # Convert to list of dicts immediately to avoid threading issues with Row objects later
        return [dict(row) for row in rows]