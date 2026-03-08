import settings
import vault
from web_tools import HLTBManager

def check_api_keys():
    """
    Checks if necessary API keys are present in config.
    Returns: (bool, message)
    """
    missing = []
    if not settings.STEAM_API_KEY:
        missing.append("STEAM_API_KEY")
    if not settings.OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")

    if missing:
        return False, f"Missing keys: {', '.join(missing)}"

    return True, "API Keys configured."

def check_llm_keys():
    """
    Checks if necessary LLM API keys and model configuration are present in config.
    Returns: (bool, message)
    """
    missing = []
    if not settings.OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if not settings.OPENAI_BASE_URL:
        missing.append("OPENAI_BASE_URL")
    if not settings.OPENAI_MODEL:
        missing.append("OPENAI_MODEL")

    if missing:
        return False, f"Missing LLM Configuration: {', '.join(missing)}"

    return True, "LLM Keys configured."

def check_database_populated():
    """
    Checks if the local vault has games.
    Returns: (bool, message)
    """
    count = vault.get_games_count()
    if count == 0:
        return False, "Database is empty. Please fetch games."

    return True, f"Database has {count} games."

def check_hltb_dataset():
    """
    Checks if the HLTB dataset is available and downloads it if missing.
    """
    try:
        manager = HLTBManager.get_instance()
        path = manager.ensure_dataset()
        if path:
            # Optionally load it now to warm up cache
            manager.load_data()
            return True, "HLTB Dataset Ready."
        else:
            return False, "Failed to download HLTB Dataset."
    except Exception as e:
        return False, f"HLTB Error: {e}"

def check_all():
    """
    Runs all checks.
    Returns: (bool, list of failures)
    """
    ok_keys, msg_keys = check_api_keys()
    ok_llm_keys, msg_llm_keys = check_llm_keys()

    # HLTB check (Auto-download)
    ok_hltb, msg_hltb = check_hltb_dataset()

    ok_db, msg_db = check_database_populated()

    failures = []
    if not ok_keys: failures.append(msg_keys)
    if not ok_llm_keys: failures.append(msg_llm_keys)
    if not ok_hltb: failures.append(msg_hltb)
    # Database empty is not a critical failure preventing app start, but good to know
    if not ok_db: failures.append(msg_db)

    # If anything critical is missing, report it.

    critical_failures = []
    # If LLM keys are missing it's not critical for startup (Gatekeeper only needs Steam keys),
    # but check_api_keys includes OPENAI_API_KEY. However we don't block the app.
    if not ok_keys: critical_failures.append(msg_keys)
    if not ok_hltb: critical_failures.append(msg_hltb)

    if critical_failures:
        return False, critical_failures + failures # Append other warnings

    return True, failures # Return any non-critical warnings
