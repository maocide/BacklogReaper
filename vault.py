import concurrent
import sqlite3
import random
import difflib

import requests
from steam_web_api import Steam
import settings
from web_tools import get_store_data
from web_tools import get_hltb_data

# Config
DB_NAME = 'backlog_vault.db'

import time
from datetime import datetime

last_refreshed = 0

def calculate_status(game):
    """
    Classifies the game state using Playtime, HLTB, Recency, and Tags.
    Returns a single string label.

    Hierarchy:
    1. Unplayed (< 10m)
    2. Completionist / Invested (> 100% Story)
    3. Bounced / Testing (< 2h)
    4. Seasoned / Forgotten (50-100% Story)
    5. Started / Abandoned (10-50% Story)
    6. Hooked / Mastered (Multiplayer/Endless)
    7. Played (Fallback)
    """
    playtime_min = game.get('playtime_forever', 0)
    last_played_ts = game.get('rtime_last_played', 0)
    hltb_main = game.get('hltb_main', 0)

    # Safely get tags
    tags_raw = game.get('tags', '')
    tags = tags_raw.lower() if tags_raw else ""

    is_multiplayer_db = game.get('is_multiplayer', 0)

    # Derived Metrics
    playtime_hrs = playtime_min / 60.0

    # Days since last launch
    days_since_played = (time.time() - last_played_ts) / 86400 if last_played_ts > 0 else 9999

    # 1. UNPLAYED
    # Increased threshold to 10 minutes as requested
    if playtime_min < 10:
        return "Unplayed"

    # Ratio Calculation (Playtime / Main Story)
    ratio = 0
    if hltb_main > 0:
        # Both are now in minutes
        ratio = playtime_min / hltb_main

    # 2. FINISHED / COMPLETIONIST (Overrides "Bounced" for short games)
    if hltb_main > 0:
        if ratio > 1.3:
            return "Completionist"
        if ratio >= 1.0:
            return "Invested"

    # 3. EARLY GAME (Bounced vs Testing)
    # If played less than 2 hours (and didn't finish it per above)
    if playtime_min < 120:
        if days_since_played > 14:
            return "Bounced"
        return "Testing"  # Recent purchase/install

    # 4. MID-GAME (Story Progress)
    if hltb_main > 0:
        # 50% - 100%
        if ratio >= 0.5:
            if days_since_played < 60:
                return "Seasoned"
            else:
                return "Forgotten"

        # 10% - 50%
        if ratio > 0.1:
            if days_since_played < 60:
                return "Started"
            else:
                return "Abandoned"

    # 5. MULTIPLAYER / ENDLESS
    # Check DB flag OR keywords
    is_mp_tag = "multiplayer" in tags or "mmo" in tags or "co-op" in tags or "online" in tags

    # If it's multiplayer OR just played a ton (> 50h)
    if is_multiplayer_db or is_mp_tag or playtime_hrs > 50:
        if days_since_played < 30:
            return "Hooked"
        else:
            return "Mastered"

    # 6. FALLBACK
    return "Played"

def calculate_simple_status(game):
    """
    Returns a simplified status group for Charting (5 groups).
    """
    detailed = calculate_status(game)

    mapping = {
        "Unplayed": "Backlog",

        "Testing": "Trying",
        "Bounced": "Trying",

        "Started": "Active",
        "Seasoned": "Active",
        "Hooked": "Active",

        "Invested": "Finished",
        "Completionist": "Finished",
        "Played": "Finished",

        "Abandoned": "Shelved",
        "Forgotten": "Shelved",
        "Mastered": "Shelved"
    }

    return mapping.get(detailed, "Played")

