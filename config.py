import os
from dotenv import load_dotenv
import settings

load_dotenv()

_file_settings = settings.load_settings()

def get_config(key):
    # Priority: 1. settings.json, 2. Environment Variables
    val = _file_settings.get(key)
    if val: return val
    return os.getenv(key)

STEAM_API_KEY = get_config("STEAM_API_KEY")
OPENAI_API_KEY = get_config("OPENAI_API_KEY")
OPENAI_BASE_URL = get_config("OPENAI_BASE_URL")
OPENAI_MODEL = get_config("OPENAI_MODEL")
STEAM_USER = get_config("STEAM_USER")

# Only raise error if NOT found in either
# We might want to relax this if we allow the UI to set them later
# But for now, existing logic expects them.
# However, for the GUI app flow, we shouldn't crash on import if they are missing,
# because the user needs to open the GUI to set them.
# So we comment out the hard checks.

# if not STEAM_API_KEY:
#     raise ValueError("No STEAM_API_KEY set for Flask application")
# if not OPENAI_API_KEY:
#     raise ValueError("No OPENAI_API_KEY set for Flask application")
# if not OPENAI_BASE_URL:
#     raise ValueError("No OPENAI_BASE_URL set for Flask application")
# if not OPENAI_MODEL:
#     raise ValueError("No OPENAI_MODEL set for Flask application")
# if not STEAM_USER:
#     raise ValueError("No STEAM_USER set for Flask application")

def reload():
    """Refreshes the config variables from the settings file."""
    global STEAM_API_KEY, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, STEAM_USER, _file_settings
    _file_settings = settings.load_settings()
    STEAM_API_KEY = get_config("STEAM_API_KEY")
    OPENAI_API_KEY = get_config("OPENAI_API_KEY")
    OPENAI_BASE_URL = get_config("OPENAI_BASE_URL")
    OPENAI_MODEL = get_config("OPENAI_MODEL")
    STEAM_USER = get_config("STEAM_USER")
