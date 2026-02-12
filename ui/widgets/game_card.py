import flet as ft
import styles
import vault
from ui.utils import get_roast_asset, launch_game
from ui.widgets.styled_inputs import GrimoireButton


class GameCard(ft.Card):
    def __init__(self, game_data):
        super().__init__()
        self.elevation = 5
        self.bgcolor = styles.COLOR_SURFACE
        self.shape = ft.RoundedRectangleBorder(radius=25.0)

        self.game_data = game_data
        self.content = self._build_content()

    def _build_content(self):
        game_data = self.game_data

        # Extract appid specifically (safely)
        appid = game_data.get("appid")

        is_roast = (appid == "ROAST" or not appid)
        bg_image = None
        bg_opacity = 0.30
        card_width = 240
        card_height = 340 if not is_roast else None
        tint_color = ft.Colors.TRANSPARENT

        # DYNAMIC BACKGROUND LOGIC
        if appid and not is_roast:
            # Standard Game behavior
            bg_image = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg"
        else:
            theme = game_data.get("bg_theme", "DEFAULT")
            bg_image = get_roast_asset(theme)


        controls_list = []

        # Mappings for nicer labels
        labels = {
            "hltb_story": "Story",
            "hours_played": "Playtime"
        }

        # Items to skip in the generic loop
        ignore = ["appid", "name", "bg_theme"]

        # HANDLE NAME FIRST
        name_value = game_data.get("name", "")
        controls_list.append(
            ft.Row(
                controls=[
                    ft.Text(
                        name_value,
                        font_family=styles.FONT_HEADING,
                        weight=ft.FontWeight.BOLD,
                        size=15,
                        no_wrap=True,
                        overflow=ft.TextOverflow.FADE,
                        tooltip=name_value,
                        expand=True  # Allows text to take available space before cutting off
                    ),
                ],
                margin=ft.Margin(5,5,5,0),
                alignment=ft.MainAxisAlignment.START
            )
        )
        # Add the divider as a separate item in the COLUMN, not the Row
        controls_list.append(ft.Divider(height=1, thickness=1, color=styles.COLOR_ACCENT_DIM))

        # LOOP THROUGH THE REST
        for title, content in game_data.items():
            # Check if title is in the ignore list
            if title in ignore:
                continue


            elif title == "comment":
                row = ft.Row(
                    controls=[
                        ft.Text(str(content), italic=True, size=12, font_family=styles.FONT_MONO, color=styles.COLOR_BORDER_BRONZE),
                    ],
                    margin=ft.Margin(5, 0, 5, 0),
                    wrap=True  # Allow comments to wrap to next line if long
                )
                controls_list.append(row)

            else:  # Dynamic fields
                default_title = labels.get(title.lower())
                if default_title:
                    formatted_label = default_title
                else:
                    formatted_label = title.replace("_", " ").title()

                text = ft.Text(
                    spans=[
                        ft.TextSpan(
                            f"{formatted_label}: ", # Note the trailing space
                            style=ft.TextStyle(
                                font_family=styles.FONT_MONO,
                                color=styles.COLOR_TEXT_SECONDARY,
                                weight=ft.FontWeight.BOLD
                            )
                        ),
                        ft.TextSpan(
                            str(content),
                            style=ft.TextStyle(
                                font_family=styles.FONT_MONO,
                                color=styles.COLOR_TEXT_PRIMARY,
                                weight=ft.FontWeight.NORMAL
                            )
                        ),
                    ],
                    size=13,
                    no_wrap=False, # Allows wrapping if the line is too long
                )
                controls_list.append(text)

        controls_list.append(ft.Container(height=10))

        # Save Button
        if appid == "ROAST":
            controls_list.append(
                ft.Row(
                    controls=[
                        GrimoireButton(
                            "Save it",
                            icon=ft.Icons.SAVE,
                            height=30,
                            # Capture appid safely in lambda
                            on_click=lambda e, a=appid: launch_game(a)
                        )
                    ],
                    alignment=ft.MainAxisAlignment.END,
                    vertical_alignment=ft.CrossAxisAlignment.END
                )
            )
        elif not appid is None and vault.is_game_owned(appid): # Launch Button
            controls_list.append(
                ft.Row(
                    controls=[
                        GrimoireButton(
                            "Launch",
                            icon=ft.Icons.PLAY_ARROW,
                            height=30,
                            style=styles.CARD_STYLE,
                            # Capture appid safely in lambda
                            on_click=lambda e, a=appid: launch_game(a)
                        )
                    ],
                    alignment=ft.MainAxisAlignment.END,
                    vertical_alignment=ft.CrossAxisAlignment.END
                )
            )

        # Build the Stack
        stack_controls = []

        # LAYER A: Background Image (Positioned to Fill)
        if bg_image:
            stack_controls.append(
                ft.Container(
                    content=ft.Image(
                        src=bg_image,
                        fit=ft.BoxFit.COVER,
                        repeat=ft.ImageRepeat.NO_REPEAT,
                    ),
                    # Absolute positioning forces this layer to stretch to match the Stack's size
                    left=0, right=0, top=0, bottom=0,
                )
            )

        gradient_layer = None
        if not is_roast:
            gradient_layer = ft.Container(
                gradient=ft.LinearGradient(
                    begin=ft.Alignment.TOP_CENTER,
                    end=ft.Alignment.BOTTOM_CENTER,
                    colors=[ft.Colors.TRANSPARENT, styles.COLOR_SURFACE],
                    stops=[0.2, 0.9]
                ),
            )
        else:
            # Roast Gradient
            gradient_layer = ft.Container(
                gradient=ft.RadialGradient(
                    center=ft.Alignment(0, 0),
                    radius=1.2,  # Slightly larger radius for variable height
                    colors=[styles.COLOR_SURFACE, ft.Colors.with_opacity(0.4, styles.COLOR_ERROR)],
                ),
            )

        if gradient_layer:
            # Add positioning to force stretch
            gradient_layer.left = 0
            gradient_layer.right = 0
            gradient_layer.top = 0
            gradient_layer.bottom = 0
            stack_controls.append(gradient_layer)

        # LAYER C: Content (The Driver)
        # This is the ONLY non-positioned element. The Stack will resize to fit THIS.
        stack_controls.append(
            ft.Container(
                padding=15,
                content=ft.Column(controls_list, spacing=4),
                # If fixed height (Game Card), force it here.
                # If dynamic (Roast), let it be.
                height=card_height if not is_roast else None
            )
        )

        return ft.Container(
            width=card_width,
            height=card_height,  # Enforce outer constraint for Game Cards
            bgcolor=styles.COLOR_SURFACE,
            border_radius=12,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Stack(
                controls=stack_controls,
                # For Roast cards, ensure the stack expands to fill the container width
                width=card_width
            )
        )
