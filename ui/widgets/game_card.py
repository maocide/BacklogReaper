import flet as ft
import styles
import vault
from ui.utils import get_roast_asset, launch_game, get_status_color
from ui.widgets.styled_inputs import GrimoireButton
from ui.roast_renderer import generate_roast_image

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

        # 1. Get Background Image
        bg_image = self._get_bg_image(appid, is_roast, game_data)

        # 2. Build Content Column (Header, Info Rows, Actions)
        content_column = ft.Column(spacing=4)

        # Header
        content_column.controls.append(self._build_header(game_data.get("name", "")))
        content_column.controls.append(ft.Divider(height=1, thickness=1, color=styles.COLOR_ACCENT_DIM))

        # Info Rows
        info_rows = self._build_info_rows(game_data)
        content_column.controls.extend(info_rows)

        # Spacer
        content_column.controls.append(ft.Container(height=10))

        # Actions (Buttons)
        actions = self._build_actions(appid)
        if actions:
            content_column.controls.append(actions)

        # 3. Build the Visual Stack (Background + Content)
        return self._build_stack(bg_image, content_column)

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
        Generates the roast image and uses FilePicker.save_file directly.
        """
        try:
            # 1. Generate Image
            img = generate_roast_image(self.game_data)

            # 2. Prepare FilePicker
            # Since we're using save_file which returns a path, we don't need on_result
            file_picker = ft.FilePicker()

            page = e.control.page
            if not page:
                print("Error: Page not found for FilePicker attachment.")
                return

            # 3. Add to Overlay and Update Page *BEFORE* calling save_file
            if file_picker not in page.overlay:
                page.overlay.append(file_picker)

            # Use smart_update helper if available or standard update
            if hasattr(page, 'update_async'):
                await page.update_async()
            else:
                page.update()

            # 4. Open Save Dialog and Await Result
            try:
                save_path = await file_picker.save_file(
                    dialog_title="Save Roast Card",
                    file_name=f"roast_{self.game_data.get('name', 'card').replace(' ', '_')}.png",
                    allowed_extensions=["png"]
                )

                if save_path:
                    # Append .png if missing
                    if not save_path.lower().endswith(".png"):
                        save_path += ".png"

                    img.save(save_path)
                    print(f"Roast saved to {save_path}")

                    # Optional: Show feedback (Snackbar)
                    page.snack_bar = ft.SnackBar(ft.Text(f"Roast card saved successfully!"))
                    page.snack_bar.open = True
                    if hasattr(page, 'update_async'):
                        await page.update_async()
                    else:
                        page.update()

            except Exception as pick_ex:
                print(f"Error during file picking: {pick_ex}")

            # Cleanup: Remove picker from overlay
            if file_picker in page.overlay:
                 page.overlay.remove(file_picker)
                 if hasattr(page, 'update_async'):
                    await page.update_async()
                 else:
                    page.update()

        except Exception as ex:
            print(f"Error generating roast image: {ex}")

    def _build_actions(self, appid):
        """Builds the action buttons (Save, Launch) if applicable."""
        if appid == "ROAST":
            return ft.Row(
                controls=[
                    GrimoireButton(
                        "Save it",
                        icon=ft.Icons.SAVE,
                        height=30,
                        style=styles.CARD_STYLE,
                        on_click=self._handle_save_roast
                    )
                ],
                alignment=ft.MainAxisAlignment.END,
                vertical_alignment=ft.CrossAxisAlignment.END
            )
        elif appid and vault.is_game_owned(appid):
            return ft.Row(
                controls=[
                    GrimoireButton(
                        "Launch",
                        icon=ft.Icons.PLAY_ARROW,
                        height=30,
                        style=styles.CARD_STYLE,
                        on_click=lambda e: launch_game(appid)
                    )
                ],
                alignment=ft.MainAxisAlignment.END,
                vertical_alignment=ft.CrossAxisAlignment.END
            )
        return None

    def _build_stack(self, bg_image, content_column):
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
        
        # LAYER D: Content
        stack_controls.append(
            ft.Container(
                padding=15,
                content=content_column,
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