def format_time_ago(ts):
    if ts == 0: return "Never"
    days = int((time.time() - ts) / 86400)
    if days == 0: return  datetime.fromtimestamp(ts).strftime('Today %H:%M')
    if days < 30: return f"{days} days ago"
    if days < 365: return f"{int(days/30)} months ago"
    return f"{int(days/365)} years ago"




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
            tags TEXT,
            description TEXT,
            hltb_main INTEGER,
            hltb_completionist INTEGER,
            is_multiplayer INTEGER DEFAULT 0,
            last_updated REAL,
            review_score INTEGER DEFAULT -1
        )''')
        conn.commit()


def fetch_game_details_worker(game):
    """
    Worker function to fetch external data for a SINGLE game.
    Executed in parallel threads.
    """
    appid = game['appid']
    name = game['name']

    # Defensive sleep to be polite to APIs inside threads
    time.sleep(0.3)

    print(f"Fetching intel for: {name} ({appid})")

    # 1. Init Data
    main_story = 0
    completionist = 0
    is_multiplayer = 0
    tags_str = ""
    description = ""
    review_score = -1

    MP_TAGS = {
        "multiplayer", "co-op", "online co-op", "coop",
        "local co-op", "online pvp", "pvp", "mmo",
        "massively multiplayer", "cross-platform multiplayer"
    }

    # 2. Fetch Store Data (Tags & Description)
    try:
        store_data = get_store_data(appid)
        description = store_data.get('description', '')
        tags_list = store_data.get('tags', [])
        tags_str = ",".join(tags_list)

        # Check Multiplayer Tags
        current_tags = {t.strip().lower() for t in tags_list}
        if not current_tags.isdisjoint(MP_TAGS):
            is_multiplayer = 1

    except Exception as e:
        print(f"Store scrape failed for {name}: {e}")

    # 3. Fetch Reviews
    try:
        review_score = fetch_review_summary(appid)
    except Exception as e:
        print(f"Review fetch failed for {name}: {e}")

    # 4. Fetch HLTB
    try:
        hltb_results = get_hltb_data(name)
        if hltb_results:
            best_match = max(hltb_results, key=lambda x: x.similarity)
            # Store as MINUTES (Integer)
            main_story = int(best_match.main_story * 60)
            completionist = int(best_match.completionist * 60)
    except Exception as e:
        print(f"HLTB failed for {name}: {e}")

    # Return a tuple formatted for the SQL INSERT
    # (appid, name, playtime, last_played, tags, desc, main, comp, is_mp, last_updated, score)
    return (
        appid,
        name,
        game['playtime_forever'],
        game.get('rtime_last_played', 0),
        tags_str,
        description,
        main_story,
        completionist,
        is_multiplayer,
        time.time(),
        review_score
    )

def update(username):
    """
    Optimized Update:
    1. Batch updates existing games (Playtime/LastPlayed).
    2. Parallel fetches new games.
    """
    print("--- OPENING THE VAULT (OPTIMIZED) ---")
    init_db()

    steam = Steam(settings.STEAM_API_KEY)
    user_data = steam.users.search_user(username)
    steam_id = user_data['player']['steamid']
    owned_games = steam.users.get_owned_games(steam_id, True, False)['games']

    print(f"Library Scan: Found {len(owned_games)} games.")

    # --- STEP 1: SEGREGATE GAMES ---
    existing_games = []  # Tuple list for batch update
    new_games = []  # List of dicts for parallel processing

    with get_connection() as conn:
        c = conn.cursor()
        # Get all existing AppIDs in one fast query
        c.execute("SELECT appid FROM games")
        known_appids = {row['appid'] for row in c.fetchall()}

    for game in owned_games:
        appid = game['appid']
        if appid in known_appids:
            # Prepare data for FAST update
            # SQL: UPDATE games SET playtime_forever=?, rtime_last_played=? WHERE appid=?
            # Data must be (playtime, last_played, appid)
            existing_games.append((
                game['playtime_forever'],
                game.get('rtime_last_played', 0),
                appid
            ))
        else:
            new_games.append(game)

    # --- STEP 2: FAST BATCH UPDATE (Existing Games) ---
    if existing_games:
        print(f"Syncing playtime for {len(existing_games)} known games...")
        with get_connection() as conn:
            c = conn.cursor()
            c.executemany(
                "UPDATE games SET playtime_forever=?, rtime_last_played=? WHERE appid=?",
                existing_games
            )
            conn.commit()

    # --- STEP 3: PARALLEL PROCESSING (New Games) ---
    if not new_games:
        print("No new recruits found.")
    else:
        print(f"Found {len(new_games)} NEW games. Deploying scrapers...")

        new_game_data = []

        # We use a ThreadPool to run multiple scrapers at once.

        worker_count = 2 if len(new_games) > 10 else 4
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            # Submit all tasks
            future_to_game = {executor.submit(fetch_game_details_worker, game): game for game in new_games}

            for i, future in enumerate(concurrent.futures.as_completed(future_to_game)):
                try:
                    data = future.result()
                    new_game_data.append(data)
                    print(f"[{i + 1}/{len(new_games)}] Processed {data[1]}")
                except Exception as exc:
                    print(f"Worker generated an exception: {exc}")

        # --- STEP 4: BATCH INSERT (New Games) ---
        if new_game_data:
            print(f"Saving {len(new_game_data)} new records to Vault...")
            with get_connection() as conn:
                c = conn.cursor()
                c.executemany(
                    '''INSERT OR REPLACE INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    new_game_data
                )
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
        games = [dict(row) for row in rows]

        # Inject hltb_hours for all games
        for game in games:
            game['hltb_hours'] = round(float(game['hltb_main']) / 60.0, 1) if game['hltb_main'] else 0

        return games

