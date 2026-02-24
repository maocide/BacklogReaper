import flet as ft
import styles

class ReaperChatBubble(ft.Container):
    def __init__(self, avatar_name, content_control, is_user, reasoning_control=None, reasoning_title="Reasoning",
                 reasoning_ref=None, reasoning_visible=True, avatar_src=None, reasoning_expanded=False):
        super().__init__()
        self.avatar_name = avatar_name
        self.content_control = content_control
        self.is_user = is_user
        self.reasoning_control = reasoning_control
        self.reasoning_title = reasoning_title
        self.reasoning_ref = reasoning_ref
        self.reasoning_visible = reasoning_visible
        self.avatar_src = avatar_src
        self.reasoning_expanded = reasoning_expanded
        self.avatar_content = None

        # Tag for identifying message type in the list
        self.data = "user_message" if is_user else "assistant_message"

        # THEME CONFIGURATION
        # Reaper Style
        reaper_bg = styles.COLOR_BACKGROUND
        # reaper_gradient = ft.LinearGradient(
        #             begin=ft.Alignment.CENTER_LEFT,
        #             end=ft.Alignment.CENTER_RIGHT,
        #             colors=[ft.Colors.with_opacity(0.22, styles.COLOR_SYSTEM_LOG), ft.Colors.with_opacity(0.08, styles.COLOR_SYSTEM_LOG)],
        #             stops=[0.2, 1]
        #         )
        reaper_gradient = ft.RadialGradient(
            center=ft.Alignment(-1.0, -1.0), # Top Left Corner
            radius=2, # Large radius to cover long text
            colors=[
                "#1C2327", # ~25% Spirit Blue on Black
                "#0C0F10", # ~8% Spirit Blue on Black
            ],
            stops=[0.2, 1.0]
        )
        reaper_name_color = styles.COLOR_TEXT_GOLD
        reaper_border_color = styles.COLOR_BORDER_BRONZE
        reaper_border = ft.border.all(width=1, color=reaper_border_color) # Muted Bronze

        # Shared Shadow Logic (Mana Glow)
        common_shadow = ft.BoxShadow(
            spread_radius=1,
            blur_radius=15,
            color=ft.Colors.with_opacity(0.4, styles.COLOR_BUBBLE_SHADOW),
            offset=ft.Offset(0, 0), # Centered glow
            blur_style=ft.BlurStyle.OUTER, # Back to OUTER to prevent internal glow/bleed
        )

        reaper_shadow = common_shadow

        # User Style
        user_bg = styles.COLOR_BUBBLE_USER
        user_name_color = styles.COLOR_TEXT_GOLD
        user_border_color = styles.COLOR_BORDER_BRONZE
        user_border = ft.border.all(width=1, color=user_border_color)
        user_shadow = common_shadow

        # Select styles based on sender
        bubble_color = user_bg if self.is_user else reaper_bg
        bubble_gradient = reaper_gradient if not self.is_user else None
        bubble_border = user_border if self.is_user else reaper_border
        bubble_shadow = user_shadow if self.is_user else reaper_shadow

        # AVATAR CONSTRUCTION
        # We use a Container to frame the image nicely
        self.avatar_content = None
        if not self.is_user:
            if self.avatar_src:
                self.avatar_content = ft.Container(
                    content=ft.Image(src=self.avatar_src, fit=ft.BoxFit.COVER, border_radius=3),
                    width=180,
                    #height=180,
                    #border=ft.border.all(2, reaper_border_color),  # Darker rim
                    border_radius=8,
                    padding=0,
                    shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK),
                    margin=ft.margin.only(right=15),
                )
            else:
                # Fallback placeholder
                # Fallback if image is missing: A simple colored initial or Icon
                self.avatar_content = ft.Container(
                    content=ft.Icon(ft.Icons.ANDROID, color=reaper_name_color),
                    width=60, height=90,
                    bgcolor=ft.Colors.BLACK,
                    border=ft.border.all(1, reaper_border_color),
                    border_radius=5,
                    alignment=ft.Alignment.CENTER
                )

        elif self.is_user:
            src = ft.Icon(ft.Icons.PERSON, color=ft.Colors.WHITE_24)
            if self.avatar_src:
                src = ft.Image(src=self.avatar_src, fit=ft.BoxFit.COVER)

            # Keep user small
            self.avatar_content = ft.Container(
                content=src,
                width=80, height=80,
                bgcolor=ft.Colors.BLACK,
                border_radius=20,
                margin=ft.margin.only(left=10),
                alignment=ft.Alignment.CENTER
            )


        # REASONING BLOCK
        reasoning_section = None
        if self.reasoning_control and not self.is_user:
            reasoning_section = ft.Container(
                ref=self.reasoning_ref,
                content=ft.ExpansionTile(
                    title=ft.Text(self.reasoning_title, size=12, italic=True, color=reaper_name_color),
                    tile_padding=ft.padding.symmetric(horizontal=10),
                    controls=[
                        ft.Container(
                            content=self.reasoning_control,
                            padding=10,
                            # bgcolor=ft.Colors.BLACK,  # REMOVED for transparency as requested
                            border=ft.border.only(left=ft.border.BorderSide(2, reaper_border_color))
                        )
                    ],
                    collapsed_icon_color=reaper_name_color,
                    icon_color=reaper_border_color,
                    expanded=self.reasoning_expanded,
                    on_change=self.on_reasoning_change
                ),
                visible=self.reasoning_visible,
                border=ft.border.all(1, ft.Colors.GREY_900),
                border_radius=5,
                margin=ft.margin.only(bottom=10)
            )

        # BUBBLE ASSEMBLY
        # Combine reasoning (if any) and main content
        bubble_interior = []

        if not self.is_user:
            bubble_interior.append(ft.Text(self.avatar_name, size=12, color=reaper_name_color, weight=ft.FontWeight.BOLD))
        else:
            bubble_interior.append(ft.Text(self.avatar_name, size=12, color=user_name_color, weight=ft.FontWeight.BOLD))

        if reasoning_section:
            bubble_interior.append(reasoning_section)

        bubble_interior.append(ft.SelectionArea(content=self.content_control))

        # The main message bubble
        message_container = ft.Container(
            content=ft.Column(bubble_interior, spacing=5, tight=True),
            bgcolor=bubble_color,
            gradient=bubble_gradient,
            border=bubble_border,
            border_radius=ft.border_radius.only(
                top_left=0 if not self.is_user else 18,
                top_right=18 if not self.is_user else 0,
                bottom_left=18,
                bottom_right=18
            ),
            padding=20,  # More padding for "book page" feel
            shadow=bubble_shadow,
        )

        # ROW COMPOSITION
        row_controls = []

        if self.is_user:
            row_controls.append(
                ft.Container(
                    content=message_container,
                    col={"sm": 12, "md": 11, "lg": 10},
                    expand=True,
                    alignment=ft.Alignment.TOP_RIGHT
                )
            )
            row_controls.append(self.avatar_content)
        else:
            # Reaper Layout: Avatar | Message
            row_controls.append(self.avatar_content)
            # We let the message expand, but the Column constraints in main chat view
            # usually handle the total width.
            row_controls.append(ft.Container(content=message_container, col={"sm": 12, "md": 11, "lg": 10}, expand=True))

        # Assign content to self (Container)
        self.content = ft.Row(
            controls=row_controls,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        # Increase bottom margin for better separation between turns
        self.margin = ft.Margin(left=0, top=10, right=0, bottom=30)
        self.padding = ft.Padding(left=10, right=10)

    def on_reasoning_change(self, e):
        # Update local state so it can be read later
        self.reasoning_expanded = e.control.expanded if e.control else False

    def set_avatar(self, new_url):
        """Updates the avatar image."""
        self.avatar_src = new_url

        if hasattr(self, 'avatar_content') and self.avatar_content:
            src = ft.Image(src=self.avatar_src, fit=ft.BoxFit.COVER)
            self.avatar_content.content = src
            self.avatar_content.update()
