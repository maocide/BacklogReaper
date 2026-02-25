import threading
import time
import flet as ft
import settings
import styles
import vault
from ui.widgets.styled_inputs import GrimoireButton, GrimoireTextField, GrimoireProgressBar

class GatekeeperView(ft.Container):
    def __init__(self, on_complete=None):
        super().__init__()
        self.expand = True
        self.on_complete = on_complete
        self.alignment = ft.Alignment.CENTER
        self.bgcolor = styles.COLOR_BACKGROUND  # Fallback color

        # --- STATE 1: THE CONTRACT (Inputs) ---
        self.tf_steam_id = GrimoireTextField(
            label="Steam ID / Vanity URL",
            hint_text="e.g. 'GabeNewell' or '76561198072746074'",
            width=400
        )
        self.tf_api_key = GrimoireTextField(
            label="Steam API Key",
            password=True,
            can_reveal_password=True,
            width=400,
            hint_text="Get it from steamcommunity.com/dev/apikey"
        )
        self.btn_initiate = GrimoireButton(
            text="Initiate Ritual",
            width=200,
            height=50,
            on_click=self._on_initiate_click
        )

        self.container_contract = ft.Column(
            controls=[
                ft.Text("Sign the Ledger", size=40, font_family=styles.FONT_HEADING, color=styles.COLOR_TEXT_GOLD),
                ft.Container(height=20),
                self.tf_steam_id,
                self.tf_api_key,
                ft.Container(height=20),
                self.btn_initiate
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            visible=True
        )

        # --- STATE 2: THE RITUAL (Sync) ---
        self.txt_total_debt = ft.Text("Total Debt: 0 Hours", size=30, color=styles.COLOR_ERROR, weight=ft.FontWeight.BOLD)
        self.progress_bar = GrimoireProgressBar(width=400)
        self.log_lines = []
        self.txt_log = ft.Text(
            "> Awaiting invocation...",
            font_family=styles.STYLE_MONOSPACE,
            color=styles.COLOR_SYSTEM_LOG,
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
                    width=500, # Constrain width for log
                    alignment=ft.Alignment.CENTER
                )
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            visible=False
        )

        # --- BACKGROUND ---
        # Placeholder for the user's background image
        self.background_image = ft.Image(
            src="assets/gatekeeper_bg.jpg", # Assuming a file might exist or fail gracefully
            fit=ft.BoxFit.COVER,
            opacity=0.3, # Darken it a bit
            error_content=ft.Container(bgcolor=styles.COLOR_BACKGROUND) # Fallback
        )

        # --- MAIN LAYOUT ---
        # We use a Stack to layer the background behind the content
        self.content = ft.Stack(
            controls=[
                self.background_image,
                # Overlay to ensure text readability if image is bright
                ft.Container(
                    bgcolor=styles.COLOR_TRANSLUCENT,
                    expand=True
                ),
                # The Content Switcher
                ft.Column(
                    controls=[
                        self.container_contract,
                        self.container_ritual
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    expand=True
                )
            ],
            expand=True
        )

    def did_mount(self):
        # Auto-check credentials
        if settings.STEAM_USER and settings.STEAM_API_KEY:
            self.tf_steam_id.value = settings.STEAM_USER
            self.tf_api_key.value = settings.STEAM_API_KEY
            self._start_ritual()
        else:
            # Stay in State 1
            pass

    def _on_initiate_click(self, e):
        user = self.tf_steam_id.value.strip()
        key = self.tf_api_key.value.strip()

        if not user or not key:
            if self.page:
                self.page.show_snack_bar(ft.SnackBar(ft.Text("The pact requires both a Name and a Key.")))
            return

        # Update Settings in Memory
        settings.STEAM_USER = user
        settings.STEAM_API_KEY = key

        # Persist to Disk
        # We need to reload the dict to ensure we have the latest, update it, and save.
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
        self.update()

        # Start Background Task
        # Using a thread to avoid blocking the UI
        self.ritual_thread = threading.Thread(target=self._ritual_task, daemon=True)
        self.ritual_thread.start()

    def _ritual_task(self):
        try:
            total_debt = 0.0

            # Initial Status
            self._log("Opening the Vault...")

            # Consume Generator
            generator = vault.update(settings.STEAM_USER)

            for status_update in generator:
                game_name = status_update.get("game_name", "Unknown Entity")
                hours = status_update.get("hours", 0)
                current = status_update.get("current", 0)
                total = status_update.get("total", 1)

                total_debt += hours

                # Update UI elements
                self.txt_total_debt.value = f"Total Debt: {int(total_debt)} Hours"

                if total > 0:
                    self.progress_bar.internal_bar.value = current / total

                self._log(f"> Reaping soul of: {game_name} ({int(hours)}h)...")

                self.update()

            # Ritual Complete
            self._log("> RITUAL COMPLETE.")
            self.progress_bar.internal_bar.value = 1.0
            self.update()

            time.sleep(1.0) # Brief pause to show completion

            if self.on_complete:
                self.on_complete()

        except Exception as e:
            print(f"Ritual Failed: {e}")
            self._log(f"> CRITICAL FAILURE: {e}")
            self.txt_log.color = styles.COLOR_ERROR

            # In case of error, maybe show the inputs again after a delay?
            # Or just let them sit in shame.
            # For now, let's just show the error.
            self.update()

    def _log(self, message):
        """Appends a message to the log, keeping only the last 5 lines."""
        self.log_lines.append(message)
        if len(self.log_lines) > 5:
            self.log_lines.pop(0)
        self.txt_log.value = "\n".join(self.log_lines)