def get_game_by_appid(appid):
    """
    Efficiently retrieves a single game by AppID.
    Returns dict or None.
    """
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM games WHERE appid=?", (appid,))
        row = c.fetchone()
        if row:
            game = dict(row)
            # Inject hltb_hours
            game['hltb_hours'] = round(float(game['hltb_main']) / 60.0, 1) if game['hltb_main'] else 0
            return game
    return None

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
        if min_playtime is not None and pt < min_playtime * 60: continue
        if max_playtime is not None and pt > max_playtime * 60: continue

        # HLTB FILTER (Input is Hours, DB is Minutes)
        main_story = game['hltb_main'] or 0
        if hltb_max is not None:
            # Skip 0 because 0 usually means "unknown," not "0 minutes long"
            if main_story == 0 or main_story > hltb_max * 60:
                continue

        # REVIEW SCORE FILTER
        if min_review_score is not None:
             score = game.get('review_score', -1)
             if score != -1 and score < min_review_score:
                 continue

        # If we survived all filters, add to results
        # Inject the calculated fields so the AI sees them
        game['calculated_status'] = game_status
        game['hours'] = round(float(game['playtime_forever']) / 60.0, 1)
        game['hltb_hours'] = round(float(game['hltb_main']) / 60.0, 1) if game['hltb_main'] else 0
        game['last_played'] = last_played_str

        results.append(game)

    # Final Sorting
    if sort_by == 'shortest':
        results.sort(key=lambda x: x['hltb_main'] if x['hltb_main'] > 0 else float('inf')) # Makes the unknown 0 data go at the bottom with Infinity
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


def get_vault_statistics():
    """
    Aggregates library data for the Dashboard Charts.
    Returns a dictionary with:
    - status_counts: {'Unplayed': 50, 'Finished': 12...}
    - genre_counts: [{'tag': 'RPG', 'count': 40}, ...]
    - total_games: 120
    - total_hours: 5000
    - backlog_hours: 2000 (Sum of HLTB for unplayed games)
    """
    stats = {
        "status_counts": {},
        "genre_counts": [],
        "genre_hours": [],
        "total_games": 0,
        "total_hours": 0,
        "backlog_hours": 0
    }

    try:
        games = get_all_games()
    except Exception:
        # DB might not exist or be empty
        return stats

    if not games:
        return stats

    stats["total_games"] = len(games)

    tag_tally = {}
    tag_hours_tally = {}

    for game in games:
        # Calculate status dynamically
        status = calculate_status(game)
        simple_status = calculate_simple_status(game) # Use simplified for chart

        playtime = game.get('playtime_forever', 0)
        hltb = game.get('hltb_main', 0)
        tags_str = game.get('tags', '')

        # Aggregate Status (Use Simple!)
        stats["status_counts"][simple_status] = stats["status_counts"].get(simple_status, 0) + 1

        # Aggregate Totals
        stats["total_hours"] += playtime

        # Backlog Debt: Sum of HLTB for 'Unplayed' games
        # Also 'Bounced' might technically be backlog, but strictly 'Unplayed' is safer definition
        if status == "Unplayed":
            stats["backlog_hours"] += hltb

        # Aggregate Genres (First Tag)
        if tags_str:
            primary_tag = tags_str.split(',')[0].strip()
            tag_tally[primary_tag] = tag_tally.get(primary_tag, 0) + 1
            tag_hours_tally[primary_tag] = tag_hours_tally.get(primary_tag, 0) + playtime

    # Convert minutes to hours
    stats["total_hours"] = int(stats["total_hours"] / 60)
    stats["backlog_hours"] = int(stats["backlog_hours"] / 60)

    # Sort Genres and take Top 10 by COUNT
    sorted_tags = sorted(tag_tally.items(), key=lambda x: x[1], reverse=True)[:10]
    stats["genre_counts"] = [{"tag": k, "count": v} for k, v in sorted_tags]

    # Sort Genres and take Top 10 by HOURS
    sorted_tags_hours = sorted(tag_hours_tally.items(), key=lambda x: x[1], reverse=True)[:10]
    stats["genre_hours"] = [{"tag": k, "count": int(v / 60)} for k, v in sorted_tags_hours]

    return stats

