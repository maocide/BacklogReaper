import config
import vault

def check_api_keys():
    """
    Checks if necessary API keys are present in config.
    Returns: (bool, message)
    """
    missing = []
    if not config.STEAM_API_KEY:
        missing.append("STEAM_API_KEY")
    if not config.OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")

    if missing:
        return False, f"Missing keys: {', '.join(missing)}"

    return True, "API Keys configured."

def check_database_populated():
    """
    Checks if the local vault has games.
    Returns: (bool, message)
    """
    count = vault.get_games_count()
    if count == 0:
        return False, "Database is empty. Please fetch games."

    return True, f"Database has {count} games."

def check_all():
    """
    Runs all checks.
    Returns: (bool, list of failures)
    """
    ok_keys, msg_keys = check_api_keys()
    ok_db, msg_db = check_database_populated()

    failures = []
    if not ok_keys: failures.append(msg_keys)
    if not ok_db: failures.append(msg_db)

    return (len(failures) == 0), failures
