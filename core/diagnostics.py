import time
import traceback
from typing import Dict, Any, Callable, List

import core.vault as vault
import core.game_intelligence as game_intelligence
import core.community_sentiment as community_sentiment
import core.web_tools as web_tools
import core.vibe_engine as vibe_engine
import core.startup as startup
import core.settings as settings


def check_steam_key_status() -> dict:
    """Checks if STEAM_API_KEY is configured and accepted by Valve."""
    import requests
    if not settings.STEAM_API_KEY:
        return {"error": "STEAM_API_KEY is not configured in settings."}
    try:
        url = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/"
        params = {"key": settings.STEAM_API_KEY, "vanityurl": "valve"}
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 403:
            return {"error": "Steam API Key returned 403 Forbidden (Invalid or expired key)."}
        if resp.status_code != 200:
            return {"error": f"Steam API Key check returned status {resp.status_code}."}
        return {"status": "valid"}
    except Exception as e:
        return {"error": f"Failed to reach Steam API: {e}"}


def run_system_diagnostics(action_description: str = "Running self-checks...") -> str:
    """
    Executes a comprehensive health check on all BacklogReaper APIs, databases,
    and external scraping tools to verify system integrity.
    Returns a Markdown-formatted report.
    """
    print(f"--- STARTING SYSTEM DIAGNOSTICS: {action_description} ---")

    # Ensure local database exists
    try:
        vault.init_db()
    except Exception as e:
        print(f"Diagnostics Init DB Warning: {e}")

    tests = {
        "Steam API Key": {
            "func": check_steam_key_status,
            "args": [],
            "kwargs": {}
        },
        "LLM Configuration": {
            "func": startup.check_llm_keys,
            "args": [],
            "kwargs": {}
        },
        "Vault Database": {
            "func": vault.get_library_stats,
            "args": [],
            "kwargs": {}
        },
        "Vault Search": {
            "func": vault.advanced_search,
            "args": [],
            "kwargs": {"sort_by": "shortest", "page": 0}
        },
        "Steam Store Search": {
            "func": game_intelligence.search_steam_store,
            "args": ["Portal 2"],
            "kwargs": {"limit": 1}
        },
        "Steam Player Reviews (IUserReviewsService)": {
            "func": game_intelligence.get_reviews_byname,
            "args": ["Portal 2"],
            "kwargs": {"count": 2}
        },
        "CheapShark Deals": {
            "func": game_intelligence.get_game_deals,
            "args": ["Portal 2", 620],
            "kwargs": {}
        },
        "Batch Game Details": {
            "func": game_intelligence.get_batch_game_details,
            "args": [["Portal 2"]],
            "kwargs": {}
        },
        "Game News (Steam API)": {
            "func": community_sentiment.get_game_news,
            "args": ["Portal 2"],
            "kwargs": {"limit": 1}
        },
        "Web Search (DDGS)": {
            "func": web_tools.web_search,
            "args": ["Valve video games"],
            "kwargs": {"max_results": 1}
        },
        "Reddit Discussions (Search Syndication)": {
            "func": web_tools.search_reddit_discussions,
            "args": ["Portal 2"],
            "kwargs": {"limit": 2}
        },
        "Vibe Engine": {
            "func": lambda: vibe_engine.VibeEngine.get_instance().search("Puzzle", top_k=1),
            "args": [],
            "kwargs": {}
        }
    }

    results_log = []

    for name, config in tests.items():
        func = config["func"]
        args = config.get("args", [])
        kwargs = config.get("kwargs", {})

        if not callable(func):
            continue

        try:
            result_data = execute_test(name, func, args, kwargs)
            results_log.append(result_data)
        except Exception as e:
            results_log.append({
                "name": name,
                "status": "CRITICAL",
                "message": f"Exception: {str(e)}",
                "data": traceback.format_exc()
            })

    # Generate Report
    report = ["### 🛠️ System Diagnostic Report\n"]

    success_count = 0
    warning_count = 0
    fail_count = 0

    for res in results_log:
        status_icon = "❓"
        if res['status'] == "PASS":
            status_icon = "✅"
            success_count += 1
        elif res['status'] == "WARNING":
            status_icon = "⚠️"
            warning_count += 1
        elif res['status'] in ("FAIL", "CRITICAL"):
            status_icon = "❌"
            fail_count += 1

        line = f"{status_icon} **{res['name']}:** {res['status']}"
        if res.get('message'):
            line += f" — {res['message']}"
        report.append(line)

    summary_line = f"\n**Summary:** {success_count} Passed, {warning_count} Warnings, {fail_count} Failed."
    report.append(summary_line)

    return "\n".join(report)


def execute_test(name: str, func: Callable, args: List, kwargs: Dict) -> Dict:
    start_time = time.time()
    try:
        result = func(*args, **kwargs)

        elapsed = round(time.time() - start_time, 2)
        status = "PASS"
        message = f"Operational ({elapsed}s)"

        # Check tuple returns (like startup.check_llm_keys -> (bool, msg))
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], bool):
            ok, msg = result
            if not ok:
                status = "WARNING"
                message = msg
            else:
                message = f"Configured ({elapsed}s)"

        # Check dict error
        elif isinstance(result, dict) and "error" in result:
            status = "FAIL"
            message = str(result["error"])

        # Check empty data
        elif not result and not isinstance(result, bool):
            status = "WARNING"
            message = "Returned empty data"

        return {
            "name": name,
            "status": status,
            "message": message,
            "data": result
        }

    except Exception as e:
        return {
            "name": name,
            "status": "FAIL",
            "message": f"Exception: {str(e)}",
            "data": traceback.format_exc()
        }


if __name__ == "__main__":
    report = run_system_diagnostics("CLI Manual Run")
    print("\n" + report)
