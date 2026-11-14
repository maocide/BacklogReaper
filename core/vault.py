import concurrent
import sqlite3
import random
import difflib
from pprint import pprint

import requests
from steam_web_api import Steam

import core.ai_tools as ai_tools
import core.settings as settings
import core.text_utils as text_utils
from core.web_tools import get_store_data
from core.web_tools import get_hltb_data
import core.paths as paths

DB_NAME = str(paths.get_base_dir() / "backlog_vault.db")

import time
from datetime import datetime

# Ignore noise
IGNORED_TAGS = {
    "Software", "Utilities", "Design & Illustration", "Web Publishing",
    "Animation & Modeling", "Video Production", "Audio Production",
    "Education", "Game Development", "Benchmark", "Movie", "Documentary",
    "360 Video", "Short", "Tutorial",
    "Singleplayer", "Multiplayer", "Indie",
}

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

    # UNPLAYED
    # Increased threshold to 10 minutes as requested
    if playtime_min < 10:
        return "Unplayed"

    # Ratio Calculation (Playtime / Main Story)
    ratio = 0
    # Ensure hltb_main is treated as 0 if None
    if hltb_main is None: hltb_main = 0

    if hltb_main > 0:
        # Both are now in minutes
        ratio = playtime_min / hltb_main

    # FINISHED / COMPLETIONIST (Overrides "Bounced" for short games)
    if hltb_main > 0:
        if ratio > 1.3:
            return "Completionist"
        if ratio >= 1.0:
            return "Invested"

    # EARLY GAME (Bounced vs Testing)
    # If played less than 2 hours (and didn't finish it per above)
    if playtime_min < 120:
        if days_since_played > 14:
            return "Bounced"
        return "Testing"  # Recent purchase/install

    # MID-GAME (Story Progress)
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

    # MULTIPLAYER / ENDLESS
    # Check DB flag OR keywords
    is_mp_tag = "multiplayer" in tags or "mmo" in tags or "co-op" in tags or "online" in tags

    # If it's multiplayer OR just played a ton (> 50h)
    if is_multiplayer_db or is_mp_tag or playtime_hrs > 50:
        if days_since_played < 30:
            return "Hooked"
        else:
            return "Mastered"

    # FALLBACK
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
    # days = int((time.time() - ts) / 86400)
    # if days == 0: return  datetime.fromtimestamp(ts).strftime('Today %H:%M')
    # if days < 30: return f"{days} days ago"
    # if days < 365: return f"{int(days/30)} months ago"
    # return f"{int(days/365)} years ago"

    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')




