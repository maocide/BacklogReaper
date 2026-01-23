import os
import json
import base64
from PIL import Image
from PIL.PngImagePlugin import PngInfo

CHARACTERS_DIR = "characters"

def ensure_characters_dir():
    if not os.path.exists(CHARACTERS_DIR):
        os.makedirs(CHARACTERS_DIR)

def get_available_characters():
    """Returns a list of available character names (filenames without extension)."""
    ensure_characters_dir()
    chars = []
    for f in os.listdir(CHARACTERS_DIR):
        if f.endswith(".json") or f.endswith(".png"):
            # Strip extension
            name = os.path.splitext(f)[0]
            if name not in chars:
                chars.append(name)
    return sorted(chars)

def get_character_real_name(filename):
    """Loads the character data and returns the internal 'name' field, or falls back to filename."""
    data = load_character(filename)
    if data and "name" in data:
        return data["name"]
    return filename

def load_character(name):
    """
    Loads character data by name.
    Prioritizes .json, then .png.
    Returns a dict with tavern fields.
    """
    ensure_characters_dir()

    # Try JSON first
    json_path = os.path.join(CHARACTERS_DIR, f"{name}.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading JSON char {name}: {e}")

    # Try PNG (Tavern Card)
    png_path = os.path.join(CHARACTERS_DIR, f"{name}.png")
    if os.path.exists(png_path):
        return load_character_card_png(png_path)

    return None

def load_character_card_png(path):
    """
    Extracts TavernAI/SillyTavern character data from a PNG file.
    Usually stored in 'chara' (base64) or standard tEXt chunks.
    """
    try:
        im = Image.open(path)
        im.load()

        # 1. Check for 'chara' chunk (Base64 encoded string of the json)
        # This is the standard TavernAI format
        if "chara" in im.info:
            decoded = base64.b64decode(im.info["chara"]).decode('utf-8')
            return json.loads(decoded)

        # 2. Check for 'ccv3' (V3 Spec, often just raw bytes or similar base64)
        if "ccv3" in im.info:
             decoded = base64.b64decode(im.info["ccv3"]).decode('utf-8')
             return json.loads(decoded)

        # 3. Text chunks
        # Sometimes key fields are just stored as text
        # But usually character cards use the encoded block.

        print(f"No valid character metadata found in {path}")
        return None

    except Exception as e:
        print(f"Error reading PNG card {path}: {e}")
        return None
