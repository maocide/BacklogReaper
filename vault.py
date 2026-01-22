import sqlite3
import time
import random
import difflib

import requests
from bs4 import BeautifulSoup
from steam_web_api import Steam
import config
from howlongtobeatpy import HowLongToBeat

# Config
DB_NAME = 'backlog_vault.db'

import time
from datetime import datetime


last_refreshed = 0

def calculate_status(game):
    """
    Classifies the game state using Playtime, HLTB, Recency, and Tags.
    Returns a single string label.
    """
    playtime_min = game.get('playtime_forever', 0)
    last_played_ts = game.get('rtime_last_played', 0)
    hltb_main = game.get('hltb_main', 0)
    hltb_comp = game.get('hltb_completionist', 0)
    tags = game.get('tags', '').lower()

    # Derived Metrics
    playtime_hrs = playtime_min / 60.0

    # Days since last launch (86400 seconds = 1 day)
    # If last_played is 0, treat as ancient history (9999 days)
    days_since_played = (time.time() - last_played_ts) / 86400 if last_played_ts > 0 else 9999

    # THE "GHOST" (Pure Backlog)
    if playtime_min < 1:
        return "Unplayed"

    # THE "TOURIST" (Bought, tried, quit immediately)
    # Played less than 2 hours...
    if playtime_min < 120:
        # ...and hasn't touched it in 2 weeks.
        if days_since_played > 14:
            return "Bounced"
        return "Testing"  # Recently bought/installed

    # THE "ADDICT" (Multiplayer / Endless)
    # Logic: If it's a multiplayer game with significant hours,
    # OR if you've played 3x the completionist time.
    is_multiplayer = "multiplayer" in tags or "mmo" in tags or "co-op" in tags

    if (is_multiplayer and playtime_hrs > 50) or (hltb_comp > 0 and playtime_hrs > hltb_comp * 3):
        return "Addicted"

    # HLTB PROGRESS LOGIC
    if hltb_main > 0:
        ratio = playtime_hrs / hltb_main

        # > 80% of Main Story length -> Likely Finished
        if ratio >= 0.8:
            return "Finished"

        # 10% to 80% -> In Progress
        if ratio > 0.1:
            # The Critical Distinction: Active vs Abandoned
            if days_since_played < 60:
                return "Active"  # Playing it this month/recently
            else:
                return "Abandoned"  # Stopped midway ages ago

    # FALLBACK (No HLTB Data)
    # We can only judge by recency if we don't know how long the game is
    if days_since_played < 30: return "Active"

    return "Played"

def format_time_ago(ts):
    if ts == 0: return "Never"
    days = int((time.time() - ts) / 86400)
    if days == 0: return  datetime.fromtimestamp(ts).strftime('Today %H:%M')
    if days < 30: return f"{days} days ago"
    if days < 365: return f"{int(days/30)} months ago"
    return f"{int(days/365)} years ago"


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