def fetch_review_summary(appid):
    """
    Fetches review summary from Steam Store API to calculate a score percentage.
    Returns: Integer 0-100 or -1 if unavailable.
    """
    url = f"https://store.steampowered.com/appreviews/{appid}?json=1&num_per_page=0&purchase_type=all"
    try:
        # No sleep needed for Store API usually, but be mindful if loop is tight
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
    paths.ensure_dirs()  # Ensure directory exists before creating DB
    conn = sqlite3.connect(DB_NAME, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # Allows dict-like access (row['name'])
    return conn


def init_db():
    """
    Creates local sql lite db and enables WAL mode for high-concurrency read/write.
    """
    with get_connection() as conn:
        c = conn.cursor()
        c.execute('PRAGMA journal_mode=WAL;')
        c.execute('PRAGMA busy_timeout=30000;')
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

    # Fetch Store Data (Tags & Description)
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

    # Fetch Reviews
    try:
        review_score = fetch_review_summary(appid)
    except Exception as e:
        print(f"Review fetch failed for {name}: {e}")

    # Fetch HLTB
    try:
        hltb_results = get_hltb_data(name)
        if hltb_results:
            best_match = max(hltb_results, key=lambda x: x.similarity)
            # Store as MINUTES (Integer)
            story_hours = getattr(best_match, 'main_story', 0) or getattr(best_match, 'main_extra', 0) or getattr(best_match, 'completionist', 0) or 0
            comp_hours = getattr(best_match, 'completionist', 0) or getattr(best_match, 'main_extra', 0) or story_hours or 0
            main_story = int(story_hours * 60)
            completionist = int(comp_hours * 60)
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

def update(username, stop_event=None):
    """
    Optimized Update:
    1. Batch updates existing games (Playtime/LastPlayed).
    2. Parallel fetches new games.
    """
    print("OPENING THE VAULT...")
    init_db()

    steam = Steam(settings.STEAM_API_KEY)
    user_data = steam.users.search_user(username)
    if not isinstance(user_data, dict) or 'player' not in user_data or 'steamid' not in user_data['player']:
        raise ValueError(f"Steam user '{username}' could not be resolved. Please verify your Steam username and API key.")
    steam_id = user_data['player']['steamid']
    games_resp = steam.users.get_owned_games(steam_id, True, False)
    if not isinstance(games_resp, dict) or 'games' not in games_resp:
        raise ValueError(f"Failed to fetch owned games for '{username}'. Your games library may be set to private or the API key lacks permissions.")
    owned_games = games_resp['games']

    print(f"Library Scan: Found {len(owned_games)} games.")

    # SEGREGATE GAMES
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

    # FAST BATCH UPDATE (Existing Games)
    if existing_games:
        print(f"Syncing playtime for {len(existing_games)} known games...")
        with get_connection() as conn:
            c = conn.cursor()
            c.executemany(
                "UPDATE games SET playtime_forever=?, rtime_last_played=? WHERE appid=?",
                existing_games
            )
            conn.commit()

    # PARALLEL PROCESSING (New Games)
    if not new_games:
        print("No new recruits found.")
    else:
        print(f"Found {len(new_games)} NEW games. Deploying scrapers...")

        new_game_data = []

        # ThreadPool to run multiple scrapers at once.
        worker_count = 2 if len(new_games) > 10 else 4

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=worker_count)

        # Submit all tasks
        future_to_game = {executor.submit(fetch_game_details_worker, game): game for game in new_games}

        try:
            for i, future in enumerate(concurrent.futures.as_completed(future_to_game)):

                # CHECK THE KILL SWITCH
                if stop_event and stop_event.is_set():
                    print(f"Vault update: Kill switch received. Stopping NOW.")
                    executor.shutdown(wait=False, cancel_futures=True)
                    return

                try:
                    data = future.result()
                    new_game_data.append(data)

                    # YIELD THE PROGRESS TO THE UI
                    yield {
                        "status": "processing",
                        "current": i + 1,
                        "total": len(new_games),
                        "game_name": data[1],
                        "hours": data[2] / 60.0  # Assuming playtime is index 2
                    }

                    print(f"[{i + 1}/{len(new_games)}] Processed {data[1]}")

                except Exception as exc:
                    print(f"Worker generated an exception: {exc}")

        finally:
            # CLEANUP
            executor.shutdown(wait=False, cancel_futures=True)

        # BATCH INSERT (New Games)
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

def stop_update():
    stop_update_bool = True

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


def get_all_games(page=-1, page_size=-1):
    with get_connection() as conn:
        c = conn.cursor()

        if page != -1 and page_size != -1:
            offset_value = page * page_size
            sql_string = "SELECT * FROM games ORDER BY playtime_forever DESC LIMIT ? OFFSET ?"
            c.execute(sql_string, (page_size, offset_value))
        else:
            sql_string = f"""SELECT * FROM games ORDER BY playtime_forever DESC"""
            c.execute(sql_string)

        rows = c.fetchall()
        # Convert to list of dicts immediately to avoid threading issues with Row objects later
        games = [dict(row) for row in rows]

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
            return game
    return None

def get_all_tags(limit=50, recent_days=None):
    """
    Returns a list of tags.
    - Filters out non-game software tags.
    - Filters out 'Ghost Tags' (Owned 1 game, never played) unless requesting recent history.
    - Sorts by HOURS PLAYED (Interest) rather than COUNT (Hoarding).
    """

    with get_connection() as conn:
        c = conn.cursor()

        # Handle "Recent" vs "Lifetime"
        if recent_days:
            # Unix timestamp for X days ago
            cutoff = time.time() - (recent_days * 86400)
            # Only look at games played recently
            c.execute("SELECT tags, playtime_forever FROM games WHERE rtime_last_played > ?", (cutoff,))
        else:
            c.execute("SELECT tags, playtime_forever FROM games")

        rows = c.fetchall()

    stats = {}

    for row in rows:
        if not row['tags']: continue

        # Split tags and clean whitespace
        current_tags = [t.strip() for t in row['tags'].split(',')]
        playtime_mins = row['playtime_forever'] or 0

        for tag in current_tags:
            if tag in IGNORED_TAGS:
                continue

            if tag not in stats:
                stats[tag] = {'count': 0, 'minutes': 0}

            stats[tag]['count'] += 1
            stats[tag]['minutes'] += playtime_mins

    # Format and Filter
    results = []
    for tag, data in stats.items():
        if not recent_days:
            # LIFETIME FILTER: Ignore tags with < 2 games AND < 1 hour total.
            if data['count'] < 2 and data['minutes'] < 60:
                continue

        results.append({
            "name": tag,
            "active_titles_count" if recent_days else "owned_count": data['count'],
            "lifetime_hours_in_tag": round(data['minutes'] / 60, 1)  # Explicitly name it 'lifetime'
        })

    # Smart Sorting
    if recent_days:
        # If looking at recent trends, sort by how many DIFFERENT games in that genre played recently
        # Since lifetime hours will heavily skew towards old games just booted for 5 mins
        results.sort(key=lambda x: (x['active_titles_count'], x['lifetime_hours_in_tag']), reverse=True)
    else:
        # If looking at lifetime, sort by total hours invested
        results.sort(key=lambda x: x['lifetime_hours_in_tag'], reverse=True)

    return results[:limit]

