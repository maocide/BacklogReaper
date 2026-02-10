import flet as ft
import settings
import character_manager
import styles
from ui.widgets.styled_inputs import GrimoireTextField, GrimoireDropdown, GrimoireButton

class SettingsView(ft.BaseControl):
    def __init__(self):
        super().__init__()
        self.set_steam_api = ft.Ref[ft.TextField]()
        self.set_openai_api = ft.Ref[ft.TextField]()
        self.set_openai_base = ft.Ref[ft.TextField]()
        self.set_openai_model = ft.Ref[ft.TextField]()
        self.set_steam_user = ft.Ref[ft.TextField]()
        self.set_character_dd = ft.Ref[ft.Dropdown]()
        self.set_status = ft.Ref[ft.Text]()

    def build(self):
        # Load initial values
        current_settings = settings.load_settings()
        init_steam_key = current_settings.get("STEAM_API_KEY") or settings.STEAM_API_KEY or ""
        init_openai_key = current_settings.get("OPENAI_API_KEY") or settings.OPENAI_API_KEY or ""
        init_openai_base = current_settings.get("OPENAI_BASE_URL") or settings.OPENAI_BASE_URL or ""
        init_openai_model = current_settings.get("OPENAI_MODEL") or settings.OPENAI_MODEL or ""
        init_steam_user = current_settings.get("STEAM_USER") or settings.STEAM_USER or ""
        init_character = current_settings.get("CHARACTER", "Reaper")

        # Load Characters
        available_chars = character_manager.get_available_characters()
        char_options = [ft.dropdown.Option(c) for c in available_chars]

        return ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Text("Settings", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM, font_family="Cinzel"),
                ft.Divider(),
                ft.Text("Persona", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                GrimoireDropdown(
                    ref=self.set_character_dd,
                    label="Active Character",
                    options=char_options,
                    value=init_character,
                ),
                ft.Divider(),
                ft.Text("Steam API", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                GrimoireTextField(ref=self.set_steam_api, label="Steam API Key", password=True, can_reveal_password=True, value=init_steam_key),
                GrimoireTextField(ref=self.set_steam_user, label="Steam Username", value=init_steam_user),
                ft.Divider(),
                ft.Text("OpenAI API (or Compatible)", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                GrimoireTextField(ref=self.set_openai_api, label="OpenAI API Key", password=True, can_reveal_password=True, value=init_openai_key),
                GrimoireTextField(ref=self.set_openai_base, label="Base URL", hint_text="https://api.openai.com/v1", value=init_openai_base),
                GrimoireTextField(ref=self.set_openai_model, label="Model Name", hint_text="gpt-4", value=init_openai_model),
                ft.Divider(),
                GrimoireButton(text="Save Settings", icon=ft.Icons.SAVE, on_click=self.save_settings_click),
                ft.Text(ref=self.set_status, value="")
            ]
        )

    def save_settings_click(self, e):
        new_settings = {
            "STEAM_API_KEY": self.set_steam_api.current.value,
            "OPENAI_API_KEY": self.set_openai_api.current.value,
            "OPENAI_BASE_URL": self.set_openai_base.current.value,
            "OPENAI_MODEL": self.set_openai_model.current.value,
            "STEAM_USER": self.set_steam_user.current.value,
            "CHARACTER": self.set_character_dd.current.value
        }

        if settings.save_settings(new_settings):
            settings.reload() # Refresh live config
            self.set_status.current.value = "Settings Saved!"
            self.set_status.current.color = ft.Colors.GREEN
        else:
            self.set_status.current.value = "Error saving settings."
            self.set_status.current.color = ft.Colors.RED

        self.update()