def get_library_stats():
    """
    Returns aggregated stats for the User's library to facilitate a 'Roast' or 'Audit'.
    Includes:
    - total_games
    - unplayed_count (Status: Unplayed)
    - bounced_count (Status: Bounced)
    - shame_percentage ((Unplayed + Bounced) / Total * 100)
    - total_hours
    - completion_rate ((Invested + Completionist) / Total * 100)
    - top_played_genres (Top 5 by hours)
    - top_owned_genres (Top 5 by count)
    """
    try:
        games = get_all_games()
    except Exception:
        return {"total_games": 0, "error": "Could not access vault."}

    total_games = len(games)
    if total_games == 0:
        return {"total_games": 0, "error": "Library is empty."}

    unplayed_count = 0
    bounced_count = 0
    finished_count = 0
    total_minutes = 0

    tag_counts = {}
    tag_minutes = {}

    for game in games:
        status = calculate_status(game)
        playtime = game.get('playtime_forever', 0)
        tags_str = game.get('tags', '')

        # Global totals
        total_minutes += playtime

        # Status Counts
        if status == "Unplayed":
            unplayed_count += 1
        elif status == "Bounced":
            bounced_count += 1
        elif status in ("Invested", "Completionist"):
            finished_count += 1

        # Genre Analysis (Split all tags)
        if tags_str:
            tags = [t.strip() for t in tags_str.split(',')]
            for tag in tags:
                if not tag: continue
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
                tag_minutes[tag] = tag_minutes.get(tag, 0) + playtime

    # Derived Metrics
    # Shame = Unplayed + Bounced
    shame_percentage = int(((unplayed_count + bounced_count) / total_games) * 100)
    completion_rate = int((finished_count / total_games) * 100)
    total_hours = int(total_minutes / 60)
    avg_playtime_hours = round(total_hours / total_games, 1)

    # Top Genres
    top_played = sorted(tag_minutes.items(), key=lambda x: x[1], reverse=True)[:5]
    top_played_fmt = [{"tag": k, "hours": int(v/60)} for k, v in top_played]

    top_owned = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_owned_fmt = [{"tag": k, "count": v} for k, v in top_owned]

    return {
        "total_games": total_games,
        "unplayed_count": unplayed_count,
        "bounced_count": bounced_count,
        "shame_percentage": f"{shame_percentage}%",
        "total_hours": total_hours,
        "avg_playtime_hours": avg_playtime_hours,
        "completion_rate": f"{completion_rate}%",
        "top_played_genres": top_played_fmt,
        "top_owned_genres": top_owned_fmt
    }

if __name__ == "__main__":
    pass
    print(get_vault_statistics())
    #hltb_test = get_hltb_search_scrape("Lossless Scaling")
    #print(hltb_test)
    # import vibe_engine
    # vibes = vibe_engine.VibeEngine.get_instance()
    # print(vibes.search("gloomy"))
