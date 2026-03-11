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
        kwargs.setdefault("label_style", ft.TextStyle(color=styles.COLOR_ACCENT_DIM)) # Floating label
        kwargs.setdefault("hint_style", ft.TextStyle(color=styles.COLOR_TEXT_SECONDARY, italic=True)) # Hint inside field

        super().__init__(**kwargs)

class GlowingChatInput(ft.Container):
    def __init__(self, on_submit=None, **kwargs):
        hint_text = kwargs.pop("hint_text", "Consult the Reaper...")
        multiline = kwargs.pop("multiline", False)
        shift_enter = kwargs.pop("shift_enter", True)

        # Changed to a bone white (WHITE70) for better visibility before typing
        label_style = kwargs.pop("label_style", ft.TextStyle(color=styles.COLOR_TEXT_SECONDARY, italic=True))
        expand_val = kwargs.pop("expand", False)

        self.input_field = ft.TextField(
            border=ft.InputBorder.NONE,
            color=styles.COLOR_INPUT_TEXT,
            cursor_color=styles.COLOR_TEXT_GOLD,
            hint_text=hint_text,
            hint_style=label_style,  # Applied the bone white style here
            on_submit=on_submit,
            on_focus=self._animate_glow_in,
            on_blur=self._animate_glow_out,
            content_padding=ft.padding.all(15),
            multiline=multiline,
            shift_enter=shift_enter,
            min_lines=1,
            max_lines=5,
        )

        self.focus_glow = ft.BoxShadow(
            spread_radius=1,
            blur_radius=15,
            color=ft.Colors.with_opacity(0.4, styles.COLOR_TEXT_GOLD),
            offset=ft.Offset(0, 0)
        )

        self.base_shadow = ft.BoxShadow(
            spread_radius=1,
            blur_radius=0,
            color=ft.Colors.TRANSPARENT,
            offset=ft.Offset(0, 0)
        )

        # Focus state tracker so hover doesn't override the focus glow
        self._is_focused = False

        super().__init__(
            content=self.input_field,
            bgcolor=styles.COLOR_SURFACE,
            border=ft.border.all(1, styles.COLOR_BORDER_BRONZE),
            border_radius=ft.border_radius.all(4),

            # 1px of padding offsets the 1px border difference to prevent jitter on hoover
            padding=ft.padding.all(1),

            animate=ft.Animation(250, ft.AnimationCurve.FAST_OUT_SLOWIN),
            shadow=self.base_shadow,
            expand=expand_val,
            on_hover=self._on_hover,  # Hoover trigger
            **kwargs
        )

    def _on_hover(self, e):
        # State Lock: If actively typing, ignore mouse movements
        if self._is_focused:
            return

        # Toggle between slight white overlay and completely transparent
        if e.data == "true":
            self.input_field.bgcolor = ft.Colors.with_opacity(0.05, ft.Colors.WHITE)
        else:
            self.input_field.bgcolor = ft.Colors.TRANSPARENT
        self.update()

    def _animate_glow_in(self, e):
        self._is_focused = True
        self.shadow = self.focus_glow
        self.border = ft.border.all(2, styles.COLOR_TEXT_GOLD)
        self.padding = ft.padding.all(0)

        self.update()

    def _animate_glow_out(self, e):
        self._is_focused = False
        self.shadow = self.base_shadow
        self.border = ft.border.all(1, styles.COLOR_BORDER_BRONZE)
        self.padding = ft.padding.all(1)

        self.update()

    @property
    def value(self):
        return self.input_field.value

    @value.setter
    def value(self, val):
        self.input_field.value = val

    # Helper method: Flet often needs to refocus the text box after you send a message
    async def focus(self):
        await self.input_field.focus()

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
                shape=ft.BeveledRectangleBorder(radius=3),
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
        # The actual bar must be WHITE and TRANSPARENT so the shader applies correctly
        self.internal_bar = ft.ProgressBar(
            value=None,  # Indeterminate by default
            color=ft.Colors.WHITE,
            bgcolor=ft.Colors.TRANSPARENT,
            border_radius=ft.BorderRadius.all(0),
        )

        # Define the gradient (Deep Blue -> Electric Azure -> Bright Cyan)
        self.mana_gradient = ft.LinearGradient(
            begin=ft.Alignment.CENTER_LEFT,
            end=ft.Alignment.CENTER_RIGHT,
            colors=[
                styles.COLOR_PROGRESS_BASE,  # Deep Magic (Base)
                styles.COLOR_PROGRESS_BAR,  # Electric Azure (Middle)
                styles.COLOR_PROGRESS_TIP  # Arcane Spark (Tip)
            ],
        )

        # Wrap the bar in the ShaderMask
        self.masked_bar = ft.ShaderMask(
            content=self.internal_bar,
            blend_mode=ft.BlendMode.SRC_IN,
            shader=self.mana_gradient,
            border_radius=ft.BorderRadius.all(0),
            expand=True,
        )

        super().__init__(
            width=width,
            height=height,
            border=ft.Border.all(1, styles.COLOR_BORDER_BRONZE),
            border_radius=ft.BorderRadius.all(0),  # edges
            padding=ft.Padding.symmetric(horizontal=3, vertical=3),  # Glass thickness
            bgcolor=styles.COLOR_BACKGROUND,  # Bg behind the glass
            content=self.masked_bar,
            **kwargs
        )