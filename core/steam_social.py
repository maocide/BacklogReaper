"""
Steam Social, Friends, Multiplayer Ownership Checks, and Library Comparisons.
"""

import concurrent.futures
from datetime import datetime
import json
import time
from typing import Any, Dict, List, Optional

import requests
from steam_web_api import Steam

from core.ai_tools import clean_json_for_ai
from core.safe_tool import safe_tool
import core.settings as settings
from core.steam_store import (
    get_steam_app_info,
    get_steam_avatar,
    resolve_steam_id,
)
import core.vault as vault
from core.vault import calculate_status


def process_friends_list(raw_friends):


    raw_friends.sort(key=lambda x: (x['personastate'], x['lastlogoff'], x['friend_since']), reverse=True)

    clean_list = []
    for f in raw_friends:
        # Filter: Skip Private Profiles (We can't scan their games anyway)
        if f.get('communityvisibilitystate', 0) != 3:
            continue

        clean_list.append(f)


    friends_schema = {
        # TRANSFORMATIONS: 'field_name': 'rule'
        "transformations": {
            "lastlogoff": "date",
        },
        # ALLOWLIST: Only keep these fields
        "keep_keys": [
            "steamid",
            "lastlogoff",
            "personaname",
            "status",
            "realname",
        ]
    }

    clean_list = clean_json_for_ai(clean_list,
                                      transformations=friends_schema["transformations"],
                                      keep_keys=friends_schema["keep_keys"])


    return clean_list


@safe_tool
def get_friends_who_own(game_names):
    """
    Checks which of the user's friends own a list of specific games.
    Fetches each friend's library ONLY ONCE and intersects it with the target games.
    """
    if not isinstance(game_names, list):
        game_names = [game_names]

    # Resolve all requested games to AppIDs
    target_games = {}  # Format: {appid: "Game Name"}
    for name in game_names:
        app = get_steam_app_info(name)
        if app:
            target_games[int(app['id'][0])] = app['name']

    if not target_games:
        return {"error": "None of the requested games could be found on Steam."}

    print(f"Scanning friends for {len(target_games)} games: {list(target_games.values())}...")

    # Get Friend List
    steam = Steam(settings.STEAM_API_KEY)
    user_id = resolve_steam_id(settings.STEAM_USER)

    try:
        friends_list = steam.users.get_user_friends_list(user_id)
    except Exception as e:
        return {"error": f"Could not fetch friend list: {e}"}

    if not friends_list or not friends_list["friends"]:
        return {"error": "No friends found (or profile is private)."}

    # Limit scanning to top 50 active friends
    friends_to_scan = process_friends_list(friends_list.get("friends", []))[:50]

    # Define the Worker Function
    def check_friend_library(friend):
        f_id = friend['steamid']
        try:
            # Fetch friend's library exactly ONCE
            games = steam.users.get_owned_games(f_id, include_appinfo=False)

            owned_targets = []
            if 'games' in games:
                for g in games['games']:
                    # Check if the friend's game matches ANY of our targets
                    if g['appid'] in target_games:
                        owned_targets.append({
                            "game": target_games[g['appid']],
                            "playtime": round(g.get('playtime_forever', 0) / 60, 1)
                        })

            # If they own at least one of the target games, return their profile
            if owned_targets:
                # Sort their owned target games by playtime so the agent sees their favorites first
                owned_targets.sort(key=lambda x: x['playtime'], reverse=True)
                friend["matched_games"] = owned_targets
                return friend

        except Exception:
            # Profile likely private
            pass
        return None

    # Execute Parallel Scan
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(check_friend_library, friends_to_scan))

    owners = [r for r in results if r]

    # Sort friends by how many of the target games they own, then by online status
    owners.sort(key=lambda x: (len(x['matched_games']), x.get('status', 0)), reverse=True)

    # Check which of these games the USER owns (for agent context)
    user_ownership = {name: vault.is_game_owned(appid) for appid, name in target_games.items()}

    return {
        "games_checked": list(target_games.values()),
        "user_owns": user_ownership,
        "friend_count": len(friends_list["friends"]),
        "owners_count": len(owners),
        "friends_data": owners
    }


