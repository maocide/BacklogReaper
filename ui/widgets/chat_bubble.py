import flet as ft
import styles

class ReaperChatBubble(ft.BaseControl):
    def __init__(self, avatar_name, content_control, is_user, reasoning_control=None, reasoning_title="Reasoning",
                 reasoning_ref=None, reasoning_visible=True, avatar_src=None):
        super().__init__()
        self.avatar_name = avatar_name
        self.content_control = content_control
        self.is_user = is_user
        self.reasoning_control = reasoning_control
        self.reasoning_title = reasoning_title
        self.reasoning_ref = reasoning_ref
        self.reasoning_visible = reasoning_visible
        self.avatar_src = avatar_src

        # Tag for identifying message type in the list
        self.data = "user_message" if is_user else "assistant_message"

    def build(self):
        # THEME CONFIGURATION
        # Reaper Style
        reaper_bg = styles.COLOR_BACKGROUND
        reaper_name_color = styles.COLOR_TEXT_GOLD
        reaper_border_color = styles.COLOR_BORDER_BRONZE
        reaper_border = ft.border.all(width=1, color=reaper_border_color) # Muted Bronze
        reaper_shadow = ft.BoxShadow(
            spread_radius=0,
            blur_radius=10,
            color=ft.Colors.with_opacity(0.1, reaper_name_color),
            offset=ft.Offset(0, 0),
            blur_style=ft.BlurStyle.OUTER,
        )

        # User Style
        user_bg = styles.COLOR_BUBBLE_USER
        user_name_color = styles.COLOR_TEXT_GOLD
        user_border_color = styles.COLOR_BORDER_BRONZE
        user_border = ft.border.all(width=1, color=user_border_color)
        user_shadow = None

        # Select styles based on sender
        bubble_color = user_bg if self.is_user else reaper_bg
        bubble_border = user_border if self.is_user else reaper_border
        bubble_shadow = user_shadow if self.is_user else reaper_shadow

        # AVATAR CONSTRUCTION
        # We use a Container to frame the image nicely
        avatar_content = None
        if not self.is_user:
            if self.avatar_src:
                avatar_content = ft.Container(
                    content=ft.Image(src=self.avatar_src, fit=ft.BoxFit.COVER, border_radius=6),
                    # DOUBLED SIZE:
                    width=120,
                    height=180,
                    #border=ft.border.all(2, reaper_border_color),  # Darker rim
                    border_radius=8,
                    padding=0,
                    shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK),
                    margin=ft.margin.only(right=15),
                )
            else:
                # Fallback placeholder
                # Fallback if image is missing: A simple colored initial or Icon
                avatar_content = ft.Container(
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
            avatar_content = ft.Container(
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
                            bgcolor=ft.Colors.BLACK,  # Darker inner background for thought process
                            border=ft.border.only(left=ft.border.BorderSide(2, reaper_border_color))
                        )
                    ],
                    collapsed_icon_color=reaper_name_color,
                    icon_color=reaper_border_color,
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
            border=bubble_border,
            border_radius=ft.border_radius.only(
                top_left=0 if not self.is_user else 12,
                top_right=12 if not self.is_user else 0,
                bottom_left=12,
                bottom_right=12
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
            row_controls.append(avatar_content)
        else:
            # Reaper Layout: Avatar | Message
            row_controls.append(avatar_content)
            # We let the message expand, but the Column constraints in main chat view
            # usually handle the total width.
            row_controls.append(ft.Container(content=message_container, col={"sm": 12, "md": 11, "lg": 10}, expand=True))

        return ft.Container(
            content=ft.Row(
                controls=row_controls,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            # Increase bottom margin for better separation between turns
            margin=ft.Margin(left=0, top=10, right=0, bottom=30),
            padding=ft.Padding(left=10, right=10)
        )
