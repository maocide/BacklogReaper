import flet as ft
import webbrowser
import os
import styles
import subprocess
import platform

async def smart_update(control):
    """
    Updates a Flet control, preferring the async method if available.
    """
    if hasattr(control, 'update_async'):
        await control.update_async()
    else:
        control.update()

def launch_game(appid):
    """Launches the game using the steam protocol directly via OS commands."""
    try:
        url = f"steam://run/{appid}"
        print(f"Launching: {url}")

        system_name = platform.system()

        if system_name == 'Windows':
            if hasattr(os, 'startfile'):
                 os.startfile(url)
            else:
                 # Windows fallback requires shell=True for 'start' to work with URLs
                 subprocess.run(['start', url], shell=True)
        elif system_name == 'Darwin': # macOS
            subprocess.run(['open', url])
        elif system_name == 'Linux':
            subprocess.run(['xdg-open', url])
        else:
            # Fallback for unknown OS
            webbrowser.open(url)

    except Exception as e:
        print(f"Error launching game via subprocess: {e}")
        # Last resort fallback
        try:
            webbrowser.open(url)
        except Exception as e2:
            print(f"Error launching game via webbrowser: {e2}")

def get_status_color(status):
    """Returns the color corresponding to a game status."""
    color_map = {
        # --- Common (Grey/White) ---
        "Backlog": styles.COLOR_RARITY_COMMON,
        "Unplayed": styles.COLOR_RARITY_COMMON,
        "Forgotten": styles.COLOR_RARITY_COMMON_VAR, # Variant for distinction

        # --- Magic (Blue) ---
        "Trying": styles.COLOR_RARITY_MAGIC,
        "Testing": styles.COLOR_RARITY_MAGIC_VAR, # Variant
        "Started": styles.COLOR_RARITY_MAGIC,

        # --- Rare (Yellow/Gold) ---
        "Active": styles.COLOR_RARITY_RARE,
        "Seasoned": styles.COLOR_RARITY_RARE_VAR, # Variant
        "Hooked": styles.COLOR_RARITY_RARE,

        # --- Legendary (Orange) ---
        "Finished": styles.COLOR_RARITY_LEGENDARY,
        "Invested": styles.COLOR_RARITY_LEGENDARY_VAR, # Variant
        "Played": styles.COLOR_RARITY_LEGENDARY,

        # --- Set (Green) ---
        "Completionist": styles.COLOR_RARITY_SET,
        "Mastered": styles.COLOR_RARITY_SET_VAR, # Variant

        # --- Junk (Brown/Rust) ---
        "Shelved": styles.COLOR_RARITY_JUNK,
        "Abandoned": styles.COLOR_RARITY_JUNK_VAR, # Variant
        "Bounced": styles.COLOR_RARITY_JUNK,
    }
    # Return mapped color or default to Primary Text Color
    return color_map.get(status, styles.COLOR_TEXT_PRIMARY)

def get_roast_asset(status_text):
    """
    Maps the Agent's wild text output to a safe local asset.
    Case-insensitive and fault-tolerant.
    """
    # Normalize the input (Agent might say "Hoarder" or "HOARDER" or "Status: Hoarder")
    key = status_text.upper().strip()

    # Define the strict mapping
    assets = {
        "HOARDER": "assets/cards/hoarder.png",
        "CASUAL": "assets/cards/casual.png",
        "BROKE": "assets/cards/broke.png",
        "HARDCORE": "assets/cards/hardcore.png",
        "ROASTED": "assets/cards/roasted.png",
        "DEFAULT": "assets/cards/default.png"
    }

    # Return the specific asset, or the Clean card if the Agent invents a new status
    return assets.get(key, "assets/cards/default.png")