@safe_tool
def compare_library_with_friend(friend_name):
    """
    Finds a friend by name, fetches their library, and compares it to the user's local Vault.
    """
    steam = Steam(settings.STEAM_API_KEY)
    user_id = resolve_steam_id(settings.STEAM_USER)

    # Fetch Friend List
    try:
        friends_list = steam.users.get_user_friends_list(user_id).get("friends", [])
    except Exception as e:
        return {"error": f"Could not fetch friend list: {e}"}

    if not friends_list:
        return {"error": "Your friend list is empty or private."}

    # Fuzzy Match the Friend's Name
    best_match = None
    best_score = 0

    for f in friends_list:
        name = f.get('personaname', '')
        score = fuzz.partial_ratio(friend_name.lower(), name.lower())
        if score > best_score:
            best_score = score
            best_match = f

    if not best_match or best_score < 70:
        return {"error": f"Could not find a friend matching '{friend_name}'. Are they on user list?"}

    target_id = best_match['steamid']
    target_name = best_match['personaname']
    print(f"Matched '{friend_name}' to friend: {target_name} ({target_id})")

    # Fetch Friend's Library
    try:
        friend_games = steam.users.get_owned_games(target_id, include_appinfo=True)
    except Exception:
        return {"error": f"{target_name}'s game library is private."}

    if 'games' not in friend_games:
        return {"error": f"Could not read {target_name}'s games (might be private)."}

    # Fetch Recently Played (Bypasses the missing timestamp for possible privacy filtered)
    recent_appids = {}
    try:
        recent_data = steam.users.get_user_recently_played_games(target_id)
        if 'games' in recent_data:
            # Map AppID to their 2-week playtime
            recent_appids = {g['appid']: g.get('playtime_2weeks', 0) for g in recent_data['games']}
    except Exception as e:
        print(f"Could not fetch recent games for {target_name}: {e}")

    friend_library = friend_games['games']



    ## Debug test code,
    # try:
    #     recent_data = steam.users.get_user_recently_played_games(target_id)
    #     if 'games' in recent_data:
    #         recent_appids = {g['appid']: g.get('playtime_2weeks', 0) for g in recent_data['games']}
    #
    #         print(f"DEBUG: {target_name} recently played these AppIDs: {list(recent_appids.keys())}")
    # except Exception as e:
    #     print(f"Could not fetch recent games for {target_name}: {e}")

    # Get Friend's RECENT Favorites
    # Sort primarily by Last Played, then by Playtime

    friend_library.sort(key=lambda x: (x.get('rtime_last_played', 0), x.get('playtime_forever', 0)), reverse=True)

    # pprint(friend_library)

    friend_top_played = []
    for g in friend_library:
        # Skip unplayed games immediately
        if g.get('playtime_forever', 0) <= 0:
            continue

        last_played_unix = g.get('rtime_last_played', 0)

        friend_top_played.append({
            "name": g.get('name', f"App {g['appid']}"),
            "playtime_hours": g.get('playtime_forever', 0),
            "last_played": last_played_unix
        })

        # Stop once we have 5 valid games
        if len(friend_top_played) >= 5:
            break

    # Cross-Reference with User's Vault
    shared_games = []
    user_vault_games = vault.get_all_games()
    user_appids = {g['appid']: g for g in user_vault_games}

    for g in friend_library:
        appid = g['appid']
        if appid in user_appids:
            local_game = user_appids[appid]

            # Is it a multiplayer game?
            tags = local_game.get('tags', '')
            is_mp = False
            if isinstance(tags, str) and any(t in tags for t in ['Multiplayer', 'Co-op', 'Online Co-Op']):
                is_mp = True
            elif isinstance(tags, list) and any(t in tags for t in ['Multiplayer', 'Co-op', 'Online Co-Op']):
                is_mp = True

            # TIME
            last_played_unix = g.get('rtime_last_played', 0)

            if appid in recent_appids:
                # We definitively know they played it in the last 14 days!
                last_played_str = "Active"
                # Give it a massive artificial timestamp so it sorts to the very top
                sort_weight = datetime.now().timestamp() + recent_appids[appid]
            elif last_played_unix > 0:
                dt = datetime.fromtimestamp(int(last_played_unix))
                last_played_str = dt.strftime("%Y-%m-%d")
                sort_weight = last_played_unix
            else:
                last_played_str = "N/A"
                sort_weight = last_played_unix

            shared_games.append({
                "name": local_game['name'],
                "is_multiplayer": is_mp,
                "sort_weight": sort_weight,  # Used exclusively for sorting
                "friend_last_played": last_played_str,
                "friend_playtime": g.get('playtime_forever', 0),
                "user_playtime": local_game.get('playtime_forever', 0) # Secondary sort, edge case when friend activity private
            })

    # Sort prioritizing Multiplayer games FIRST, then by custom Sort Weight, then playtimes
    shared_games.sort(key=lambda x: (x['is_multiplayer'], x['sort_weight'], x['friend_playtime'], x['user_playtime']), reverse=True)

    friends_schema = {
        # TRANSFORMATIONS: 'field_name': 'rule'
        "transformations": {
            "friend_playtime": "minutes_to_hours_or_na",
            "user_playtime": "minutes_to_hours_or_na",
            "playtime_hours": "minutes_to_hours_or_na",
            "last_played": "date",
        },
        # ALLOWLIST: Only keep these fields
        "keep_keys": [
            "name",
            "playtime_hours",
            "last_played",
            "is_multiplayer",
            "friend_last_played",
            "friend_playtime",
            "user_playtime",
            "friend_name",
            "status",
            "friend_recent_favorites",
            "total_shared_games",
            "top_shared_multiplayer",
            "top_shared"
        ]
    }

    result = {
        "friend_name": target_name,
        "status": "online" if best_match.get('personastate', 0) == 1 else "offline",
        "friend_recent_favorites": friend_top_played if friend_top_played else "N/A Privacy?",
        "total_shared_games": len(shared_games),
        "top_shared_multiplayer": [g for g in shared_games if g['is_multiplayer']][:7],
        "top_shared": [g for g in shared_games if not g['is_multiplayer']][:3]
    }

    result = clean_json_for_ai(result,
                                  transformations=friends_schema["transformations"],
                                  keep_keys=friends_schema["keep_keys"])

    return result