def is_game_owned(appid):
    """
    Returns True if the game is currently owned by the user's library.
    """
    try:
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT appid FROM games WHERE appid=?", (appid,))
            rows = c.fetchall()

        if rows:
            return True
        else:
            return False
    except sqlite3.OperationalError:
        return False


def get_distinct_tags():
    """Return sorted unique canonical tags present in the local library DB."""
    try:
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT tags FROM games WHERE tags IS NOT NULL AND tags != ''")
            rows = c.fetchall()
    except sqlite3.OperationalError:
        return []

    seen = set()
    for row in rows:
        for t in (row['tags'] or "").split(','):
            cleaned = t.strip()
            if cleaned:
                seen.add(cleaned)
    return sorted(seen)


def _format_vault_entry(game, game_status, last_played_str, name_score=0.0, tag_relevance=0):
    entry = dict(game)
    entry['status'] = game_status
    entry['hours'] = game['playtime_forever']
    entry['hltb_main'] = game['hltb_main'] if game['hltb_main'] else None
    entry['hltb_completionist'] = game['hltb_completionist'] if game['hltb_completionist'] else None
    entry['last_played'] = last_played_str
    entry['_name_score'] = name_score
    entry['_tag_relevance'] = tag_relevance
    return entry


def advanced_search(
    tags=None,
    exclude_tags=None,
    tag_mode='all',
    min_playtime=None,
    max_playtime=None,
    hltb_max=None,
    include_unknown_hltb=False,
    status=None,
    min_review_score=None,
    name=None,
    sort_by='shortest',
    page=0,
    page_size=10,
    seed=None,
):
    """
    Filter the vault with tag-vector projection (`tag_mode='all'|'any'`), 3-tier title
    resolution (normalized -> fuzzy -> semantic fallback), HLTB guards, and pagination.
    """
    if tags is None:
        tags = []
    if exclude_tags is None:
        exclude_tags = []
    if status is None:
        status = []

    req_status = {s.lower() for s in status}
    tag_mode = (tag_mode or 'all').lower()
    if tag_mode not in ('all', 'any'):
        tag_mode = 'all'

    # Normalize AI 0-sentinels as unlimited
    if min_playtime == 0:
        min_playtime = None
    if max_playtime == 0:
        max_playtime = None
    if hltb_max == 0:
        hltb_max = None
    if min_review_score == 0:
        min_review_score = None

    # Lazy import avoids top-level circular dependency with core.vibe_engine
    from core.vibe_engine import TAG_ALIASES, VibeEngine

    distinct_tags = get_distinct_tags() if (tags or exclude_tags) else []

    # Resolve exclude tags deterministically (normalized + collapsed + alias targets)
    ex_tags = set()
    if exclude_tags:
        norm_lookup = {text_utils.normalize_tag_key(t): t.lower() for t in distinct_tags}
        col_lookup = {text_utils.collapse_tag_key(t): t.lower() for t in distinct_tags}
        for raw_ex in exclude_tags:
            nkey = text_utils.normalize_tag_key(raw_ex)
            ckey = text_utils.collapse_tag_key(raw_ex)
            ex_tags.add(raw_ex.strip().lower())
            if nkey in norm_lookup:
                ex_tags.add(norm_lookup[nkey])
            if ckey in col_lookup:
                ex_tags.add(col_lookup[ckey])
            for alias_target in TAG_ALIASES.get(nkey, []):
                ex_tags.add(alias_target.lower())

    # Resolve include tags via grouped tag-vector projection
    raw_req_lower = {t.strip().lower() for t in tags if (t or "").strip()}
    tag_groups = []
    expanded_tags = {}
    if tags:
        vibe = VibeEngine.get_instance()
        tag_groups, expanded_tags = vibe.resolve_vault_tags(tags, distinct_tags=distinct_tags)

    all_games = get_all_games()
    eligible_pool = []
    results = []
    unknown_hltb_skipped = 0

    q_norm = text_utils.normalize_title(name, convert_roman=True) if name else ""
    q_nums = text_utils.extract_sequel_numbers(name) if name else set()

    for game in all_games:
        game_status = calculate_status(game)
        if req_status and game_status.lower() not in req_status:
            continue

        game_tags = {t.strip().lower() for t in (game['tags'] or "").split(',') if t.strip()}
        if ex_tags and not ex_tags.isdisjoint(game_tags):
            continue

        tag_relevance = 0
        if tag_groups:
            group_hits = [not grp.isdisjoint(game_tags) for grp in tag_groups]
            if tag_mode == 'any':
                if not any(group_hits):
                    continue
            else:
                if not all(group_hits):
                    continue
            tag_relevance = (len(raw_req_lower & game_tags) * 2) + sum(1 for h in group_hits if h)

        pt = game['playtime_forever']
        if min_playtime is not None and pt < min_playtime * 60:
            continue
        if max_playtime is not None and pt > max_playtime * 60:
            continue

        main_story = game['hltb_main'] or 0
        if hltb_max is not None:
            if main_story == 0:
                if not include_unknown_hltb:
                    unknown_hltb_skipped += 1
                    continue
            elif main_story > hltb_max * 60:
                continue

        if min_review_score is not None:
            score = game.get('review_score', -2)
            if score != -2 and score < min_review_score and score != -1:
                continue

        last_played_str = format_time_ago(game.get('rtime_last_played', 0))
        eligible_pool.append((game, game_status, last_played_str, tag_relevance))

        if name:
            c_norm = text_utils.normalize_title(game['name'], convert_roman=True)
            c_nums = text_utils.extract_sequel_numbers(game['name'])
            is_exact = (q_norm == c_norm) and bool(q_norm)
            is_sub = text_utils.contains_normalized_phrase(q_norm, c_norm) and (not q_nums or q_nums.issubset(c_nums))
            match_score = text_utils.score_title_match(name, game['name'])
            if not (is_exact or is_sub or match_score >= 0.62):
                continue
            results.append(_format_vault_entry(game, game_status, last_played_str, name_score=match_score, tag_relevance=tag_relevance))
        else:
            results.append(_format_vault_entry(game, game_status, last_played_str, name_score=0.0, tag_relevance=tag_relevance))

    # Tier-3 Semantic Title Fallback (strict >= 0.72 similarity + sequel-digit guard)
    if name and not results and eligible_pool:
        pool_games = [item[0] for item in eligible_pool]
        pool_meta = {int(item[0]['appid']): item for item in eligible_pool}
        vibe = VibeEngine.get_instance()
        semantic_hits = vibe.search_titles(name, pool_games, threshold=0.72, top_k=5)
        for hit in semantic_hits:
            meta = pool_meta.get(int(hit['appid']))
            if meta:
                g, g_status, lp_str, t_rel = meta
                results.append(
                    _format_vault_entry(
                        g,
                        g_status,
                        lp_str,
                        name_score=hit.get('title_similarity', 0.72),
                        tag_relevance=t_rel,
                    )
                )

    # Final Sorting
    if sort_by == 'relevance':
        results.sort(
            key=lambda x: (
                -x.get('_name_score', 0.0),
                -x.get('_tag_relevance', 0),
                -(x.get('review_score') if isinstance(x.get('review_score'), (int, float)) else -1),
                x.get('name', ''),
            )
        )
    elif sort_by == 'shortest':
        results.sort(key=lambda x: (x['hltb_main'] if x.get('hltb_main') and x['hltb_main'] > 0 else float('inf'), -x.get('_tag_relevance', 0)))
    elif sort_by == 'longest':
        results.sort(key=lambda x: x.get('hltb_main') or 0, reverse=True)
    elif sort_by == 'name':
        results.sort(key=lambda x: x['name'])
    elif sort_by == 'recent':
        results.sort(key=lambda x: x['rtime_last_played'], reverse=True)
    elif sort_by == 'score_best':
        results.sort(key=lambda x: x['review_score'], reverse=True)
    elif sort_by == 'score_worst':
        results.sort(key=lambda x: x['review_score'], reverse=False)
    elif sort_by == 'random':
        if seed is not None:
            random.Random(seed).shuffle(results)
        else:
            random.shuffle(results)

    game_schema = {
        "transformations": {
            "hours": "minutes_to_hours",
            "hltb_main": "minutes_to_hours_or_na",
            "hltb_completionist": "minutes_to_hours_or_na",
        },
        "keep_keys": [
            "appid",
            "name",
            "status",
            "tags",
            "hours",
            "hltb_main",
            "hltb_completionist",
            "review_score",
            "last_played",
        ]
    }

    results = ai_tools.clean_json_for_ai(
        results,
        transformations=game_schema["transformations"],
        keep_keys=game_schema["keep_keys"],
    )

    total_count = len(results)
    if page_size > 0:
        total_pages = (total_count + page_size - 1) // page_size
        start_idx = page * page_size
        end_idx = start_idx + page_size
        sliced_results = results[start_idx:end_idx]
    else:
        total_pages = 1 if total_count > 0 else 0
        sliced_results = results

    return {
        "results": sliced_results,
        "total_count": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "unknown_hltb_skipped": unknown_hltb_skipped,
        "expanded_tags": expanded_tags,
    }


