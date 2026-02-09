import flet as ft
import webbrowser

import vault
import styles

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

    # Return Card with Stack
    game_card = ft.Card(
        elevation=5,  # Add slight shadow for depth
        bgcolor=styles.COLOR_SURFACE,
        shape=ft.RoundedRectangleBorder(radius=25.0),
        content=ft.Container(
            width=card_width,
            bgcolor=styles.COLOR_SURFACE,
            border_radius=25,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,  # Clips the image to the rounded corners
            content=card_content
        )
    )

    return game_card

def create_metric_card(title, ref_value, icon, color=ft.Colors.WHITE):
     """Creates a standard dashboard metric card."""
     return ft.Card(
        elevation=5,
        bgcolor=styles.COLOR_SURFACE,
        shape=ft.RoundedRectangleBorder(radius=10),
        content=ft.Container(
            content=ft.Column([
                ft.Row([ft.Icon(icon, color=styles.COLOR_TEXT_GOLD), ft.Text(title, weight=ft.FontWeight.BOLD, color=styles.COLOR_TEXT_SECONDARY)], alignment=ft.MainAxisAlignment.CENTER),
                ft.Text("0", ref=ref_value, size=30, weight=ft.FontWeight.BOLD, color=color, text_align=ft.TextAlign.CENTER)
            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=20,
            width=200,
            height=120,
            border=ft.border.all(1, styles.COLOR_BORDER_BRONZE),
            border_radius=10
        )
     )

def create_chat_row(avatar_name, content_control, is_user, reasoning_control=None, reasoning_title="Reasoning",
                    reasoning_ref=None, reasoning_visible=True, avatar_src=None):
    """
    Creates a stylized chat row with RPG-style portraits and themed bubbles.

    Args:
        avatar_name (str): Name to display above the message.
        content_control (ft.Control): The main message content (usually ft.Column or ft.Markdown).
        is_user (bool): True if message is from user (Right aligned), False for Agent (Left aligned).
        reasoning_control (ft.Control, optional): Content for the 'Reasoning' expansion tile.
        reasoning_title (str): Title for the reasoning expansion tile.
        reasoning_ref (ft.Ref, optional): Ref to assign to the reasoning container for dynamic updates.
        reasoning_visible (bool, optional): Initial visibility of the reasoning container.
        avatar_src (ft.Source, optional): Portrait image to use.

    Returns:
        ft.Container: The container wrapping the entire chat row.
    """

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
    bubble_color = user_bg if is_user else reaper_bg
    bubble_border = user_border if is_user else reaper_border
    bubble_shadow = user_shadow if is_user else reaper_shadow

    # AVATAR CONSTRUCTION
    # We use a Container to frame the image nicely
    avatar_content = None
    if not is_user:
        if avatar_src:
            avatar_content = ft.Container(
                content=ft.Image(src=avatar_src, fit=ft.BoxFit.COVER, border_radius=6),
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

    elif is_user:
        # Keep user small
        avatar_content = ft.Container(
            content=ft.Icon(ft.Icons.PERSON, color=ft.Colors.WHITE_24),
            width=40, height=40,
            bgcolor=ft.Colors.BLACK,
            border_radius=20,
            margin=ft.margin.only(left=10),
            alignment=ft.Alignment.CENTER
        )


    # REASONING BLOCK
    reasoning_section = None
    if reasoning_control and not is_user:
        reasoning_section = ft.Container(
            ref=reasoning_ref,
            content=ft.ExpansionTile(
                title=ft.Text(reasoning_title, size=12, italic=True, color=reaper_name_color),
                tile_padding=ft.padding.symmetric(horizontal=10),
                controls=[
                    ft.Container(
                        content=reasoning_control,
                        padding=10,
                        bgcolor=ft.Colors.BLACK,  # Darker inner background for thought process
                        border=ft.border.only(left=ft.border.BorderSide(2, reaper_border_color))
                    )
                ],
                collapsed_icon_color=reaper_name_color,
                icon_color=reaper_border_color,
            ),
            visible=reasoning_visible,
            border=ft.border.all(1, ft.Colors.GREY_900),
            border_radius=5,
            margin=ft.margin.only(bottom=10)
        )

    # BUBBLE ASSEMBLY
    # Combine reasoning (if any) and main content
    bubble_interior = []

    if not is_user:
        bubble_interior.append(ft.Text(avatar_name, size=12, color=reaper_name_color, weight=ft.FontWeight.BOLD))
    else:
        bubble_interior.append(ft.Text(avatar_name, size=12, color=user_name_color, weight=ft.FontWeight.BOLD))

    if reasoning_section:
        bubble_interior.append(reasoning_section)

    bubble_interior.append(ft.SelectionArea(content=content_control))

    # The main message bubble
    message_container = ft.Container(
        content=ft.Column(bubble_interior, spacing=5, tight=True),
        bgcolor=bubble_color,
        border=bubble_border,
        border_radius=ft.border_radius.only(
            top_left=0 if not is_user else 12,
            top_right=12 if not is_user else 0,
            bottom_left=12,
            bottom_right=12
        ),
        padding=20,  # More padding for "book page" feel
        shadow=bubble_shadow,
    )

    # ROW COMPOSITION
    row_controls = []

    if is_user:
        row_controls.append(
            ft.Container(
                content=message_container,
                col={"sm": 12, "md": 11, "lg": 10},
                expand=True,
                alignment=ft.alignment.top_right
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
        padding=ft.Padding(left=10, right=10),
        data="user_message" if is_user else "assistant_message"
    )
