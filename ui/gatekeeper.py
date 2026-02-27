import asyncio
import queue
import threading
import time
import flet as ft
from PIL.ImageOps import expand
from flet import WindowEventType

import settings
import styles
import ui.utils
import vault
from ui.widgets.styled_inputs import GrimoireButton, GrimoireTextField, GrimoireProgressBar
from vibe_engine import VibeEngine


class GatekeeperView(ft.Container):
    def __init__(self, on_complete=None):
        super().__init__()
        self.expand = True
        self.on_complete = on_complete
        self.alignment = ft.Alignment.CENTER
        self.bgcolor = styles.COLOR_BACKGROUND
        self.txt_life_wasted = ft.Ref[ft.Text]()

        self.stop_event = threading.Event()


        # STATE 1: THE CONTRACT (Inputs)
        self.tf_steam_id = GrimoireTextField(
            label="Steam Username",
            hint_text="e.g. 'GabeNewell69'",
            width=400
        )
        self.tf_api_key = GrimoireTextField(
            label="Steam API Key",
            password=True,
            can_reveal_password=True,
            width=400,
        )
        self.btn_initiate = GrimoireButton(
            text="Initiate Ritual",
            width=200,
            height=50,
            on_click=self._on_initiate_click
        )
        # Helper link
        self.link_api_key = ft.Text(
            width=400,
            text_align=ft.TextAlign.RIGHT,  # Aligns it neatly under the right edge of the input
            spans=[
                ft.TextSpan(
                    "Obtain a key from Lord Gaben",
                    url="https://steamcommunity.com/dev/apikey",
                    style=ft.TextStyle(
                        color=styles.COLOR_TEXT_GOLD,
                        size=12,
                        italic=True,
                        decoration=ft.TextDecoration.UNDERLINE
                    )
                )
            ]
        )

        # The inner content column
        contract_content = ft.Column(
            controls=[
                ft.Text("Sign the Ledger", size=40, font_family=styles.FONT_HEADING, color=styles.COLOR_TEXT_GOLD),
                ft.Container(height=20),
                self.tf_steam_id,
                self.tf_api_key,
                self.link_api_key,
                ft.Container(height=20),
                self.btn_initiate
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        )

        # The "Obsidian Plaque" Wrapper (Glassmorphism effect)
        self.container_contract = ft.Container(
            content=contract_content,
            bgcolor=ft.Colors.with_opacity(0.10, styles.COLOR_SURFACE),
            border=ft.border.all(1, styles.COLOR_TEXT_GOLD),
            border_radius=12,
            padding=ft.padding.all(40),
            blur=ft.Blur(6, 6),  # Frosted glass over the background image
            width=500,
            shadow=ft.BoxShadow(
                blur_radius=50,
                color=ft.Colors.with_opacity(0.5, ft.Colors.BLACK),
                offset=ft.Offset(0, 10)
            ),
            visible=True
        )

        # STATE 2: THE RITUAL (Sync)
        # Changed to "Life Wasted" and swapped Red for Orange/Gold
        self.txt_total_debt = ft.Text("Life Wasted: 0 Hours", size=30, color=styles.COLOR_TEXT_GOLD, font_family=styles.FONT_HEADING, weight=ft.FontWeight.BOLD, ref=self.txt_life_wasted)
        self.progress_bar = GrimoireProgressBar(width=400, height=20)
        self.log_lines = []
        self.txt_log = ft.Text(
            "> Awaiting invocation...",
            font_family=styles.STYLE_MONOSPACE,
            # Fallback to grey if COLOR_SYSTEM_LOG isn't defined yet
            color=getattr(styles, 'COLOR_SYSTEM_LOG', ft.Colors.GREY_500),
            size=12,
            text_align=ft.TextAlign.LEFT,
        )

        self.container_ritual = ft.Column(
            controls=[
                self.txt_total_debt,
                ft.Container(height=20),
                self.progress_bar,
                ft.Container(height=10),
                ft.Container(
                    content=self.txt_log,
                    width=600,
                    height=250,
                    alignment=ft.Alignment.TOP_LEFT,
                )
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            visible=False
        )

        # BACKGROUND
        self.background_image = ft.Image(
            src="assets/gatekeeper_bg.png",
            fit=ft.BoxFit.COVER, # Flet 0.80+
            opacity=0.3,
            error_content=ft.Container(bgcolor=styles.COLOR_BACKGROUND)
        )

        # MAIN LAYOUT
        self.content = ft.Stack(
            fit=ft.StackFit.EXPAND,
            controls=[
                self.background_image,
                ft.Container(
                    bgcolor=getattr(styles, 'COLOR_TRANSLUCENT', ft.Colors.TRANSPARENT),
                    expand=True
                ),
                # The Centering Wrapper: Prevents the Stack from pinning content to top-left
                ft.Container(
                    expand=True,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Column(
                        controls=[
                            self.container_contract,
                            self.container_ritual
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    )
                )
            ],
            expand=True
        )

    def did_mount(self):
        # Auto-check credentials
        if settings.STEAM_USER and settings.STEAM_API_KEY:
            self.tf_steam_id.value = settings.STEAM_USER
            self.tf_api_key.value = settings.STEAM_API_KEY

            self.page.window.prevent_close = True
            self.page.window.on_event = self.on_window_event
            self._start_ritual()

    async def on_window_event(self, e):
        print(f"on_window_event {e}")
        if e.type == WindowEventType.CLOSE:
            print("OS Window closed! Triggering kill switches...")
            # Fire the Gatekeeper's kill switch
            self.stop_event.set()

            # Now manually destroy the window to actually close the app
            self.page.window.prevent_close = False
            self.page.update()

            # Tell Flet to close naturally (which will now terminate the app)
            await self.page.window.close()


    def _on_initiate_click(self, e):
        user = self.tf_steam_id.value.strip()
        key = self.tf_api_key.value.strip()

        if not user or not key:
            if self.page:
                self.page.show_dialog(ft.SnackBar(ft.Text("The pact requires both a Name and a Key.")))
            return

        # Update Settings in Memory
        settings.STEAM_USER = user
        settings.STEAM_API_KEY = key

        # Persist to Disk
        current_settings = settings.load_settings()
        current_settings["STEAM_USER"] = user
        current_settings["STEAM_API_KEY"] = key
        settings.save_settings(current_settings)

        # Reload globals
        settings.reload()

        self._start_ritual()

    def _start_ritual(self):
        # Transition UI
        self.container_contract.visible = False
        self.container_ritual.visible = True

        stats = vault.get_vault_statistics()
        life_wasted = int(stats.get("total_hours", 0))

        self.txt_total_debt.value = f"Life Wasted: {life_wasted} Hours"
        self.update()

        # Create a thread-safe communication bucket
        self.ritual_queue = queue.Queue()

        # Start the heavy scraper in a totally disconnected background thread
        threading.Thread(target=self._heavy_scraper_thread, daemon=True).start()

        # Start Flet's native async UI updater loop
        self.page.run_task(self._ui_updater_task)

    def _heavy_scraper_thread(self):
        """Runs in the background, totally disconnected from the UI. Just does the math."""
        try:
            generator = vault.update(settings.STEAM_USER, stop_event=self.stop_event)
            for status_update in generator:
                # Throw the update into the bucket
                self.ritual_queue.put(status_update)
                if self.stop_event.is_set():
                    self.ritual_queue.put("ABORTED")
                    return

            self.ritual_queue.put("VIBES")
            vibes = VibeEngine.get_instance()
            vibes.ingest_library()

            # Tell the bucket we are finished
            self.ritual_queue.put("DONE")
        except Exception as e:
            self.ritual_queue.put({"error": str(e)})

    async def _ui_updater_task(self):
        """Runs on Flet's UI thread. Safely checks the bucket and draws the screen."""
        stats = vault.get_vault_statistics()
        life_wasted = float(stats.get("total_hours", 0))

        self._log("Opening the Vault...")
        self.txt_log.update()

        while True:
            try:
                # Try to grab a message from the bucket without stopping the program
                update_data = self.ritual_queue.get_nowait()

                # Check if the ritual is finished
                if update_data == "DONE":
                    self._log("> RITUAL COMPLETE.")
                    self.progress_bar.internal_bar.value = 1.0
                    self.progress_bar.internal_bar.update()
                    self.txt_log.update()

                    # Restore native Flet window behavior
                    self.page.window.prevent_close = False
                    self.page.window.on_event = None  # Detach the Gatekeeper's custom listener
                    self.page.update()

                    await asyncio.sleep(1.0)  # Show 100% for a second
                    if self.on_complete:
                        self.on_complete()
                    break
                elif update_data == "VIBES":
                    self._log(f"> Channeling games into vectors...")
                    self.txt_log.update()
                    continue
                elif update_data == "ABORTED":
                    return

                # Check if the thread threw an error
                if isinstance(update_data, dict) and "error" in update_data:
                    self._log(f"> CRITICAL FAILURE: {update_data['error']}")
                    self.txt_log.color = styles.COLOR_ERROR
                    self.txt_log.update()
                    break

                # --- Normal UI Update ---
                game_name = update_data.get("game_name", "Unknown Entity")
                hours = update_data.get("hours", 0)
                current = update_data.get("current", 0)
                total = update_data.get("total", 1)

                life_wasted += hours

                # Draw the updates
                self.txt_total_debt.value = f"Life Wasted: {int(life_wasted)} Hours"
                self.txt_total_debt.update()

                if total > 0:
                    self.progress_bar.internal_bar.value = current / total
                    self.progress_bar.internal_bar.update()

                if hours >= 1:
                    display_time = f"{int(hours)}h"
                elif hours > 0:
                    display_time = f"{int(hours * 60)}m"
                else:
                    display_time = "0m"

                self._log(f"> Consuming: {game_name} [{display_time}]...")
                self.txt_log.update()

            except queue.Empty:
                # The bucket is empty right now.
                # This is the magic line! Yield exactly 50ms back to Flet so it can DRAW THE FRAME.
                await asyncio.sleep(0.05)


    def _log(self, message):
        """Appends a message to the log, keeping only the last 5 lines."""
        self.log_lines.append(message)
        if len(self.log_lines) > 7:
            self.log_lines.pop(0)
        self.txt_log.value = "\n".join(self.log_lines)
