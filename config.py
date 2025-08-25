import os
from dotenv import load_dotenv

load_dotenv()

STEAM_API_KEY = os.getenv("STEAM_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL = os.getenv("OPENAI_MODEL")
STEAM_USER = os.getenv("STEAM_USER")

if not STEAM_API_KEY:
    raise ValueError("No STEAM_API_KEY set for Flask application")
if not OPENAI_API_KEY:
    raise ValueError("No OPENAI_API_KEY set for Flask application")
if not OPENAI_BASE_URL:
    raise ValueError("No OPENAI_BASE_URL set for Flask application")
if not OPENAI_MODEL:
    raise ValueError("No OPENAI_MODEL set for Flask application")
if not STEAM_USER:
    raise ValueError("No STEAM_USER set for Flask application")
