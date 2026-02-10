import flet as ft
import webbrowser

def launch_game(appid):
    """Launches the game using the steam protocol."""
    try:
        url = f"steam://run/{appid}"
        print(f"Launching: {url}")
        webbrowser.open(url)
    except Exception as e:
        print(f"Error launching game: {e}")

def get_status_color(status):
    """Returns the color corresponding to a game status."""
    color_map = {
        # Simplified Chart Categories
        "Backlog": ft.Colors.GREY_500,  # Unplayed
        "Trying": ft.Colors.AMBER_400,  # Testing, Bounced
        "Active": ft.Colors.BLUE_400,   # Started, Seasoned, Hooked
        "Finished": ft.Colors.GREEN_400,# Invested, Completionist, Played
        "Shelved": ft.Colors.BROWN_400, # Abandoned, Forgotten, Mastered

        # Detailed Game Card Categories (Fallback to related simplified color)
        "Unplayed": ft.Colors.GREY_500,

        "Testing": ft.Colors.AMBER_400,
        "Bounced": ft.Colors.DEEP_ORANGE_400, # Distinction: Orange for bounced

        "Started": ft.Colors.BLUE_200,
        "Seasoned": ft.Colors.BLUE_600,
        "Hooked": ft.Colors.PURPLE_400, # Distinction: Purple for endless/multi

        "Invested": ft.Colors.GREEN_300,
        "Completionist": ft.Colors.GREEN_500,
        "Played": ft.Colors.TEAL_400, # Distinction: Teal for generic played

        "Abandoned": ft.Colors.BROWN_400,
        "Forgotten": ft.Colors.BROWN_200,
        "Mastered": ft.Colors.DEEP_PURPLE_400 # Distinction: Deep Purple for shelved master
    }
    return color_map.get(status, ft.Colors.WHITE)

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
