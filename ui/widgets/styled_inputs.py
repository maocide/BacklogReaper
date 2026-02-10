import flet as ft
import styles

class GrimoireTextField(ft.TextField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bgcolor = styles.COLOR_SURFACE
        self.color = styles.COLOR_INPUT_TEXT
        self.cursor_color = styles.COLOR_INPUT_CURSOR
        self.border_color = styles.COLOR_BORDER_BRONZE
        self.focused_border_color = styles.COLOR_TEXT_GOLD
        self.label_style = ft.TextStyle(color=styles.COLOR_ACCENT_DIM)

class GrimoireDropdown(ft.Dropdown):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bgcolor = styles.COLOR_SURFACE
        self.color = styles.COLOR_INPUT_TEXT
        # Dropdown does not have cursor_color
        self.border_color = styles.COLOR_BORDER_BRONZE
        self.focused_border_color = styles.COLOR_TEXT_GOLD
        self.label_style = ft.TextStyle(color=styles.COLOR_ACCENT_DIM)

class GrimoireButton(ft.FilledButton):
    def __init__(self, text=None, icon=None, on_click=None, **kwargs):
        # Apply default style if not provided
        style = kwargs.pop("style", None)
        if style is None:
            style = ft.ButtonStyle(
                color=styles.COLOR_TEXT_GOLD,
                bgcolor=styles.COLOR_SURFACE,
                shape=ft.RoundedRectangleBorder(radius=5),
                side=ft.BorderSide(1, styles.COLOR_BORDER_BRONZE)
            )

        super().__init__(text=text, icon=icon, on_click=on_click, style=style, **kwargs)
