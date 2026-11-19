"""
Unified Steam Achievements Engine.
Provides schema resolution, raw player queries, session milestone extraction,
and achievement dashboard/pagination analytics with zero disk staleness.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from core.safe_tool import safe_tool
import core.settings as settings
from core.web_tools import get_steam_bypass_with_referer

# In-memory schema cache for static developer metadata (display names & descriptions)
_SCHEMA_CACHE: Dict[int, Dict[str, Dict[str, str]]] = {}


def get_game_achievement_schema(appid: int) -> Dict[str, Dict[str, str]]:
    """
    Fetches and caches the achievement schema (display names & descriptions) for an AppID.
    Returns map: api_name -> {"real_name": str, "desc": str}.
    Thread-safe and cached in memory across calls (never persisted to disk).
    """
    if appid in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[appid]

    schema_map: Dict[str, Dict[str, str]] = {}
    try:
        url = f"https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/?key={settings.STEAM_API_KEY}&appid={appid}"
        headers, cookies = get_steam_bypass_with_referer(appid)
        resp = requests.get(url, headers=headers, cookies=cookies, timeout=5)
        if resp.status_code == 200:
            stats = resp.json().get("game", {}).get("availableGameStats", {})
            for item in stats.get("achievements", []):
                schema_map[item["name"]] = {
                    "real_name": item.get("displayName", item["name"]),
                    "desc": item.get("description", "No description provided.")
                }
    except Exception as e:
        print(f"Warning: Failed to fetch achievement schema for {appid}: {e}")

    _SCHEMA_CACHE[appid] = schema_map
    return schema_map


def get_player_achievements_raw(
    appid: int,
    steam_id: Optional[str] = None
) -> Tuple[Optional[List[dict]], Optional[str], bool]:
    """
    Fetches raw player achievements live from Steam WebAPI.
    Never cached on disk to guarantee zero stale data when unlocks happen.

    Returns:
        (achievements_list, message_or_error, has_achievements)
    """
    if not steam_id:
        from core.game_intelligence.store import resolve_steam_id
        steam_id = resolve_steam_id(settings.STEAM_USER)
    if not steam_id:
        return None, "Could not resolve Steam ID.", False

    url = f"https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/?appid={appid}&key={settings.STEAM_API_KEY}&steamid={steam_id}"
    try:
        resp = requests.get(url, timeout=5)
        user_data = {}
        try:
            user_data = resp.json()
        except ValueError:
            pass

        ps_error = (user_data.get("playerstats") or {}).get("error", "")

        # 403: unowned, unplayed, or private profile
        if resp.status_code == 403:
            return None, "No achievement data found. The user likely does not own the game or has a private profile.", False

        # 400 with 'no stats': game has no Steam achievements configured
        if resp.status_code == 400 and "no stats" in ps_error.lower():
            return [], "This game does not have Steam Achievements.", False

        if resp.status_code != 200:
            detail = f" ({ps_error})" if ps_error else ""
            return None, f"Steam API returned status code {resp.status_code}{detail}.", False

        playerstats = user_data.get("playerstats", {})
        if not playerstats.get("success", False):
            return None, ps_error or "Could not parse player stats. Profile might be private.", False

        achievements = playerstats.get("achievements", [])
        if not achievements:
            return [], "This game does not have Steam Achievements.", False

        return achievements, None, True

    except Exception as e:
        return None, f"Failed fetching player achievements: {e}", False


def get_session_achievements(
    appid: int,
    last_played_ts: int,
    session_window_seconds: int = 14400,
    steam_id: Optional[str] = None
) -> dict:
    """
    Extracts achievements unlocked during a specific play session window
    (last_played_ts - session_window_seconds to last_played_ts + 600).
    Resolves human-readable names and descriptions using the in-memory schema cache.
    """
    achs, err, has_achs = get_player_achievements_raw(appid, steam_id=steam_id)

    res = {
        "has_achievements": has_achs,
        "total_available": 0,
        "total_unlocked": 0,
        "completion_pct": 0.0,
        "session_unlocks": []
    }

    if not has_achs or not achs:
        return res

    res["total_available"] = len(achs)
    unlocked = [a for a in achs if a.get("achieved") == 1 and a.get("unlocktime", 0) > 0]
    res["total_unlocked"] = len(unlocked)
    if achs:
        res["completion_pct"] = round((len(unlocked) / len(achs)) * 100.0, 1)

    # Session window: from (last_played_ts - session_window_seconds) to (last_played_ts + 600)
    window_start = last_played_ts - session_window_seconds
    window_end = last_played_ts + 600
    session_raw = [a for a in unlocked if window_start <= a["unlocktime"] <= window_end]

    if session_raw:
        schema = get_game_achievement_schema(appid)
        session_raw.sort(key=lambda a: a["unlocktime"])
        for a in session_raw:
            apiname = a.get("apiname", "")
            details = schema.get(apiname, {"real_name": apiname, "desc": ""})
            res["session_unlocks"].append({
                "apiname": apiname,
                "name": details.get("real_name", apiname),
                "desc": details.get("desc", ""),
                "description": details.get("desc", ""),
                "unlock_time": datetime.fromtimestamp(a["unlocktime"]).strftime("%H:%M") if a.get("unlocktime") else "",
                "raw_unlock_time": a.get("unlocktime", 0),
                "date": datetime.fromtimestamp(a["unlocktime"]).strftime("%Y-%m-%d %H:%M")
            })

    return res


@safe_tool
def get_achievement_stats(appid: int = -1, game_name: str = "", page: Optional[int] = None) -> dict:
    """
    Fetches Achievement stats.
    Default: Returns a 'Dashboard' summary (Stats + Top 3 Easiest Locked).
    If 'page' is set (int), returns a list of locked achievements for browsing.
    """
    from core.game_intelligence.store import get_steam_app_info, resolve_steam_id

    if appid == -1 and game_name:
        app_info = get_steam_app_info(game_name)
        if not app_info:
            return {"error": f"Game not found: {game_name}"}
        appid = int(app_info["id"][0])

    steam_id = resolve_steam_id(settings.STEAM_USER)
    if not steam_id:
        return {"error": "Could not resolve Steam ID."}

    # 1. Fetch Schema for Descriptions
    ach_details = get_game_achievement_schema(appid)

    # 2. Fetch Global Achievement Percentages
    global_url = f"https://api.steampowered.com/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v0002/?gameid={appid}&format=json"
    headers, cookies = get_steam_bypass_with_referer(appid)
    try:
        global_http = requests.get(global_url, headers=headers, cookies=cookies, timeout=5)
        global_resp = global_http.json() if global_http.status_code == 200 else {}
    except Exception:
        global_resp = {}
    global_map = {
        a["name"]: a["percent"]
        for a in global_resp.get("achievementpercentages", {}).get("achievements", [])
    }

    # 3. Fetch Player Achievements Live
    user_achievements, err_msg, has_achs = get_player_achievements_raw(appid, steam_id=steam_id)
    if err_msg:
        if not has_achs:
            return {
                "game": game_name or str(appid),
                "appid": int(appid),
                "view": "no_achievements",
                "has_achievements": False,
                "message": err_msg,
            }
        return {"error": err_msg}

    if not user_achievements:
        return {
            "game": game_name or str(appid),
            "appid": int(appid),
            "view": "no_achievements",
            "has_achievements": False,
            "message": "This game does not have Steam Achievements.",
        }

    # 4. Process Lists
    unlocked_list = []
    locked_list = []

    for ach in user_achievements:
        api_name = ach["apiname"]
        details = ach_details.get(api_name, {"real_name": api_name, "desc": ""})

        entry = {
            "name": details["real_name"],
            "description": details["desc"],
            "rarity": global_map.get(api_name, 0.0),
            "unlocked": ach.get("achieved", 0),
            "unlock_time": ach.get("unlocktime", 0)
        }

        if entry["unlocked"]:
            entry["date"] = datetime.fromtimestamp(entry["unlock_time"]).strftime("%Y-%m-%d %H:%M")
            unlocked_list.append(entry)
        else:
            locked_list.append(entry)

    total = len(user_achievements)
    count = len(unlocked_list)
    percent_complete = int((count / total) * 100) if total > 0 else 0

    # 5. Mode Selection: Pagination vs Dashboard
    if page is not None:
        locked_list.sort(key=lambda x: x["rarity"], reverse=True)
        items_per_page = 10
        start = page * items_per_page
        end = start + items_per_page

        return {
            "game": game_name,
            "view": "locked_list",
            "page": page,
            "total_locked": len(locked_list),
            "total_pages": (len(locked_list) + items_per_page - 1) // items_per_page,
            "achievements": locked_list[start:end]
        }

    # Dashboard Mode
    unlocked_list.sort(key=lambda x: x["unlock_time"], reverse=True)
    locked_list.sort(key=lambda x: x["rarity"], reverse=True)

    return {
        "game": game_name,
        "appid": int(appid),
        "view": "dashboard",
        "has_achievements": True,
        "stats": {
            "total": total,
            "unlocked": count,
            "locked": len(locked_list),
            "percentage": percent_complete
        },
        "latest_unlocked": unlocked_list[0] if unlocked_list else None,
        "easiest_locked": locked_list[:3]
    }
