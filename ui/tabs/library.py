import threading
import traceback
import math
import flet as ft

import vault
import settings
import styles
from ui.utils import get_status_color
from vibe_engine import VibeEngine
from ui.widgets.styled_inputs import GrimoireButton, GrimoireProgressBar

class LibraryView(ft.Container):
    def __init__(self):
        super().__init__()
        self.expand = True
        self.padding = ft.Padding(0, 5, 5, 10)

        # State
        self.all_games_data = []
        self.current_page = 0
        self.page_size = 15
        self.sort_col_index = 2 # Playtime by default
        self.sort_ascending = False

        # Refs
        self.gf_table = ft.Ref[ft.DataTable]()
        self.gf_status = ft.Ref[ft.Text]()
        self.gf_progress = ft.Ref[ft.Container]() # Ref to the Container wrapping the bar
        self.gf_btn_update = ft.Ref[ft.FilledButton]()
        self.gf_page_info = ft.Ref[ft.Text]()
        self.gf_btn_prev = ft.Ref[ft.IconButton]()
        self.gf_btn_next = ft.Ref[ft.IconButton]()

        self.content = ft.Column([
            ft.Row([
                ft.Text("Grimoire Library", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM, expand=True, font_family="Cinzel"),
                GrimoireButton(ref=self.gf_btn_update, text="Update Library", icon=ft.Icons.REFRESH, on_click=self.start_update_click),
            ]),
            ft.Text(ref=self.gf_status, value="Ready", color=styles.COLOR_TEXT_SECONDARY, size=12),
            GrimoireProgressBar(ref=self.gf_progress, width=None, visible=False), # Full width by default in column if not constrained
            ft.Divider(),
            # Table Container
            ft.Container(
                content=ft.Column([
                    ft.DataTable(
                        ref=self.gf_table,
                        sort_column_index=self.sort_col_index,
                        sort_ascending=self.sort_ascending,
                        columns=[
                            ft.DataColumn(label=ft.Text("AppID", color=styles.COLOR_TEXT_PRIMARY), numeric=True, on_sort=self.handle_sort),
                            ft.DataColumn(label=ft.Text("Name", color=styles.COLOR_TEXT_PRIMARY), on_sort=self.handle_sort),
                            ft.DataColumn(label=ft.Text("Playtime (h)", color=styles.COLOR_TEXT_PRIMARY), numeric=True, on_sort=self.handle_sort),
                            ft.DataColumn(label=ft.Text("Main Story (h)", color=styles.COLOR_TEXT_PRIMARY), numeric=True, on_sort=self.handle_sort),
                            ft.DataColumn(label=ft.Text("Completionist (h)", color=styles.COLOR_TEXT_PRIMARY), numeric=True, on_sort=self.handle_sort),
                            ft.DataColumn(label=ft.Text("Status", color=styles.COLOR_TEXT_PRIMARY), on_sort=self.handle_sort),
                        ],
                        rows=[],
                        vertical_lines=ft.BorderSide(1, styles.COLOR_BORDER_BRONZE),
                        horizontal_lines=ft.BorderSide(1, styles.COLOR_ACCENT_DIM),
                        heading_row_color=styles.COLOR_ACCENT_DIM,
                        data_row_color=styles.COLOR_SURFACE,
                        data_text_style=ft.TextStyle(color=styles.COLOR_TEXT_PRIMARY),
                    )
                ], scroll=ft.ScrollMode.AUTO),
                expand=True,
                bgcolor=styles.COLOR_SURFACE,
                border=ft.border.all(1, styles.COLOR_BORDER_BRONZE),
                border_radius=5,
                padding=10
            ),
            # Pagination Controls
            ft.Row([
                ft.IconButton(ref=self.gf_btn_prev, icon=ft.Icons.CHEVRON_LEFT, on_click=self.prev_page_click, disabled=True),
                ft.Text(ref=self.gf_page_info, value="Page 1 of 1"),
                ft.IconButton(ref=self.gf_btn_next, icon=ft.Icons.CHEVRON_RIGHT, on_click=self.next_page_click, disabled=True),
            ], alignment=ft.MainAxisAlignment.CENTER)
        ])

    def did_mount(self):
        self.page.pubsub.subscribe(self.on_update_message)
        # Load data immediately
        self.load_data()

    def will_unmount(self):
        self.page.pubsub.unsubscribe(self.on_update_message)

    def load_data(self):
        """Loads data from Vault (DB) into memory and renders the table."""
        try:
            self.all_games_data = vault.get_all_games()
            self.current_page = 0
            self.render_table()

            if self.gf_status.current:
                self.gf_status.current.value = f"Loaded {len(self.all_games_data)} games from Vault."
                self.gf_status.current.update()

        except Exception as e:
            traceback.print_exc()
            if self.gf_status.current:
                self.gf_status.current.value = f"Error loading data: {e}"
                self.gf_status.current.update()

    def render_table(self):
        """Sorts, slices, and updates the UI table."""
        if not self.all_games_data:
            if self.gf_table.current:
                self.gf_table.current.rows = []
                self.gf_table.current.update()
            self.update_pagination_controls(0)
            return

        # 1. Sort
        def get_sort_key(game):
            # Columns: 0=AppID, 1=Name, 2=Playtime, 3=Main, 4=Comp, 5=Status
            try:
                if self.sort_col_index == 0: return game.get('appid') or 0
                if self.sort_col_index == 1: return (game.get('name') or "").lower()
                if self.sort_col_index == 2: return game.get('playtime_forever') or 0
                if self.sort_col_index == 3: return float(game.get('hltb_main') or 0)
                if self.sort_col_index == 4: return float(game.get('hltb_completionist') or 0)
                if self.sort_col_index == 5: return vault.calculate_status(game)
            except Exception:
                return 0
            return 0

        self.all_games_data.sort(key=get_sort_key, reverse=not self.sort_ascending)

        # 2. Slice
        total_items = len(self.all_games_data)
        total_pages = math.ceil(total_items / self.page_size)
        if total_pages == 0: total_pages = 1

        # Clamp page
        if self.current_page >= total_pages: self.current_page = total_pages - 1
        if self.current_page < 0: self.current_page = 0

        start_idx = self.current_page * self.page_size
        end_idx = start_idx + self.page_size
        slice_data = self.all_games_data[start_idx:end_idx]

        # 3. Build Rows
        rows = []
        for game in slice_data:
            status = vault.calculate_status(game)

            playtime_min = game.get('playtime_forever', 0)
            playtime_hrs = round(playtime_min / 60.0, 1)

            try:
                hltb_main = float(game.get('hltb_main') or 0)
            except (ValueError, TypeError):
                hltb_main = 0

            try:
                hltb_comp = float(game.get('hltb_completionist') or 0)
            except (ValueError, TypeError):
                hltb_comp = 0

            hltb_main_hrs = round(hltb_main / 60.0, 1) if hltb_main > 0 else 0
            hltb_comp_hrs = round(hltb_comp / 60.0, 1) if hltb_comp > 0 else 0

            cells = [
                ft.DataCell(ft.Text(str(game['appid']))),
                ft.DataCell(ft.Text(game['name'], overflow=ft.TextOverflow.ELLIPSIS, width=300, tooltip=game['name'])),
                ft.DataCell(ft.Text(f"{playtime_hrs} h")),
                ft.DataCell(ft.Text(str(hltb_main_hrs) if hltb_main_hrs > 0 else "-")),
                ft.DataCell(ft.Text(str(hltb_comp_hrs) if hltb_comp_hrs > 0 else "-")),
                ft.DataCell(ft.Text(status, color=get_status_color(status))),
            ]
            rows.append(ft.DataRow(cells=cells))

        if self.gf_table.current:
            self.gf_table.current.rows = rows
            self.gf_table.current.sort_column_index = self.sort_col_index
            self.gf_table.current.sort_ascending = self.sort_ascending
            self.gf_table.current.update()

        self.update_pagination_controls(total_pages)

    def update_pagination_controls(self, total_pages):
        if self.gf_page_info.current:
            self.gf_page_info.current.value = f"Page {self.current_page + 1} of {total_pages}"
            self.gf_page_info.current.update()

        if self.gf_btn_prev.current:
            self.gf_btn_prev.current.disabled = (self.current_page == 0)
            self.gf_btn_prev.current.update()

        if self.gf_btn_next.current:
            self.gf_btn_next.current.disabled = (self.current_page >= total_pages - 1)
            self.gf_btn_next.current.update()

    def handle_sort(self, e):
        self.sort_col_index = e.column_index
        self.sort_ascending = e.ascending
        self.render_table()

    def prev_page_click(self, e):
        if self.current_page > 0:
            self.current_page -= 1
            self.render_table()

    def next_page_click(self, e):
        # We need total pages to check upper bound, render_table handles clamping effectively but let's be safe
        total_items = len(self.all_games_data)
        total_pages = math.ceil(total_items / self.page_size)

        if self.current_page < total_pages - 1:
            self.current_page += 1
            self.render_table()

    # --- UPDATE THREAD ---

    def run_update_thread(self, username):
        try:
            self.page.pubsub.send_all({"type": "update_status", "content": f"Syncing Vault for {username}..."})

            # 1. Update Vault (API calls)
            vault.update(username)

            # 2. Ingest into Vibe Engine (Vector DB)
            vibes = VibeEngine.get_instance()
            vibes.ingest_library()

            self.page.pubsub.send_all({"type": "update_complete"})

        except Exception as e:
            traceback.print_exc()
            self.page.pubsub.send_all({"type": "update_error", "content": str(e)})

    def start_update_click(self, e):
        username = settings.STEAM_USER
        if not username:
             self.page.show_dialog(ft.SnackBar(ft.Text("Please configure Steam Username in Settings!")))
             self.page.update()
             return

        if not settings.STEAM_API_KEY:
             self.page.show_dialog(ft.SnackBar(ft.Text("Please configure Steam API Key in Settings!")))
             self.page.update()
             return

        self.gf_btn_update.current.disabled = True
        self.gf_btn_update.current.update()

        # Show Progress
        if self.gf_progress.current:
            self.gf_progress.current.visible = True
            self.gf_progress.current.update()

        if hasattr(self.page, 'run_thread'):
             self.page.run_thread(self.run_update_thread, username)
        else:
             threading.Thread(target=self.run_update_thread, args=(username,), daemon=True).start()

    def on_update_message(self, message):
        msg_type = message.get("type")
        content = message.get("content")

        if msg_type == "update_status":
            if self.gf_status.current:
                self.gf_status.current.value = content
                self.gf_status.current.color = styles.COLOR_TEXT_SECONDARY
                self.gf_status.current.update()

        elif msg_type == "update_complete":
            # Refresh data from DB
            self.load_data()
            if self.gf_btn_update.current:
                self.gf_btn_update.current.disabled = False
                self.gf_btn_update.current.update()
            if self.gf_status.current:
                self.gf_status.current.value = "Library updated successfully."
                self.gf_status.current.color = styles.COLOR_TEXT_SECONDARY
                self.gf_status.current.update()

            # Hide Progress
            if self.gf_progress.current:
                self.gf_progress.current.visible = False
                self.gf_progress.current.update()

        elif msg_type == "update_error":
            if self.gf_status.current:
                self.gf_status.current.value = f"Error: {content}"
                self.gf_status.current.color = styles.COLOR_ERROR
                self.gf_status.current.update()
            if self.gf_btn_update.current:
                self.gf_btn_update.current.disabled = False
                self.gf_btn_update.current.update()

            # Hide Progress
            if self.gf_progress.current:
                self.gf_progress.current.visible = False
                self.gf_progress.current.update()
