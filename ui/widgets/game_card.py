import flet as ft
import ui.styles as styles
import core.vault as vault
from ui.utils import get_roast_asset, launch_game, get_status_color
from ui.widgets.styled_inputs import GrimoireButton
from ui.roast_renderer import generate_roast_image
import core.paths as paths
from datetime import datetime
import os

# TOGGLE: Set to False to disable the rarity-colored borders
SHOW_RARITY_BORDER = False

class GameCard(ft.Card):
    def __init__(self, game_data):
        super().__init__()
        self.elevation = 5
        self.bgcolor = styles.COLOR_SURFACE
        self.shape = ft.RoundedRectangleBorder(radius=25.0)

        self.game_data = game_data

        # Dimensions and style constants
        self.card_width = 240
        self.card_height = 340
        self.tint_color = ft.Colors.TRANSPARENT

        self.content = self._build_content()

    def _build_content(self):
        """
        Orchestrates the construction of the card's content.
        """
        game_data = self.game_data
        appid = game_data.get("appid")
        is_roast = (appid == "ROAST" or not appid)

        # Get Background Image
        bg_image = self._get_bg_image(appid, is_roast, game_data)

        # Build Content Column (Header, Info Rows)
        # Add adaptive scrolling so long text fields don't overflow the card
        content_column = ft.Column(spacing=4, scroll=ft.ScrollMode.ADAPTIVE)

        # Header
        content_column.controls.append(self._build_header(game_data.get("name", "")))
        content_column.controls.append(ft.Divider(height=1, thickness=1, color=styles.COLOR_ACCENT_DIM))

        # Info Rows
        info_rows = self._build_info_rows(game_data)
        content_column.controls.extend(info_rows)

        # Bottom padding to ensure last item is not covered by the fixed button
        content_column.controls.append(ft.Container(height=45))

        # Actions (Buttons) are extracted to be positioned absolutely
        actions = self._build_actions(appid)

        # Build the Visual Stack (Background + Content + Actions)
        return self._build_stack(bg_image, content_column, actions)

    def _get_bg_image(self, appid, is_roast, game_data):
        """Determines the background image URL or asset path."""
        if appid and not is_roast:
            # Standard Game behavior
            return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg"
        else:
            theme = game_data.get("bg_theme", "DEFAULT")
            return get_roast_asset(theme)

    def _build_header(self, name_value):
        """Builds the game title row."""
        return ft.Row(
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
            margin=ft.Margin(5, 5, 5, 0),
            alignment=ft.MainAxisAlignment.START
        )

    def _build_info_rows(self, game_data):
        """Generates the list of information rows based on game data."""
        controls_list = []

        # Mappings for nicer labels
        labels = {
            "hltb_story": "Story",
            "hours_played": "Playtime"
        }

        # Items to skip in the generic loop
        ignore = ["appid", "name", "bg_theme"]

        for title, content in game_data.items():
            if title in ignore:
                continue

            elif title == "comment":
                row = ft.Row(
                    controls=[
                        ft.Text(
                            str(content),
                            italic=True,
                            size=12,
                            text_align=ft.TextAlign.LEFT,
                            font_family=styles.FONT_MONO,
                            weight=ft.FontWeight.BOLD,
                            color=styles.COLOR_BORDER_BRONZE
                        ),
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

                # Determine Value Color
                val_color = styles.COLOR_TEXT_PRIMARY  # Default

                # Apply special color for "Status" field
                if title.lower() == "status":
                    val_color = get_status_color(str(content))

                # Handle possible lists
                final_content = ""
                if isinstance(content, list):
                    for item in content:
                        if not final_content:
                            final_content = item
                        else:
                            final_content = f"{final_content}, {item}"
                    content = final_content

                new_line = ft.Text(
                    spans=[
                        ft.TextSpan(
                            f"{formatted_label}: ",
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
                                color=val_color, # Use the calculated color
                                weight=ft.FontWeight.NORMAL
                            )
                        ),
                    ],
                    size=13,
                    no_wrap=False, # Allows wrapping if the line is too long
                )
                controls_list.append(new_line)

        return controls_list

    async def _handle_save_roast(self, e):
        """
        Generates the roast image and saves it to an 'exports' folder with a timestamp.
        """
        import os
        from datetime import datetime

        try:
            # Generate Image
            img = generate_roast_image(self.game_data)

            # Determine Save Path
            paths.ensure_dirs()
            export_dir = paths.get_base_dir() / "exports"

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"roast_{timestamp}.png"
            save_path = export_dir / filename

            # Save Image
            img.save(save_path)
            print(f"Roast saved to {save_path}")

            # Show Feedback (Snackbar via show_dialog workaround)
            page = e.control.page
            if page:
                # Use show_dialog as per user request for SnackBar functionality in this env
                snack = ft.SnackBar(
                    content=ft.Text(f"Roast saved to {save_path}"),
                    action="OK"
                )
                if hasattr(page, 'show_dialog'):
                     page.show_dialog(snack)
                else:
                     # Fallback if method missing (though expected to be there)
                     print("Warning: show_dialog not found, trying page.open")
                     page.open(snack)

                # Use smart_update logic
                if hasattr(page, 'update_async'):
                    await page.update_async()
                else:
                    page.update()
            else:
                print("Warning: Page object not found, skipping SnackBar.")

        except Exception as ex:
            print(f"Error saving roast image: {ex}")
            # Try to show error snackbar if possible
            if e.control.page:
                 err_snack = ft.SnackBar(ft.Text(f"Error saving roast: {ex}"), bgcolor=styles.COLOR_ERROR)
                 if hasattr(e.control.page, 'show_dialog'):
                     e.control.page.show_dialog(err_snack)
                 else:
                     e.control.page.open(err_snack)

                 if hasattr(e.control.page, 'update_async'):
                    await e.control.page.update_async()
                 else:
                    e.control.page.update()

    def _build_actions(self, appid):
        """Builds the action buttons (Save, Launch) if applicable."""
        # Note: We return just the button (not a Row) to prevent the Row's
        # transparent hitbox from consuming clicks meant for the list underneath.
        if appid == "ROAST":
            return GrimoireButton(
                "Save it",
                icon=ft.Icons.SAVE,
                height=30,
                style=styles.CARD_STYLE,
                on_click=self._handle_save_roast
            )
        elif appid and vault.is_game_owned(appid):
            return GrimoireButton(
                "Launch",
                icon=ft.Icons.PLAY_ARROW,
                height=30,
                style=styles.CARD_STYLE,
                on_click=lambda e: launch_game(appid)
            )
        return None

    def _build_stack(self, bg_image, content_column, actions=None):
        """Combines background, gradient, and content into the final stack."""

        stack_controls = []

        # LAYER A: Background Image (Positioned to Fill)
        stack_controls.append(
            ft.Container(
                content=ft.Image(
                    src=bg_image,
                    error_content=ft.Image(
                        src=get_roast_asset("DEFAULT"),
                        fit=ft.BoxFit.COVER,
                        repeat=ft.ImageRepeat.NO_REPEAT
                    ), # FALLBACK
                    fit=ft.BoxFit.COVER,
                    repeat=ft.ImageRepeat.NO_REPEAT,
                ),
                # Absolute positioning forces this layer to stretch to match the Stack's size
                left=0, right=0, top=0, bottom=0,
            )
        )

        # LAYER B: Gradient Overlay
        gradient_layer = ft.Container(
            gradient=ft.LinearGradient(
                begin=ft.Alignment.TOP_CENTER,
                end=ft.Alignment.BOTTOM_CENTER,
                colors=[
                    ft.Colors.with_opacity(0.65, styles.COLOR_SURFACE),
                    ft.Colors.with_opacity(0.65, styles.COLOR_SURFACE),
                    ft.Colors.with_opacity(0.65, styles.COLOR_SURFACE),
                    ft.Colors.with_opacity(0.9, styles.COLOR_SURFACE),
                ],
                stops=[0, 0.3, 0.7, 1.0]
            ),
            # Add positioning to force stretch
            left=0, right=0, top=0, bottom=0,
        )
        stack_controls.append(gradient_layer)

        # LAYER C: Sizing Container (Invisible, enforces min size)
        stack_controls.append(
            ft.Container(
                width=self.card_width,
                height=self.card_height,
            )
        )
        
        # LAYER D: Content (Scrollable)
        stack_controls.append(
            ft.Container(
                padding=15,
                content=content_column,
                # Absolute positioning constraints are needed for scrollable columns inside Stacks
                left=0, right=0, top=0, bottom=0,
            )
        )

        # LAYER E: Action Button (Hovering at bottom right)
        if actions:
            stack_controls.append(
                ft.Container(
                    content=actions,
                    bottom=15,
                    right=15,
                )
            )

        # Shadow Style
        shadow = ft.BoxShadow(
            blur_radius=10,
            spread_radius=1,
            color=ft.Colors.with_opacity(0.80, styles.COLOR_SURFACE),
            offset=ft.Offset(0, 0)
        )

        # --- THEMATIC BORDER LOGIC ---
        border_side = None
        if SHOW_RARITY_BORDER:
            # Check if this card has a specific status
            status = self.game_data.get("status")
            if status:
                color = get_status_color(status)
                border_side = ft.border.all(2, color)
            # If no status (e.g. Roast card), maybe default border?
            elif self.game_data.get("appid") == "ROAST":
                 # Roast cards get red border? or just none?
                 # Let's leave them none for now or maybe Bronze.
                 pass

        # Final Container Wrapper
        return ft.Container(
            width=self.card_width,
            height=self.card_height,  # Enforce outer constraint for Game Cards
            bgcolor=self.tint_color,
            border_radius=12,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Stack(
                controls=stack_controls,
                # For Roast cards, ensure the stack expands to fill the container width
                width=self.card_width
            ),
            shadow=shadow,
            border=border_side
        )
