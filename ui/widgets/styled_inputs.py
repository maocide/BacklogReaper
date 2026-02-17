import flet as ft
import styles

class GrimoireTextField(ft.TextField):
    def __init__(self, **kwargs):
        # Override specific styles but allow kwargs to pass through
        kwargs.setdefault("bgcolor", styles.COLOR_SURFACE)
        kwargs.setdefault("color", styles.COLOR_INPUT_TEXT)
        kwargs.setdefault("cursor_color", styles.COLOR_INPUT_CURSOR)
        kwargs.setdefault("border_color", styles.COLOR_BORDER_BRONZE)
        kwargs.setdefault("focused_border_color", styles.COLOR_TEXT_GOLD)
        kwargs.setdefault("focused_border_width", 2)
        kwargs.setdefault("label_style", ft.TextStyle(color=styles.COLOR_ACCENT_DIM))
        super().__init__(**kwargs)

class GrimoireDropdown(ft.Dropdown):
    def __init__(self, **kwargs):
        # Dropdown does not have cursor_color
        kwargs.setdefault("bgcolor", styles.COLOR_SURFACE)
        kwargs.setdefault("color", styles.COLOR_INPUT_TEXT)
        kwargs.setdefault("border_color", styles.COLOR_BORDER_BRONZE)
        kwargs.setdefault("focused_border_color", styles.COLOR_TEXT_GOLD)
        kwargs.setdefault("label_style", ft.TextStyle(color=styles.COLOR_ACCENT_DIM))
        super().__init__(**kwargs)

class GrimoireButton(ft.FilledButton):
    def __init__(self, text=None, icon=None, on_click=None, style=None, **kwargs):
        # Apply default style if not provided
        if style is None:
            style = ft.ButtonStyle(
                color=styles.COLOR_TEXT_GOLD,
                bgcolor=styles.COLOR_SURFACE,
                shape=ft.RoundedRectangleBorder(radius=5),
                side=ft.BorderSide(1, styles.COLOR_BORDER_BRONZE)
            )
        elif style == styles.CARD_STYLE:
            style = ft.ButtonStyle(
                color=styles.COLOR_TEXT_GOLD,
                bgcolor=styles.COLOR_TRANSLUCENT,
                shape=ft.RoundedRectangleBorder(radius=5),
                side=ft.BorderSide(1, styles.COLOR_BORDER_BRONZE))


        # FilledButton in older versions might not support 'text' param directly if using 'content'
        # But 'text' usually maps to setting content=ft.Text(text)
        # Checking introspection, __init__ has 'content' but not 'text'.
        content = None
        if text:
            content = ft.Text(text)
        elif kwargs.get("content"):
            content = kwargs.pop("content")

        super().__init__(content=content, icon=icon, on_click=on_click, style=style, **kwargs)

class GrimoireProgressBar(ft.Container):
    """
    A progress bar styled like a mana bar (bordered container).
    """
    def __init__(self, width=300, height=8, color=styles.COLOR_PROGRESS_BAR, bgcolor=styles.COLOR_SURFACE, **kwargs):
        # The internal ProgressBar needs to fill the container minus padding
        self.internal_bar = ft.ProgressBar(
                value=None, # Indeterminate by default
                color=color,
                bgcolor=bgcolor,
                border_radius=ft.border_radius.all(2),
            )

        super().__init__(
            width=width,
            height=height,
            border=ft.border.all(1, styles.COLOR_BORDER_BRONZE),
            border_radius=ft.border_radius.all(4),
            padding=ft.padding.all(2), # Space between border and bar
            content=self.internal_bar,
            **kwargs
        )
