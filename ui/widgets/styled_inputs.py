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
    A progress bar styled like a mana bar (bordered container with a gradient).
    """

    def __init__(self, width=300, height=12, **kwargs):
        # 1. The actual bar must be WHITE and TRANSPARENT so the shader applies correctly
        self.internal_bar = ft.ProgressBar(
            value=None,  # Indeterminate by default
            color=ft.Colors.WHITE,
            bgcolor=ft.Colors.TRANSPARENT,
            border_radius=ft.BorderRadius.all(4),
        )

        # 2. Define the magical gradient (Deep Blue -> Electric Azure -> Bright Cyan)
        self.mana_gradient = ft.LinearGradient(
            begin=ft.Alignment.CENTER_LEFT,
            end=ft.Alignment.CENTER_RIGHT,
            colors=[
                styles.COLOR_PROGRESS_BASE,  # Deep Magic (Base)
                styles.COLOR_PROGRESS_BAR,  # Electric Azure (Middle)
                styles.COLOR_PROGRESS_TIP  # Arcane Spark (Tip)
            ],
        )

        # 3. Wrap the bar in the ShaderMask
        self.masked_bar = ft.ShaderMask(
            content=self.internal_bar,
            blend_mode=ft.BlendMode.SRC_IN,
            shader=self.mana_gradient,
            border_radius=ft.BorderRadius.all(4),
            expand=True,  # Ensure the mask stretches correctly
        )

        super().__init__(
            width=width,
            height=height,
            border=ft.Border.all(1, styles.COLOR_BORDER_BRONZE),
            border_radius=ft.BorderRadius.all(6),  # Smooth glass tube edges
            padding=ft.Padding.symmetric(horizontal=3, vertical=3),  # "Glass thickness"
            bgcolor=styles.COLOR_BACKGROUND,  # The void behind the glass
            content=self.masked_bar,  # Use the masked version here!
            **kwargs
        )