def vault_search_batch(game_names: list[str]):
    if not game_names:
        return []

    seen_appids = set()
    results = []

    for name in game_names:
        search_payload = advanced_search(name=name, sort_by='relevance', page_size=5)
        for game in search_payload.get("results", []):
            appid = game.get("appid")
            if appid not in seen_appids:
                seen_appids.add(appid)
                results.append(game)

    return results


def get_chart_totals():
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

        # Aggregate Genres (First VALID Tag)
        if tags_str:
            primary_tag = "Uncategorized"  # Fallback just in case

            for tag in tags_str.split(','):
                clean_tag = tag.strip()
                # Check if it's a real genre and not in our global blocklist
                if clean_tag and clean_tag not in IGNORED_TAGS:
                    primary_tag = clean_tag
                    break  # Stop. Primary genre, preventing overlap.

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
    backlog_minutes = 0  # NEW VARIABLE

    for game in games:
        status = calculate_status(game)
        playtime = game.get('playtime_forever', 0)
        hltb = game.get('hltb_main', 0)
        tags_str = game.get('tags', '')

        # Global totals
        total_minutes += playtime

        # Status Counts
        if status == "Unplayed":
            unplayed_count += 1
            backlog_minutes += hltb
        elif status == "Bounced":
            bounced_count += 1
        elif status in ("Invested", "Completionist"):
            finished_count += 1

        # Genre Analysis (Filtered)
        if tags_str:
            tags = [t.strip() for t in tags_str.split(',')]
            for tag in tags:
                if not tag or tag in IGNORED_TAGS:
                    continue  # Skip the noisy unuseful tags
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
                tag_minutes[tag] = tag_minutes.get(tag, 0) + playtime

    # Derived Metrics
    # Shame = (Unplayed + Bounced) / total
    shame_percentage = int(((unplayed_count + bounced_count) / total_games) * 100)
    completion_rate = int((finished_count / total_games) * 100)
    total_hours = int(total_minutes / 60)
    avg_playtime_hours = round(total_hours / total_games, 1)
    backlog_hours = int(backlog_minutes / 60)

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
        "completion_rate": f"{completion_rate}%",
        "total_hours_played": total_hours,
        "backlog_debt_hours": backlog_hours,
        "avg_playtime_hours": avg_playtime_hours,
        "top_played_genres": top_played_fmt,
        "top_owned_genres": top_owned_fmt
    }

if __name__ == "__main__":
    pass
    #print(get_all_tags(recent_days=30))
    #print(get_all_games(0,20))
    #print(advanced_search(sort_by="recent"))
    #hltb_test = get_hltb_search_scrape("Lossless Scaling")
    #print(hltb_test)
    #pprint(get_chart_totals())
    #pprint(get_library_stats())
    # import core.vibe_engine as vibe_engine
    # vibes = vibe_engine.VibeEngine.get_instance()
    # print(vibes.search("gloomy"))
    #pprint(get_all_tags())