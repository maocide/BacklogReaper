import threading
import traceback
import flet as ft

import vault
import settings
import styles
from ui.utils import get_status_color
from vibe_engine import VibeEngine
from ui.widgets.styled_inputs import GrimoireButton

class LibraryView(ft.BaseControl):
    def __init__(self):
        super().__init__()
        self.gf_table = ft.Ref[ft.DataTable]()
        self.gf_status = ft.Ref[ft.Text]()
        self.gf_btn_fetch = ft.Ref[ft.FilledButton]()
        self.gf_btn_stop = ft.Ref[ft.FilledButton]()
        self.stop_event_gf = threading.Event()

    def build(self):
        BUTTON_STYLE = ft.ButtonStyle(
            color=styles.COLOR_TEXT_GOLD,
            bgcolor=styles.COLOR_SURFACE,
            shape=ft.RoundedRectangleBorder(radius=5),
            side=ft.BorderSide(1, styles.COLOR_BORDER_BRONZE)
        )

        return ft.Column(
            expand=True,
            controls=[
                ft.Text("Game List Fetcher", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM, font_family="Cinzel"),
                ft.Row([
                    GrimoireButton(ref=self.gf_btn_fetch, text="Fetch Games", icon=ft.Icons.DOWNLOAD, on_click=self.start_fetch),
                    GrimoireButton(ref=self.gf_btn_stop, text="Stop", icon=ft.Icons.STOP, on_click=self.stop_fetch, disabled=True),
                ]),
                ft.Text(ref=self.gf_status, value="Ready", color=styles.COLOR_TEXT_SECONDARY),
                ft.Divider(),
                ft.Container(
                    content=ft.Column([
                        ft.DataTable(
                            ref=self.gf_table,
                            sort_column_index=2, # Default sort by Playtime
                            sort_ascending=False,
                            columns=[
                                ft.DataColumn(ft.Text("AppID", color=styles.COLOR_TEXT_PRIMARY), numeric=True, on_sort=self.sort_table),
                                ft.DataColumn(ft.Text("Name", color=styles.COLOR_TEXT_PRIMARY), on_sort=self.sort_table),
                                ft.DataColumn(ft.Text("Playtime (h)", color=styles.COLOR_TEXT_PRIMARY), numeric=True, on_sort=self.sort_table),
                                ft.DataColumn(ft.Text("Main Story (h)", color=styles.COLOR_TEXT_PRIMARY), numeric=True, on_sort=self.sort_table),
                                ft.DataColumn(ft.Text("Completionist (h)", color=styles.COLOR_TEXT_PRIMARY), numeric=True, on_sort=self.sort_table),
                                ft.DataColumn(ft.Text("Status", color=styles.COLOR_TEXT_PRIMARY), on_sort=self.sort_table),
                            ],
                            rows=[],
                            vertical_lines=ft.BorderSide(1, styles.COLOR_BORDER_BRONZE),
                            horizontal_lines=ft.BorderSide(1, styles.COLOR_ACCENT_DIM),
                            heading_row_color=styles.COLOR_ACCENT_DIM,
                            data_row_color=styles.COLOR_SURFACE,
                            data_text_style=ft.TextStyle(color=styles.COLOR_TEXT_PRIMARY),
                        )
                    ], scroll=ft.ScrollMode.AUTO), # Scrollable container for the table
                    expand=True,
                    bgcolor=styles.COLOR_SURFACE,
                    border=ft.border.all(1, styles.COLOR_BORDER_BRONZE),
                    border_radius=5,
                    padding=10
                )
            ]
        )

    def did_mount(self):
        # We need to subscribe to fetch status updates
        self.page.pubsub.subscribe(self.on_fetch_message)

    def will_unmount(self):
        self.page.pubsub.unsubscribe(self.on_fetch_message)

    def update_data_sources(self):
        vault.update(settings.STEAM_USER)
        vibes = VibeEngine.get_instance()
        vibes.ingest_library()

    def run_fetch_thread(self, username):
        try:
            if self.stop_event_gf.is_set(): return

            self.page.pubsub.send_all({"type": "fetch_status", "content": f"Opening the Vault for {username}..."})

            force_update = False

            # FETCH FROM DB
            game_count = vault.get_games_count()

            if game_count == 0 or force_update:
                # UPDATE THE DB
                self.update_data_sources()

            if self.stop_event_gf.is_set(): return

            self.page.pubsub.send_all({"type": "fetch_status", "content": "Reading from Vault..."})

            # FETCH FROM DB
            games_list = vault.get_all_games()

            if not games_list:
                self.page.pubsub.send_all({"type": "fetch_error", "content": "Vault is empty. Something went wrong."})
                return

            # POPULATE UI TABLE ---
            rows = []
            for game in games_list:
                status = vault.calculate_status(game)

                playtime_min = game.get('playtime_forever', 0)
                playtime_hrs = round(playtime_min / 60.0, 1)

                hltb_main = game.get('hltb_main', 0)
                hltb_comp = game.get('hltb_completionist', 0)

                hltb_main_hrs = round(hltb_main / 60.0, 1) if hltb_main > 0 else 0
                hltb_comp_hrs = round(hltb_comp / 60.0, 1) if hltb_comp > 0 else 0

                cells = [
                    ft.DataCell(ft.Text(str(game['appid']))),
                    ft.DataCell(ft.Container(content=ft.Text(game['name'], overflow=ft.TextOverflow.ELLIPSIS), width=300)),
                    ft.DataCell(ft.Text(f"{playtime_hrs} h"), data=playtime_hrs),
                    ft.DataCell(ft.Text(str(hltb_main_hrs) if hltb_main_hrs > 0 else "-"), data=hltb_main_hrs),
                    ft.DataCell(ft.Text(str(hltb_comp_hrs) if hltb_comp_hrs > 0 else "-"), data=hltb_comp_hrs),
                    ft.DataCell(ft.Text(status, color=get_status_color(status))),
                ]
                rows.append(ft.DataRow(cells=cells))

            self.page.pubsub.send_all({"type": "fetch_complete", "data": rows, "count": len(games_list)})

        except Exception as e:
            traceback.print_exc()
            self.page.pubsub.send_all({"type": "fetch_complete", "error": f"Error: {e}"})

    def on_fetch_message(self, message):
        msg_type = message.get("type")
        content = message.get("content")

        if msg_type == "fetch_status":
            if self.gf_status.current:
                self.gf_status.current.value = content
                self.gf_status.current.color = styles.COLOR_TEXT_SECONDARY
                self.gf_status.current.update()

        elif msg_type == "fetch_complete":
            if "data" in message:
                rows = message.get("data")
                count = message.get("count")
                if self.gf_table.current:
                    self.gf_table.current.rows = rows
                    self.gf_table.current.update()
                if self.gf_status.current:
                    self.gf_status.current.value = f"Vault loaded. {count} games found."
                    self.gf_status.current.color = styles.COLOR_TEXT_SECONDARY
                    self.gf_status.current.update()

            if "error" in message:
                error_msg = message.get("error")
                if self.gf_status.current:
                    self.gf_status.current.value = error_msg
                    self.gf_status.current.color = styles.COLOR_ERROR
                    self.gf_status.current.update()

            if self.gf_btn_fetch.current:
                self.gf_btn_fetch.current.disabled = False
                self.gf_btn_fetch.current.update()
            if self.gf_btn_stop.current:
                self.gf_btn_stop.current.disabled = True
                self.gf_btn_stop.current.update()

        elif msg_type == "fetch_error": # Added handler for fetch_error used in run_fetch_thread
             if self.gf_status.current:
                self.gf_status.current.value = content
                self.gf_status.current.color = styles.COLOR_ERROR
                self.gf_status.current.update()

    def start_fetch(self, e):
        username = settings.STEAM_USER

        if not username:
            self.gf_status.current.value = "Please configure Steam Username in Settings."
            self.page.snack_bar = ft.SnackBar(ft.Text("Please configure Steam Username in Settings!"))
            self.page.snack_bar.open = True
            self.page.update()
            return

        if not settings.STEAM_API_KEY:
             self.gf_status.current.value = "Please configure Steam API Key in Settings."
             self.page.snack_bar = ft.SnackBar(ft.Text("Please configure Steam API Key in Settings!"))
             self.page.snack_bar.open = True
             self.page.update()
             return

        self.stop_event_gf.clear()
        self.gf_btn_fetch.current.disabled = True
        self.gf_btn_stop.current.disabled = False
        self.gf_table.current.rows.clear()
        self.gf_status.current.value = "Starting fetch..."
        self.update()

        if hasattr(self.page, 'run_thread'):
             self.page.run_thread(self.run_fetch_thread, username)
        else:
             threading.Thread(target=self.run_fetch_thread, args=(username,), daemon=True).start()

    def stop_fetch(self, e):
        self.stop_event_gf.set()
        self.gf_status.current.value = "Stopping..."
        self.gf_status.current.color = styles.COLOR_TEXT_SECONDARY
        self.gf_status.current.update()

    def sort_table(self, e):
        try:
            col_index = e.column_index
            ascending = e.ascending

            self.gf_table.current.sort_column_index = col_index
            self.gf_table.current.sort_ascending = ascending

            rows = self.gf_table.current.rows

            def get_cell_value(row, index):
                content = row.cells[index].content
                if hasattr(content, "data") and content.data is not None:
                    return content.data
                if isinstance(content, ft.Text):
                    val = content.value
                    if index == 2:
                        return float(val.replace(" h", "").replace(",", "")) if val.replace(" h", "").replace(",", "").replace(".", "").isdigit() else 0
                    if index in [3, 4]:
                        return float(val) if val != "-" and val.replace(".", "").isdigit() else -1
                    return val.lower()
                return ""

            rows.sort(key=lambda x: get_cell_value(x, col_index), reverse=not ascending)

            self.gf_table.current.update()
        except Exception as ex:
             print(f"Sort Error: {ex}")
             traceback.print_exc()
