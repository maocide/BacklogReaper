import json
import os
import paths
import crypto

SETTINGS_FILE = str(paths.get_base_dir() / "settings.json")

DEFAULT_SETTINGS = {
    "STEAM_API_KEY": "",
    "OPENAI_API_KEY": "",
    "OPENAI_BASE_URL": "",
    "OPENAI_MODEL": "",
    "STEAM_USER": "",
    "CHARACTER": "Reaper",
    "LLM_TEMPERATURE": 0.7,
    "LLM_TOP_P": 1.0,
    "LLM_PRESENCE_PENALTY": 0.0
}

def load_settings():
    """Loads settings from the JSON file, or returns defaults if not found."""
    if not os.path.exists(SETTINGS_FILE):
        paths.ensure_dirs()  # Ensure directories exist on first run
        return DEFAULT_SETTINGS.copy()

    try:
        with open(SETTINGS_FILE, 'r') as f:
            data = json.load(f)
            # Ensure all keys exist (merge with defaults)
            settings = DEFAULT_SETTINGS.copy()
            settings.update(data)

            # Decrypt sensitive keys
            if settings.get("STEAM_API_KEY"):
                settings["STEAM_API_KEY"] = crypto.decrypt(settings["STEAM_API_KEY"])
            if settings.get("OPENAI_API_KEY"):
                settings["OPENAI_API_KEY"] = crypto.decrypt(settings["OPENAI_API_KEY"])

            return settings
    except Exception as e:
        print(f"Error loading settings: {e}")
        return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    """Saves the settings dictionary to the JSON file."""
    try:
        settings_to_save = settings.copy()

        # Encrypt sensitive keys before saving
        if settings_to_save.get("STEAM_API_KEY"):
            settings_to_save["STEAM_API_KEY"] = crypto.encrypt(settings_to_save["STEAM_API_KEY"])
        if settings_to_save.get("OPENAI_API_KEY"):
            settings_to_save["OPENAI_API_KEY"] = crypto.encrypt(settings_to_save["OPENAI_API_KEY"])

        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings_to_save, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving settings: {e}")
        return False




def get_config(key):
    # Priority: 1. settings.json, 2. Environment Variables
    val = _file_settings.get(key)
    if val: return val
    return os.getenv(key)

_file_settings = load_settings()

APP_VERSION = "1.0.0"
STEAM_API_KEY = get_config("STEAM_API_KEY")
OPENAI_API_KEY = get_config("OPENAI_API_KEY")
OPENAI_BASE_URL = get_config("OPENAI_BASE_URL")
OPENAI_MODEL = get_config("OPENAI_MODEL")
STEAM_USER = get_config("STEAM_USER")
LLM_TEMPERATURE = float(get_config("LLM_TEMPERATURE") or 0.7)
LLM_TOP_P = float(get_config("LLM_TOP_P") or 1.0)
LLM_PRESENCE_PENALTY = float(get_config("LLM_PRESENCE_PENALTY") or 0.0)
STEAM_PROFILE_PIC = None # Currently fetched in gatekeeper but not updated in chat

def reload():
    """Refreshes the config variables from the settings file."""
    global STEAM_API_KEY, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, STEAM_USER, LLM_TEMPERATURE, LLM_TOP_P, LLM_PRESENCE_PENALTY, _file_settings
    _file_settings = load_settings()
    STEAM_API_KEY = get_config("STEAM_API_KEY")
    OPENAI_API_KEY = get_config("OPENAI_API_KEY")
    OPENAI_BASE_URL = get_config("OPENAI_BASE_URL")
    OPENAI_MODEL = get_config("OPENAI_MODEL")
    STEAM_USER = get_config("STEAM_USER")
    LLM_TEMPERATURE = float(get_config("LLM_TEMPERATURE") or 0.7)
    LLM_TOP_P = float(get_config("LLM_TOP_P") or 1.0)
    LLM_PRESENCE_PENALTY = float(get_config("LLM_PRESENCE_PENALTY") or 0.0)
