import flet as ft
import webbrowser

def launch_game(appid):
    """Launches the game using the steam protocol."""
    try:
        url = f"steam://run/{appid}"
        print(f"Launching: {url}")
        webbrowser.open(url)
    except Exception as e:
        print(f"Error launching game: {e}")

def get_status_color(status):
    """Returns the color corresponding to a game status."""
    color_map = {
        # Simplified Chart Categories
        "Backlog": ft.Colors.GREY_500,  # Unplayed
        "Trying": ft.Colors.AMBER_400,  # Testing, Bounced
        "Active": ft.Colors.BLUE_400,   # Started, Seasoned, Hooked
        "Finished": ft.Colors.GREEN_400,# Invested, Completionist, Played
        "Shelved": ft.Colors.BROWN_400, # Abandoned, Forgotten, Mastered

        # Detailed Game Card Categories (Fallback to related simplified color)
        "Unplayed": ft.Colors.GREY_500,

        "Testing": ft.Colors.AMBER_400,
        "Bounced": ft.Colors.DEEP_ORANGE_400, # Distinction: Orange for bounced

        "Started": ft.Colors.BLUE_200,
        "Seasoned": ft.Colors.BLUE_600,
        "Hooked": ft.Colors.PURPLE_400, # Distinction: Purple for endless/multi

        "Invested": ft.Colors.GREEN_300,
        "Completionist": ft.Colors.GREEN_500,
        "Played": ft.Colors.TEAL_400, # Distinction: Teal for generic played

        "Abandoned": ft.Colors.BROWN_400,
        "Forgotten": ft.Colors.BROWN_200,
        "Mastered": ft.Colors.DEEP_PURPLE_400 # Distinction: Deep Purple for shelved master
    }
    return color_map.get(status, ft.Colors.WHITE)

def get_roast_asset(status_text):
    """
    Maps the Agent's wild text output to a safe local asset.
    Case-insensitive and fault-tolerant.
    """
    # Normalize the input (Agent might say "Hoarder" or "HOARDER" or "Status: Hoarder")
    key = status_text.upper().strip()

    # Define the strict mapping
    assets = {
        "HOARDER": "assets/cards/hoarder.png",
        "CASUAL": "assets/cards/casual.png",
        "BROKE": "assets/cards/broke.png",
        "HARDCORE": "assets/cards/hardcore.png",
        "ROASTED": "assets/cards/roasted.png",
        "DEFAULT": "assets/cards/default.png"
    }

    # Return the specific asset, or the Clean card if the Agent invents a new status
    return assets.get(key, "assets/cards/default.png")

def create_game_card(game_data):
    """Creates a stylized card for a single game."""

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
    else: # Launch Button
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

    # Return Card with Stack
    game_card = ft.Card(
        elevation=5,  # Add slight shadow for depth
        bgcolor=tint_color,
        shape=ft.RoundedRectangleBorder(radius=25.0),
        content=ft.Container(
            width=card_width,
            bgcolor=tint_color,
            border_radius=25,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,  # Clips the image to the rounded corners
            content=card_content
        )
    )

    return game_card

def create_metric_card(title, ref_value, icon, color=ft.Colors.WHITE):
     """Creates a standard dashboard metric card."""
     return ft.Card(
        content=ft.Container(
            content=ft.Column([
                ft.Row([ft.Icon(icon), ft.Text(title, weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
                ft.Text("0", ref=ref_value, size=30, weight=ft.FontWeight.BOLD, color=color, text_align=ft.TextAlign.CENTER)
            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=20,
            width=200,
            height=120
        )
     )

def create_chat_row(avatar_name, content_control, is_user, reasoning_control=None, reasoning_title="Reasoning", reasoning_ref=None, reasoning_visible=True):
    """
    Creates a standardized chat row with avatar, message bubble, and optional reasoning block.

    Args:
        avatar_name (str): Name to display above the message.
        content_control (ft.Control): The main message content (usually ft.Column or ft.Markdown).
        is_user (bool): True if message is from user (Right aligned), False for Agent (Left aligned).
        reasoning_control (ft.Control, optional): Content for the 'Reasoning' expansion tile.
        reasoning_title (str): Title for the reasoning expansion tile.
        reasoning_ref (ft.Ref, optional): Ref to assign to the reasoning container for dynamic updates.
        reasoning_visible (bool, optional): Initial visibility of the reasoning container.

    Returns:
        ft.Container: The container wrapping the entire chat row.
    """

    # 1. Layout Configuration
    content_col_width = 11
    spacer_col_width = 1

    # Colors and Alignment
    bubble_color = ft.Colors.BLUE_GREY_900 if is_user else ft.Colors.BLACK38
    avatar_alignment = ft.MainAxisAlignment.START if is_user else ft.MainAxisAlignment.END

    # The actual message bubble container
    message_container = ft.Container(
        content=content_control,
        bgcolor=bubble_color,
        col=content_col_width,
        border_radius=10,
        padding=15,
    )

    # Spacer to push bubble to side
    spacer = ft.Container(
        content=None,
        col=spacer_col_width,
        padding=0,
    )

    # Row composition based on sender
    if is_user:
        row_controls = [message_container, spacer]
    else:
        row_controls = [spacer, message_container]

    bubble_row = ft.ResponsiveRow(
        controls=row_controls,
        vertical_alignment=ft.CrossAxisAlignment.START
    )

    # Wrap in SelectionArea for text selection
    bubble_selectable = ft.SelectionArea(content=bubble_row)

    # Main Column Controls
    main_column_controls = [
        ft.Row(
            [ft.Text(avatar_name, size=12, color=ft.Colors.GREY, weight=ft.FontWeight.BOLD)],
            alignment=avatar_alignment
        )
    ]

    # Reasoning Block (Only for Assistant)
    if reasoning_control and not is_user:
        # Create the ExpansionTile structure
        reasoning_row = ft.ResponsiveRow(
            ref=reasoning_ref,
            controls=[
                ft.Container(col=1),
                ft.Container(
                    col=11,
                    content=ft.SelectionArea(
                        content=ft.ExpansionTile(
                            title=ft.Text(reasoning_title),
                            tile_padding=0,
                            controls=[
                                ft.Container(
                                    content=reasoning_control,
                                    padding=ft.Padding.only(left=10, bottom=10)
                                )
                            ],
                            initially_expanded=False
                        )
                    ),
                ),
            ],
            visible=reasoning_visible
        )
        main_column_controls.append(reasoning_row)

    main_column_controls.append(bubble_selectable)

    return ft.Container(
        content=ft.Column(
            controls=main_column_controls,
            spacing=2,
        ),
        margin=ft.Margin(left=0, top=0, right=0, bottom=15),
        padding=ft.Padding(left=10, top=0, right=10, bottom=0),
        data="user_message" if is_user else "assistant_message"
    )
