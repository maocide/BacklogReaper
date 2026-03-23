import flet as ft
import core.settings as settings
from core.character_manager import CharacterManager
import ui.styles as styles
from ui.widgets.styled_inputs import GrimoireTextField, GrimoireDropdown, GrimoireButton


class SettingsView(ft.Container):
    def __init__(self):
        super().__init__()
        self.expand = True
        self.padding = ft.Padding(0, 5, 5, 10)  # Consistent Padding

        self.set_steam_api = ft.Ref[ft.TextField]()
        self.set_openai_api = ft.Ref[ft.TextField]()
        self.set_openai_base = ft.Ref[ft.TextField]()
        self.set_openai_model = ft.Ref[ft.TextField]()
        self.set_steam_user = ft.Ref[ft.TextField]()
        self.set_character_dd = ft.Ref[ft.Dropdown]()

        # New LLM Settings
        self.set_llm_temp = ft.Ref[ft.Slider]()
        self.set_llm_top_p = ft.Ref[ft.Slider]()
        self.set_llm_presence = ft.Ref[ft.Slider]()

        self.set_status = ft.Ref[ft.Text]()
        self.btn_save = ft.Ref[ft.FilledButton]()

        # Load initial values
        current_settings = settings.load_settings()
        init_steam_key = current_settings.get("STEAM_API_KEY") or settings.STEAM_API_KEY or ""
        init_openai_key = current_settings.get("OPENAI_API_KEY") or settings.OPENAI_API_KEY or ""
        init_openai_base = current_settings.get("OPENAI_BASE_URL") or settings.OPENAI_BASE_URL or ""
        init_openai_model = current_settings.get("OPENAI_MODEL") or settings.OPENAI_MODEL or ""
        init_steam_user = current_settings.get("STEAM_USER") or settings.STEAM_USER or ""
        init_character = current_settings.get("CHARACTER", "Reaper")

        init_llm_temp = float(current_settings.get("LLM_TEMPERATURE", 0.7))
        init_llm_top_p = float(current_settings.get("LLM_TOP_P", 1.0))
        init_llm_presence = float(current_settings.get("LLM_PRESENCE_PENALTY", 0.0))

        # Load Characters
        available_chars = CharacterManager.get_available_characters()
        char_options = [ft.dropdown.Option(c) for c in available_chars]

        def build_card(title, controls):
            return ft.Container(
                content=ft.Column([
                    ft.Text(title, theme_style=ft.TextThemeStyle.TITLE_MEDIUM, color=styles.COLOR_TEXT_GOLD),
                    ft.Divider(color=styles.COLOR_BORDER_BRONZE),
                    *controls
                ], spacing=15),
                bgcolor=styles.COLOR_SURFACE,
                border=ft.border.all(1, styles.COLOR_BORDER_BRONZE),
                border_radius=8,
                padding=20,
                expand=True
            )

        def slider_with_label(ref, label, min_val, max_val, init_val, divisions):
            val_text = ft.Text(str(init_val), width=40, text_align=ft.TextAlign.RIGHT, font_family=styles.FONT_MONO)

            def on_slider_change(e):
                val_text.value = str(round(e.control.value, 2))
                val_text.update()
                self._mark_unsaved(e)

            return ft.Column([
                ft.Row([ft.Text(label, size=13), val_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Slider(
                    ref=ref,
                    min=min_val,
                    max=max_val,
                    value=init_val,
                    divisions=divisions,
                    label="{value}",
                    on_change=on_slider_change,
                    active_color=styles.COLOR_TEXT_GOLD
                )
            ])

        col_left = ft.Column([
            build_card("Steam API", [
                GrimoireTextField(ref=self.set_steam_api, label="Steam API Key", password=True,
                                  can_reveal_password=True, value=init_steam_key, on_change=self._mark_unsaved),
                GrimoireTextField(ref=self.set_steam_user, label="Steam Username", value=init_steam_user,
                                  on_change=self._mark_unsaved)
            ]),
            build_card("Persona", [
                GrimoireDropdown(
                    ref=self.set_character_dd,
                    label="Active Character",
                    options=char_options,
                    value=init_character,
                    on_select=self._mark_unsaved
                )
            ])
        ], expand=True, spacing=20)

        col_right = ft.Column([
            build_card("OpenAI API (or Compatible)", [
                GrimoireTextField(ref=self.set_openai_api, label="OpenAI API Key", password=True,
                                  can_reveal_password=True, value=init_openai_key, on_change=self._mark_unsaved),
                GrimoireTextField(ref=self.set_openai_base, label="Base URL", hint_text="https://api.openai.com/v1",
                                  value=init_openai_base, on_change=self._mark_unsaved),
                GrimoireTextField(ref=self.set_openai_model, label="Model Name", hint_text="gpt-4",
                                  value=init_openai_model, on_change=self._mark_unsaved),
                ft.Divider(color=styles.COLOR_ACCENT_DIM),
                ft.Text("Model Parameters", size=14, weight=ft.FontWeight.BOLD),
                slider_with_label(self.set_llm_temp, "Temperature", 0.0, 2.0, init_llm_temp, 20),
                slider_with_label(self.set_llm_top_p, "Top P", 0.0, 1.0, init_llm_top_p, 20),
                slider_with_label(self.set_llm_presence, "Presence Penalty", -2.0, 2.0, init_llm_presence, 40),
            ])
        ], expand=True, spacing=20)

        header_row = ft.Row([
            ft.Text("Settings", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM, font_family=styles.FONT_HEADING,
                    expand=True),
            GrimoireButton(ref=self.btn_save, text="Save Settings", icon=ft.Icons.SAVE,
                           on_click=self.save_settings_click)
        ])

        self.content = ft.Column([
            header_row,
            ft.Text(ref=self.set_status, value="", color=styles.COLOR_TEXT_SECONDARY, size=12),
            ft.Divider(color=styles.COLOR_ACCENT_DIM),
            ft.Container(
                content=ft.Row([col_left, col_right], alignment=ft.MainAxisAlignment.START,
                               vertical_alignment=ft.CrossAxisAlignment.START, spacing=20),
                expand=True
            )
        ], scroll=ft.ScrollMode.AUTO)

    def refresh_state(self):
        """Called by flet main page/controller when the user navigates back to this tab."""
        current_settings = settings.load_settings()

        if self.set_steam_api.current:
            self.set_steam_api.current.value = current_settings.get("STEAM_API_KEY") or settings.STEAM_API_KEY or ""
            self.set_steam_api.current.update()
        if self.set_steam_user.current:
            self.set_steam_user.current.value = current_settings.get("STEAM_USER") or settings.STEAM_USER or ""
            self.set_steam_user.current.update()
        if self.set_openai_api.current:
            self.set_openai_api.current.value = current_settings.get("OPENAI_API_KEY") or settings.OPENAI_API_KEY or ""
            self.set_openai_api.current.update()
        if self.set_openai_base.current:
            self.set_openai_base.current.value = current_settings.get(
                "OPENAI_BASE_URL") or settings.OPENAI_BASE_URL or ""
            self.set_openai_base.current.update()
        if self.set_openai_model.current:
            self.set_openai_model.current.value = current_settings.get("OPENAI_MODEL") or settings.OPENAI_MODEL or ""
            self.set_openai_model.current.update()
        if self.set_character_dd.current:
            self.set_character_dd.current.value = current_settings.get("CHARACTER", "Reaper")
            self.set_character_dd.current.update()

        if self.set_llm_temp.current:
            self.set_llm_temp.current.value = float(current_settings.get("LLM_TEMPERATURE", 0.7))
            self.set_llm_temp.current.update()
        if self.set_llm_top_p.current:
            self.set_llm_top_p.current.value = float(current_settings.get("LLM_TOP_P", 1.0))
            self.set_llm_top_p.current.update()
        if self.set_llm_presence.current:
            self.set_llm_presence.current.value = float(current_settings.get("LLM_PRESENCE_PENALTY", 0.0))
            self.set_llm_presence.current.update()

        # Reset status and save button
        if self.set_status.current:
            self.set_status.current.value = ""
            self.set_status.current.update()
        if self.btn_save.current:
            self.btn_save.current.style.bgcolor = styles.COLOR_SURFACE
            self.btn_save.current.style.color = styles.COLOR_TEXT_GOLD
            self.btn_save.current.update()

    def _mark_unsaved(self, e):
        if self.set_status.current and self.set_status.current.value != "Unsaved Changes...":
            self.set_status.current.value = "Unsaved Changes..."
            self.set_status.current.color = styles.COLOR_ERROR
            self.set_status.current.update()

            if self.btn_save.current:
                # Add a subtle glow hint to save button
                self.btn_save.current.style.bgcolor = styles.COLOR_TEXT_GOLD
                self.btn_save.current.style.color = ft.Colors.BLACK
                self.btn_save.current.update()

    def save_settings_click(self, e):
        new_settings = {
            "STEAM_API_KEY": self.set_steam_api.current.value.strip() if self.set_steam_api.current.value else "",
            "OPENAI_API_KEY": self.set_openai_api.current.value.strip() if self.set_openai_api.current.value else "",
            "OPENAI_BASE_URL": self.set_openai_base.current.value.strip() if self.set_openai_base.current.value else "",
            "OPENAI_MODEL": self.set_openai_model.current.value.strip() if self.set_openai_model.current.value else "",
            "STEAM_USER": self.set_steam_user.current.value.strip() if self.set_steam_user.current.value else "",
            "CHARACTER": self.set_character_dd.current.value,
            "LLM_TEMPERATURE": round(self.set_llm_temp.current.value, 2),
            "LLM_TOP_P": round(self.set_llm_top_p.current.value, 2),
            "LLM_PRESENCE_PENALTY": round(self.set_llm_presence.current.value, 2)
        }

        if settings.save_settings(new_settings):
            settings.reload()  # Refresh live config
            self.set_status.current.value = "Settings Saved!"
            self.set_status.current.color = ft.Colors.GREEN
            self.set_status.current.update()

            if self.btn_save.current:
                # Revert save button style to default
                self.btn_save.current.style.bgcolor = styles.COLOR_SURFACE
                self.btn_save.current.style.color = styles.COLOR_TEXT_GOLD
                self.btn_save.current.update()
        else:
            self.set_status.current.value = "Error saving settings."
            self.set_status.current.color = ft.Colors.RED
            self.set_status.current.update()
