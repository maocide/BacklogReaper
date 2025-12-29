import sqlite3
import time
import requests
from steam_web_api import Steam
import config
import BacklogReaper as br
from howlongtobeatpy import HowLongToBeat

# Connect to (or create) the local brain
conn = sqlite3.connect('backlog_vault.db')
c = conn.cursor()

# Create the master table if it doesn't exist
# We store EVERYTHING here so we never have to ask the internet again
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


def update_vault(username):
    print("--- OPENING THE VAULT ---")
    steam = Steam(config.STEAM_API_KEY)
    user_data = steam.users.search_user(username)
    steam_id = user_data['player']['steamid']

    # 1. Get the raw list (Fast)
    owned_games = steam.users.get_owned_games(steam_id, True, False)['games']

    print(f"Found {len(owned_games)} games. Checking for missing intel...")

    for game in owned_games:
        appid = game['appid']
        name = game['name']
        playtime = game['playtime_forever']

        # Check if we already have this game cached
        c.execute("SELECT last_updated FROM games WHERE appid=?", (appid,))
        row = c.fetchone()

        # If cached, just update playtime (fast)
        if row:
            c.execute("UPDATE games SET playtime_forever=? WHERE appid=?", (playtime, appid))
            conn.commit()
            continue  # SKIP the heavy API calls!

        # --- SLOW ZONE: New Game Detected ---
        print(f"New recruit detected: {name}. Interrogating APIs...")

        # Fetch Tags/Genre (SteamSpy or Store API)
        # Note: You can throttle this to 1 request per second to be safe
        tags_str = ""
        genre_str = ""
        try:
            # Your existing tag fetching logic here
            # tags_list = get_realtime_tags(appid)
            tags_list = br.get_realtime_tags(appid)
            tags_str = ",".join(tags_list)
        except:
            print(f"Failed to get tags for {name}")

        # Fetch HLTB (The slowest part)
        main_story = 0
        completionist = 0
        try:
            hltb_results = HowLongToBeat().search(name)
            if hltb_results:
                best_match = max(hltb_results, key=lambda x: x.similarity)
                main_story = best_match.main_story
                completionist = best_match.completionist
        except Exception as e:
            print(f"HLTB failed for {name}: {e}")

        # INSERT into Vault
        c.execute('''INSERT OR REPLACE INTO games VALUES (?,?,?,?,?,?,?,?)''',
                  (appid, name, playtime, genre_str, tags_str, main_story, completionist, time.time()))
        conn.commit()

        # RESPECT THE RATE LIMITS OR DIE
        time.sleep(1)

    print("Vault update complete.")


if __name__ == "__main__":
    pass
    #update_vault(config.STEAM_USER)