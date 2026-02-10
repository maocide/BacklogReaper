import flet as ft
import styles
import vault
from ui.utils import get_roast_asset, launch_game

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

        # Use 'header.jpg' (460x215) as it fits small cards better than the huge hero image
        bg_image = None
        theme = None
        bg_opacity = 0.30
        card_width = 270
        tint_color = ft.Colors.TRANSPARENT

        # DYNAMIC BACKGROUND LOGIC
        if appid == "ROAST" or not appid:
            # Determine Archetype based on stats
            theme = game_data.get("bg_theme", "default")

            # Map themes to local assets
            bg_image = get_roast_asset(theme)

        elif appid:
            # Standard Game behavior
            bg_image = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg" if appid else ""


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
                        font_family="Cinzel",
                        weight=ft.FontWeight.BOLD,
                        size=15,
                        no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        tooltip=name_value,
                        expand=True  # Allows text to take available space before cutting off
                    ),
                ],
                margin=ft.Margin(5,5,5,0),
                alignment=ft.MainAxisAlignment.START
            )
        )
        # Add the divider as a separate item in the COLUMN, not the Row
        controls_list.append(ft.Divider(height=1, thickness=1))

        # LOOP THROUGH THE REST
        for title, content in game_data.items():
            # Check if title is in the ignore list
            if title in ignore:
                continue


            elif title == "comment":
                row = ft.Row(
                    controls=[
                        ft.Text(str(content), italic=True, size=12, color=ft.Colors.BLUE_GREY),
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

                row = ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Text(f"{formatted_label}:", color=ft.Colors.WHITE38, weight=ft.FontWeight.BOLD),
                            width=100,
                        ),
                        ft.Text(str(content), color=ft.Colors.GREY, expand=True),  # expand prevents overflow push
                    ],
                    alignment=ft.MainAxisAlignment.START,
                    margin=ft.Margin(5, 0, 5, 0),
                    vertical_alignment=ft.CrossAxisAlignment.START  # Aligns text to top if content wraps
                )
                controls_list.append(row)

        controls_list.append(ft.Container(height=10))

        # Save Button
        if appid == "ROAST":
            controls_list.append(
                ft.Row(
                    controls=[
                        ft.FilledButton(
                            "Save it",
                            icon=ft.Icons.SAVE,
                            height=30,
                            style=ft.ButtonStyle(padding=5),
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
                        ft.FilledButton(
                            "Launch",
                            icon=ft.Icons.PLAY_ARROW,
                            height=30,
                            style=ft.ButtonStyle(padding=5),
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

        # LAYER 0: The Background Image (Only if valid)
        if bg_image:
            stack_controls.append(
                ft.Image(
                    src=bg_image,
                    width=card_width,
                    fit=ft.BoxFit.COVER,
                    opacity=bg_opacity,
                    repeat=ft.ImageRepeat.NO_REPEAT,
                    gapless_playback=True,
                )
            )

        # LAYER 1
        stack_controls.append(
            ft.Container(
                padding=10,
                content=ft.Column(
                    controls=controls_list,
                    spacing=5,
                    scroll=ft.ScrollMode.HIDDEN
                )
            )
        )

        card_content = ft.Stack(controls=stack_controls)

        return ft.Container(
            width=card_width,
            bgcolor=styles.COLOR_SURFACE,
            border_radius=25,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,  # Clips the image to the rounded corners
            content=card_content
        )
