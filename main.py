import flet as ft
import sys
import os
import core.paths as paths
import core.settings as settings
import os
import sys
import certifi
import core.paths as paths
import core.startup as startup
import ui.styles as styles
from ui.tabs.dashboard import DashboardView
from ui.tabs.chat import ReaperChatView
from ui.tabs.library import LibraryView
from ui.tabs.settings import SettingsView
from ui.gatekeeper import GatekeeperView

# Force Python requests and urllib to use certifi's CA bundle
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

# Fix Windows encoding crashes and setup a Debug Log for the Sandbox
if paths.is_packaged():
    # Create a path for a log file inside your local data folder
    log_path = paths.get_asset_path("data", "reaper_debug.log")

    # Ensure the directory exists
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    # Open the file in append mode so it doesn't overwrite immediately on quick restarts
    debug_log = open(log_path, "a", encoding="utf-8")

    sys.stdout = debug_log
    sys.stderr = debug_log

    print("\n" + "=" * 40)
    print("💀 REAPER EXECUTABLE INITIATED")
    print("=" * 40)


def main(page: ft.Page):
    page.title = f"Backlog Reaper [{settings.APP_VERSION}]"

    # Platform-specific icon handling
    if sys.platform == "win32":
        page.window.icon = "reaper_icon.ico"
    else:
        # Use path resolution for bundled assets
        icon_path = paths.get_asset_path("assets", "reaper_icon.png")
        if icon_path.exists():
            page.window.icon = str(icon_path)
        else:
            page.window.icon = "reaper_icon.png"

    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 1280
    page.window.height = 800
    page.bgcolor = styles.COLOR_BACKGROUND
    page.padding = 0

    page.fonts = {
        styles.FONT_HEADING: "fonts/Cinzel-VariableFont_wght.ttf"
    }

    page.theme = ft.Theme(
        font_family=styles.FONT_BODY,
        scrollbar_theme=ft.ScrollbarTheme(
            thumb_color={
                ft.ControlState.HOVERED: styles.COLOR_TEXT_GOLD,
                ft.ControlState.DEFAULT: styles.COLOR_BORDER_BRONZE,
            },
            track_color=styles.COLOR_SURFACE,
            thickness=5,
            radius=10,
        )
    )

    page.window.minimizable = True
    page.window.maximizable = True
    page.window.closable = True
    page.window.frameless = False
    page.window.title_bar_hidden = False
    page.window.title_bar_buttons_hidden = False

    # STARTUP CHECKS
    # We still run checks for HLTB/DB, but Gatekeeper handles Steam Keys.
    paths.ensure_dirs()  # Ensure directories exist
    is_ready, failures = startup.check_all()
    if not is_ready:
        print("STARTUP CHECKS WARNINGS:")
        for f in failures:
            print(f" - {f}")
        # We don't block execution here, as Gatekeeper might fix API keys,
        # and HLTB/DB issues might be resolved later or are non-fatal.

    # Initialize Views
    view_dashboard = DashboardView()
    view_chat = ReaperChatView()
    view_library = LibraryView()
    view_settings = SettingsView()

    # Initial Visibility
    view_dashboard.visible = True
    view_chat.visible = False
    view_library.visible = False
    view_settings.visible = False

    # Navigation Logic
    def on_nav_change(e):
        settings.reload()
        index = e.control.selected_index

        is_chat_tab = (index == 1)
        is_settings_tab = (index == 3)

        view_dashboard.visible = (index == 0)
        view_chat.visible = (index == 1)
        view_library.visible = (index == 2)
        view_settings.visible = (index == 3)

        # Refresh char selection and chat status
        if is_chat_tab:
            view_chat.refresh_state()

        if is_settings_tab:
            view_settings.refresh_state()

        page.update()

    rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=100,
        min_extended_width=400,
        group_alignment=-0.9,
        bgcolor=styles.COLOR_SURFACE,
        indicator_color=styles.COLOR_TEXT_GOLD,
        destinations=[
            ft.NavigationRailDestination(
                icon=ft.Icons.PIE_CHART_OUTLINE,
                selected_icon=ft.Icons.PIE_CHART,
                label="Dashboard"
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.CHAT_BUBBLE_OUTLINE,
                selected_icon=ft.Icons.CHAT_BUBBLE,
                label="Reaper Chat"
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.LIST_ALT_OUTLINED,
                selected_icon=ft.Icons.LIST_ALT,
                label="My Backlog"
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.SETTINGS_OUTLINED,
                selected_icon=ft.Icons.SETTINGS,
                label="Settings"
            ),
        ],
        on_change=on_nav_change,
    )

    # Main App Layout (Hidden Initially)
    main_layout = ft.Row(
        [
            rail,
            ft.VerticalDivider(width=1, color=styles.COLOR_BORDER_BRONZE),
            view_dashboard,
            view_chat,
            view_library,
            view_settings
        ],
        expand=True,
        visible=False  # Initially hidden until Gatekeeper ritual is complete
    )

    def on_ritual_complete():
        # Force a settings reload to ensure any new Steam User is loaded
        settings.reload()

        # Transition: Hide Gatekeeper, Show Main App
        gatekeeper.visible = False
        main_layout.visible = True

        # Refresh Views to reflect any new data from the ritual
        view_dashboard.load_stats()
        view_library.load_data()
        view_chat.refresh_state()

        page.update()

    # Initialize Gatekeeper
    gatekeeper = GatekeeperView(on_complete=on_ritual_complete)

    # Use a Stack to layer them (Gatekeeper on top implicitly by visibility, or explicitly)
    # Since main_layout is visible=False, it won't render.
    # Gatekeeper is visible=True by default.
    page.add(
        ft.Stack(
            [
                main_layout,
                gatekeeper
            ],
            expand=True
        )
    )


if __name__ == "__main__":
    # Force an absolute path to the assets folder using paths.py logic
    assets_path = str(paths.get_asset_path("assets"))

    # Pass the absolute path to Flet
    ft.run(main, assets_dir=assets_path)