@safe_tool
def get_active_friends():
    """
    Fetches the user's friend list and runs a batch GetPlayerSummaries
    via direct HTTP request to see exactly who is online and what they are playing.
    """
    steam = Steam(settings.STEAM_API_KEY)
    user_id = resolve_steam_id(settings.STEAM_USER)

    # Get Friend List (Just the IDs) using the wrapper
    try:
        friends_list = steam.users.get_user_friends_list(user_id).get("friends", [])
    except Exception as e:
        return {"error": f"Could not fetch friend list: {e}"}

    if not friends_list:
        return {"error": "Your friend list is empty or private."}

    # Extract up to 100 SteamIDs (Steam's batch limit for this endpoint)
    friend_ids = [f['steamid'] for f in friends_list[:100]]
    comma_separated_ids = ",".join(friend_ids)

    # Get Player Summaries using direct HTTP request
    url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
    params = {
        "key": settings.STEAM_API_KEY,
        "steamids": comma_separated_ids
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        summaries = data.get('response', {}).get('players', [])
    except Exception as e:
        return {"error": f"Could not fetch player summaries via HTTP: {e}"}

    active_friends = []
    recently_offline = []

    for player in summaries:
        # personastate: 0 = Offline, 1 = Online, 2 = Busy, 3 = Away, 4 = Snooze, 5 = looking to trade, 6 = looking to play
        status_code = player.get('personastate', 0)

        # Sometimes users appear offline but Steam still broadcasts gameextrainfo
        current_game = player.get('gameextrainfo')
        name = player.get('personaname', 'Unknown')

        if status_code > 0 or current_game:
            # Map status code to text
            status_map = {1: "Online", 2: "Busy", 3: "Away", 4: "Snooze", 5: "Looking to Trade", 6: "Looking to Play"}
            status_text = status_map.get(status_code, "Offline")

            active_friends.append({
                "name": player.get('personaname', 'Unknown'),
                "status": status_text,
                "currently_playing": current_game if current_game else "Nothing"
            })
        else:
            # Catch the offline players
            last_logoff = player.get('lastlogoff', 0)
            if last_logoff > 0:

                recently_offline.append({
                    "name": name,
                    "last_seen": last_logoff  # For sorting
                })

    # Sort the offline list to get the most recent ones
    recently_offline.sort(key=lambda x: x['last_seen'], reverse=True)
    # Sort so people actually playing games are at the very top
    active_friends.sort(key=lambda x: (x['currently_playing'] != "Nothing", x['status'] == "Online"),
                        reverse=True)

    max_entries = 10
    max_offline = max_entries - len(active_friends) if max_entries - len(active_friends) > 0 else 0

    result = {
        "total_friends": len(friend_ids),
        "online_count": len(active_friends),
        "active_players": active_friends[:max_entries],
        "recently_offline": recently_offline[:max_offline]
    }

    friends_schema = {
        # TRANSFORMATIONS: 'field_name': 'rule'
        "transformations": {
            "last_seen": "datetime",
        },
        # ALLOWLIST: Only keep these fields
        "keep_keys": [
            "total_friends",
            "online_count",
            "active_players",
            "recently_offline",
            "name",
            "last_seen",
            "status",
            "currently_playing",
        ]
    }

    result = clean_json_for_ai(result,
                                  transformations=friends_schema["transformations"],
                                  keep_keys=friends_schema["keep_keys"])

    return result


@safe_tool
def get_user_activity(
    include_sessions: bool = True,
    max_sessions: int = 3,
    session_gap_hours: int = 8
) -> dict:
    """
    Checks the user's live Steam presence (in-game title & AppID) and investigates
    recent gaming sessions from the Vault, clustering close playtimes (within session_gap_hours)
    and reporting achievements unlocked during those sessions.
    """
    steam_id = resolve_steam_id(settings.STEAM_USER)
    if not steam_id:
        return {"error": "Could not resolve Steam ID for user."}

    # 1. Live Status Probe
    live_status = {"online": False, "status": "offline_or_invisible", "game": None, "appid": None}
    try:
        url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
        params = {"key": settings.STEAM_API_KEY, "steamids": steam_id}
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            players = resp.json().get("response", {}).get("players", [])
            if players:
                p = players[0]
                p_state = p.get("personastate", 0)
                game_title = p.get("gameextrainfo")
                game_id = p.get("gameid")

                state_map = {
                    0: "Offline / Invisible",
                    1: "Online",
                    2: "Busy",
                    3: "Away",
                    4: "Snooze",
                    5: "Looking to trade",
                    6: "Looking to play",
                }

                if game_id:
                    total_hours = None
                    try:
                        g_entry = vault.get_game_by_appid(int(game_id))
                        if g_entry:
                            total_hours = round((g_entry.get("playtime_forever") or 0) / 60.0, 1)
                    except Exception:
                        pass

                    live_status = {
                        "online": True,
                        "status": "in_game",
                        "game": game_title or f"AppID {game_id}",
                        "appid": int(game_id) if str(game_id).isdigit() else game_id,
                        "total_hours": total_hours,
                    }
                else:
                    live_status = {
                        "online": p_state > 0,
                        "status": "not_in_game" if p_state > 0 else "offline_or_invisible",
                        "persona_state": state_map.get(p_state, "Unknown"),
                        "game": None,
                        "appid": None,
                    }
    except Exception as e:
        live_status["error"] = str(e)

    if not include_sessions:
        return {"live_status": live_status, "sessions": []}

    # 2. Query Recent Games from Vault Database
    recent_games = []
    try:
        with vault.get_connection() as conn:
            c = conn.cursor()
            rows = c.execute(
                "SELECT appid, name, playtime_forever, rtime_last_played FROM games "
                "WHERE rtime_last_played > 0 ORDER BY rtime_last_played DESC LIMIT 15"
            ).fetchall()
            recent_games = [
                {
                    "appid": r["appid"],
                    "name": r["name"],
                    "playtime_forever": r["playtime_forever"],
                    "rtime_last_played": r["rtime_last_played"]
                }
                for r in rows
            ]
    except Exception as e:
        return {"live_status": live_status, "sessions": [], "error": f"Failed reading vault: {e}"}

    if not recent_games:
        return {"live_status": live_status, "sessions": []}

    # 3. Temporal Clustering into Sessions
    session_clusters = []
    current_cluster = []
    gap_seconds = max(session_gap_hours, 1) * 3600

    for g in recent_games:
        if not current_cluster:
            current_cluster.append(g)
        else:
            prev_lp = current_cluster[-1]["rtime_last_played"]
            diff = prev_lp - g["rtime_last_played"]
            if diff <= gap_seconds:
                current_cluster.append(g)
            else:
                session_clusters.append(current_cluster)
                current_cluster = [g]
                if len(session_clusters) >= max_sessions:
                    break

    if current_cluster and len(session_clusters) < max_sessions:
        session_clusters.append(current_cluster)

    # 4. Inspect Session Achievements
    sessions_payload = []
    schema_cache = {}

    for s_idx, cluster in enumerate(session_clusters):
        session_start = cluster[-1]["rtime_last_played"]
        session_end = cluster[0]["rtime_last_played"]

        cluster_games = []
        for gm in cluster:
            gid = gm["appid"]
            gname = gm["name"]
            lp = gm["rtime_last_played"]
            total_h = round((gm.get("playtime_forever") or 0) / 60.0, 1)

            game_ach_summary = {
                "appid": gid,
                "name": gname,
                "last_played_ts": lp,
                "last_played_str": vault.format_time_ago(lp),
                "total_hours": total_h,
                "has_achievements": False,
                "total_unlocked": 0,
                "total_available": 0,
                "completion_pct": 0.0,
                "session_unlocks": [],
            }

            try:
                ach_url = f"https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/?appid={gid}&key={settings.STEAM_API_KEY}&steamid={steam_id}"
                r_ach = requests.get(ach_url, timeout=5)
                if r_ach.status_code == 200:
                    a_data = r_ach.json().get("playerstats", {})
                    achs = a_data.get("achievements", [])
                    if achs:
                        game_ach_summary["has_achievements"] = True
                        game_ach_summary["total_available"] = len(achs)
                        unlocked = [a for a in achs if a.get("achieved") == 1 and a.get("unlocktime", 0) > 0]
                        game_ach_summary["total_unlocked"] = len(unlocked)
                        if len(achs) > 0:
                            game_ach_summary["completion_pct"] = round((len(unlocked) / len(achs)) * 100.0, 1)

                        # Unlocks within session window: from (lp - 14400s) to (lp + 600s)
                        session_raw = [a for a in unlocked if (lp - 14400) <= a["unlocktime"] <= (lp + 600)]

                        if session_raw:
                            if gid not in schema_cache:
                                schema_cache[gid] = {}
                                s_url = f"https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/?key={settings.STEAM_API_KEY}&appid={gid}"
                                r_s = requests.get(s_url, timeout=5)
                                if r_s.status_code == 200:
                                    s_json = r_s.json().get("game", {}).get("availableGameStats", {})
                                    for item in s_json.get("achievements", []):
                                        schema_cache[gid][item["name"]] = {
                                            "name": item.get("displayName", item["name"]),
                                            "desc": item.get("description", "")
                                        }

                            session_raw.sort(key=lambda x: x["unlocktime"], reverse=True)
                            for s_item in session_raw[:6]:
                                aname = s_item.get("apiname", "")
                                meta = schema_cache[gid].get(aname, {})
                                u_ts = s_item.get("unlocktime", 0)
                                game_ach_summary["session_unlocks"].append({
                                    "apiname": aname,
                                    "name": meta.get("name", aname),
                                    "desc": meta.get("desc", ""),
                                    "unlock_time": datetime.fromtimestamp(u_ts).strftime("%H:%M") if u_ts else ""
                                })
            except Exception:
                pass

            cluster_games.append(game_ach_summary)

        sessions_payload.append({
            "session_index": s_idx + 1,
            "session_time_str": vault.format_time_ago(session_end),
            "session_end_ts": session_end,
            "session_start_ts": session_start,
            "games": cluster_games
        })

    return {
        "live_status": live_status,
        "sessions": sessions_payload
    }

