import flet as ft
import webbrowser
import os
import styles
import subprocess
import platform
import paths

import sys

def get_markdown_newline():
    """Returns a cross-platform friendly newline sequence for Markdown."""
    if sys.platform == 'win32':
        return "  \r\n\r\n"
    return "  \n\n"

def get_clipboard_newline():
    """Returns a native newline sequence for clipboard copying."""
    if sys.platform == 'win32':
        return "\r\n\r\n"
    return "\n\n"

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
        # Common (Grey/White)
        "Backlog": styles.COLOR_RARITY_COMMON,
        "Unplayed": styles.COLOR_RARITY_COMMON,
        "Forgotten": styles.COLOR_RARITY_COMMON_VAR, # Variant for distinction

        # Magic (Blue)
        "Trying": styles.COLOR_RARITY_MAGIC,
        "Testing": styles.COLOR_RARITY_MAGIC_VAR, # Variant
        "Started": styles.COLOR_RARITY_MAGIC,

        # Rare (Yellow/Gold)
        "Active": styles.COLOR_RARITY_RARE,
        "Seasoned": styles.COLOR_RARITY_RARE_VAR, # Variant
        "Hooked": styles.COLOR_RARITY_RARE,

        # Legendary (Orange)
        "Finished": styles.COLOR_RARITY_LEGENDARY,
        "Invested": styles.COLOR_RARITY_LEGENDARY_VAR, # Variant
        "Played": styles.COLOR_RARITY_LEGENDARY,

        # Set (Green)
        "Completionist": styles.COLOR_RARITY_SET,
        "Mastered": styles.COLOR_RARITY_SET_VAR, # Variant

        # Junk (Brown/Rust)
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
        "HOARDER": str(paths.get_asset_path("assets", "cards", "hoarder.png")),
        "CASUAL": str(paths.get_asset_path("assets", "cards", "casual.png")),
        "BROKE": str(paths.get_asset_path("assets", "cards", "broke.png")),
        "HARDCORE": str(paths.get_asset_path("assets", "cards", "hardcore.png")),
        "ROASTED": str(paths.get_asset_path("assets", "cards", "roasted.png")),
        "DEFAULT": str(paths.get_asset_path("assets", "cards", "default.png"))
    }

    # Return the specific asset, or the Clean card if the Agent invents a new status
    return assets.get(key, str(paths.get_asset_path("assets", "cards", "default.png")))

def mix_color(color1, color2, weight=0.5):
    """
    Mixes two hex colors.
    :param color1: Hex string (e.g. "#RRGGBB")
    :param color2: Hex string (e.g. "#RRGGBB")
    :param weight: Float between 0.0 and 1.0 (weight of color1)
    :return: Mixed hex string
    """
    def hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 3:
            hex_color = ''.join([c*2 for c in hex_color])
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    def rgb_to_hex(rgb):
        return '#{:02x}{:02x}{:02x}'.format(*rgb)

    rgb1 = hex_to_rgb(color1)
    rgb2 = hex_to_rgb(color2)

    mixed_rgb = tuple(
        int(c1 * weight + c2 * (1 - weight))
        for c1, c2 in zip(rgb1, rgb2)
    )

    return rgb_to_hex(mixed_rgb)