def fetch_review_summary(appid):
    """
    Fetches review summary from Steam Store API to calculate a score percentage.
    Returns: Integer 0-100 or -1 if unavailable.
    """
    url = f"https://store.steampowered.com/appreviews/{appid}?json=1&num_per_page=0&purchase_type=all"
    try:
        # No sleep needed for Store API usually, but be mindful if loop is tight.
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            summary = data.get('query_summary', {})
            total_positive = summary.get('total_positive', 0)
            total_negative = summary.get('total_negative', 0)
            total = total_positive + total_negative
            if total > 0:
                # Calculate percentage
                return int((total_positive / total) * 100)
    except Exception as e:
        print(f"Error fetching reviews for {appid}: {e}")

    return -1


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
            last_updated REAL,
            review_score INTEGER DEFAULT -1
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
                c.execute("UPDATE games SET playtime_forever=?, rtime_last_played=? WHERE appid=?", (playtime, last_played, appid))
                conn.commit()
                continue

            # Slow Path: New Game
            print(f"New recruit detected: {name} ({appid})")

            # Fetch Review Score
            review_score = fetch_review_summary(appid)

            tags_str = ""
            try:
                # Use the LOCAL function, not the one from 'br'
                tags_list = get_realtime_tags(appid)
                tags_str = ",".join(tags_list)

                time.sleep(0.25)
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

            c.execute('''INSERT OR REPLACE INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                      (appid, name, playtime, last_played, "", tags_str, main_story, completionist, is_multiplayer, time.time(), review_score))
            conn.commit()

    global last_refreshed
    last_refreshed = time.time()

    print("Vault update complete.")

def get_elapsed_since_update():
    return time.time() - last_refreshed

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


def get_all_tags(limit=None):
    """
    Returns a list of tags in the user's library with stats.
    Used by the Agent to know what genres are available to search.
    """
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT tags, playtime_forever FROM games")
        rows = c.fetchall()

    stats = {}

    for row in rows:
        if not row['tags']: continue

        # Split tags and clean whitespace
        current_tags = [t.strip() for t in row['tags'].split(',')]
        playtime_mins = row['playtime_forever'] or 0

        for tag in current_tags:
            if tag not in stats:
                stats[tag] = {'count': 0, 'minutes': 0}

            stats[tag]['count'] += 1
            stats[tag]['minutes'] += playtime_mins

    # Format for the Agent
    results = []
    for tag, data in stats.items():
        results.append({
            "name": tag,  # "name" is intuitive for the search parameter
            "owned": data['count'],
            "total_hours": round(data['minutes'] / 60, 1)
        })

    # Sort by 'owned' count so the most relevant genres appear first
    results.sort(key=lambda x: x['owned'], reverse=True)

    # If the list is huge (e.g. 300 tags), maybe slice it if no limit was requested to save tokens?
    # But usually, providing all allows the agent to find niche tags.
    if limit:
        return results[:limit]

    return results

def is_game_owned(appid):
    """
    Returns True if the game is currently owned by the user's library.
    """
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT appid FROM games WHERE appid=?", (appid,))
        rows = c.fetchall()

    if rows:
        return True
    else:
        return False


def advanced_search(tags=None, exclude_tags=None, min_playtime=None, max_playtime=None, hltb_max=None, status=None, min_review_score=None, name=None, sort_by='shortest', page=0, page_size=10, seed=None):
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
    if min_review_score == 0: min_review_score = None

    # Fetch ALL games (It's 2000 rows, Python eats this for breakfast)
    # We fetch all because Python string processing is more robust than SQLite 'LIKE'
    all_games = get_all_games()

    results = []

    for game in all_games:
        # STATUS FILTER (Computed on the fly)
        game_status = calculate_status(game)
        last_played_str = format_time_ago(game.get('rtime_last_played', 0))

        if req_status and game_status.lower() not in req_status:
            continue

        # NAME FILTER (Fuzzy Match)
        if name:
             game_name_lower = game['name'].lower()
             target_name_lower = name.lower()

             # Check for substring match
             is_substring = target_name_lower in game_name_lower

             # Check for fuzzy match using difflib
             similarity = difflib.SequenceMatcher(None, target_name_lower, game_name_lower).ratio()
             is_fuzzy = similarity > 0.6

             if not (is_substring or is_fuzzy):
                 continue

        # TAGS FILTER
        game_tags = {t.strip().lower() for t in (game['tags'] or "").split(',')}

        # Check Excludes (Critical)
        if not ex_tags.isdisjoint(game_tags):
            continue

        # Check Includes
        #if req_tags and not req_tags.issubset(game_tags):
        #    continue
        if len(req_tags) and len(req_tags.difference(game_tags)) == len(req_tags): # if it has no requested tags then skip
            continue

        # PLAYTIME FILTER (in Minutes)
        pt = game['playtime_forever']
        if min_playtime is not None and pt < min_playtime: continue
        if max_playtime is not None and pt > max_playtime: continue

        # HLTB FILTER (in Hours)
        main_story = game['hltb_main'] or 0
        if hltb_max is not None:
            if main_story == 0: continue  # Skip games with no data if searching by length
            if main_story > hltb_max: continue

        # REVIEW SCORE FILTER
        if min_review_score is not None:
             score = game.get('review_score', -1)
             if score != -1 and score < min_review_score:
                 continue

        # If we survived all filters, add to results
        # Inject the calculated fields so the AI sees them
        game['calculated_status'] = game_status
        game['hours'] = round(float(game['playtime_forever']) / 60.0, 1)
        game['last_played'] = last_played_str

        results.append(game)

    # Final Sorting
    if sort_by == 'shortest':
        results.sort(key=lambda x: x['hltb_main'] if x['hltb_main'] > 0 else 999)
    elif sort_by == 'longest':
        results.sort(key=lambda x: x['hltb_main'], reverse=True)
    elif sort_by == 'name':
        results.sort(key=lambda x: x['name'])
    elif sort_by == 'recent':
        results.sort(key=lambda x: x['rtime_last_played'], reverse=True)
    elif sort_by == 'review_score':
        results.sort(key=lambda x: x['review_score'], reverse=True)
    elif sort_by == 'random':
        if seed is not None:
             random.Random(seed).shuffle(results)
        else:
             random.shuffle(results)

    # Slice for pagination
    if page_size > 0:
        start_idx = page * page_size
        end_idx = start_idx + page_size
        results = results[start_idx:end_idx]

    return results

def vault_search_batch(game_names: list[str]):
    # Create a dynamic SQL query
    results = []

    for name in game_names:
        game_result = advanced_search(name=name)
        results = results + game_result

    return results