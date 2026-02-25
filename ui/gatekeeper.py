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
        self.bgcolor = styles.COLOR_BACKGROUND

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

        # The inner content column
        contract_content = ft.Column(
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
        )

        # The "Obsidian Plaque" Wrapper (Glassmorphism effect)
        self.container_contract = ft.Container(
            content=contract_content,
            bgcolor=ft.Colors.with_opacity(0.85, styles.COLOR_SURFACE),
            border=ft.border.all(1, styles.COLOR_TEXT_GOLD),
            border_radius=12,
            padding=ft.padding.all(40),
            blur=ft.Blur(10, 10),  # Frosted glass over the background image
            shadow=ft.BoxShadow(
                blur_radius=50,
                color=ft.Colors.with_opacity(0.5, ft.Colors.BLACK),
                offset=ft.Offset(0, 10)
            ),
            visible=True
        )

        # --- STATE 2: THE RITUAL (Sync) ---
        # Changed to "Life Wasted" and swapped Red for Orange/Gold
        self.txt_total_debt = ft.Text("Life Wasted: 0 Hours", size=30, color=styles.COLOR_TEXT_GOLD, weight=ft.FontWeight.BOLD)
        self.progress_bar = GrimoireProgressBar(width=400)
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
                    width=500,
                    alignment=ft.Alignment.CENTER
                )
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            visible=False
        )

        # --- BACKGROUND ---
        self.background_image = ft.Image(
            src="assets/gatekeeper_bg.jpg",
            fit=ft.BoxFit.COVER, # Fixed the Flet 0.80+ ImageFit hallucination
            opacity=0.3,
            error_content=ft.Container(bgcolor=styles.COLOR_BACKGROUND)
        )

        # --- MAIN LAYOUT ---
        self.content = ft.Stack(
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
            self._start_ritual()

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

        # Replaced threading with Flet's safe background task runner
        self.page.run_task(self._ritual_task)

    async def _ritual_task(self):
        try:
            # Pre-load existing wasted life from the vault stats
            stats = vault.get_vault_statistics()
            life_wasted = float(stats.get("total_hours", 0))

            # Update UI immediately before the loop starts
            self.txt_total_debt.value = f"Life Wasted: {int(life_wasted)} Hours"
            self.update()

            self._log("Opening the Vault...")
            generator = vault.update(settings.STEAM_USER)

            for status_update in generator:
                game_name = status_update.get("game_name", "Unknown Entity")
                hours = status_update.get("hours", 0)
                current = status_update.get("current", 0)
                total = status_update.get("total", 1)

                # Add newly fetched hours to the total
                life_wasted += hours

                # Update UI elements
                self.txt_total_debt.value = f"Life Wasted: {int(life_wasted)} Hours"

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
            self.update()

    def _log(self, message):
        """Appends a message to the log, keeping only the last 5 lines."""
        self.log_lines.append(message)
        if len(self.log_lines) > 5:
            self.log_lines.pop(0)
        self.txt_log.value = "\n".join(self.log_lines)
