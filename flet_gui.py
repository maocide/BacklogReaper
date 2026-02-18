import flet as ft
import startup
import styles
from ui.tabs.dashboard import DashboardView
from ui.tabs.chat import ReaperChatView
from ui.tabs.library import LibraryView
from ui.tabs.settings import SettingsView

def main(page: ft.Page):
    page.title = "Backlog Reaper"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 1280
    page.window.height = 800
    page.bgcolor = styles.COLOR_BACKGROUND
    page.padding = 0

    page.fonts = {
        "Cinzel": "fonts/Cinzel-VariableFont_wght.ttf"
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

    # 0. GATEKEEPER CHECK
    is_ready, failures = startup.check_all()
    if not is_ready:
        print("STARTUP CHECKS FAILED:")
        for f in failures:
            print(f" - {f}")
        page.show_dialog(ft.SnackBar(ft.Text("Chat history copied to clipboard!")))
        page.update()

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
        index = e.control.selected_index
        view_dashboard.visible = (index == 0)
        view_chat.visible = (index == 1)
        view_library.visible = (index == 2)
        view_settings.visible = (index == 3)
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

    page.add(
        ft.Row(
            [
                rail,
                ft.VerticalDivider(width=1, color=styles.COLOR_BORDER_BRONZE),
                view_dashboard,
                view_chat,
                view_library,
                view_settings
            ],
            expand=True,
        )
    )

if __name__ == "__main__":
    ft.run(main,  assets_dir="assets")
