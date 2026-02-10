import json
import os

SETTINGS_FILE = 'settings.json'

DEFAULT_SETTINGS = {
    "STEAM_API_KEY": "",
    "OPENAI_API_KEY": "",
    "OPENAI_BASE_URL": "",
    "OPENAI_MODEL": "",
    "STEAM_USER": "",
    "CHARACTER": "Reaper"
}

def load_settings():
    """Loads settings from the JSON file, or returns defaults if not found."""
    if not os.path.exists(SETTINGS_FILE):
        return DEFAULT_SETTINGS.copy()

    try:
        with open(SETTINGS_FILE, 'r') as f:
            data = json.load(f)
            # Ensure all keys exist (merge with defaults)
            settings = DEFAULT_SETTINGS.copy()
            settings.update(data)
            return settings
    except Exception as e:
        print(f"Error loading settings: {e}")
        return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    """Saves the settings dictionary to the JSON file."""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
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

STEAM_API_KEY = get_config("STEAM_API_KEY")
OPENAI_API_KEY = get_config("OPENAI_API_KEY")
OPENAI_BASE_URL = get_config("OPENAI_BASE_URL")
OPENAI_MODEL = get_config("OPENAI_MODEL")
STEAM_USER = get_config("STEAM_USER")
STEAM_PROFILE_PIC = None

def reload():
    """Refreshes the config variables from the settings file."""
    global STEAM_API_KEY, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, STEAM_USER, _file_settings
    _file_settings = load_settings()
    STEAM_API_KEY = get_config("STEAM_API_KEY")
    OPENAI_API_KEY = get_config("OPENAI_API_KEY")
    OPENAI_BASE_URL = get_config("OPENAI_BASE_URL")
    OPENAI_MODEL = get_config("OPENAI_MODEL")
    STEAM_USER = get_config("STEAM_USER")
