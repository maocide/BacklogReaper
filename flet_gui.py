import json
import webbrowser
from flet import FontWeight
import flet as ft

import BacklogReaper as br
import agent
import threading
import traceback
import vault
import config
import settings
from pathlib import Path

def launch_game(appid):
    """Launches the game using the steam protocol."""
    try:
        url = f"steam://run/{appid}"
        print(f"Launching: {url}")
        webbrowser.open(url)
    except Exception as e:
        print(f"Error launching game: {e}")


def create_game_card(game_data):
    """Creates a stylized card for a single game."""

    # Extract appid specifically (safely)
    appid = game_data.get("appid")

    # Use 'header.jpg' (460x215) as it fits small cards better than the huge hero image
    #bg_image = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg" if appid else ""
    bg_image = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg" if appid else ""

    controls_list = []

    # Mappings for nicer labels
    labels = {
        "hltb_story": "Story",
        "hours_played": "Playtime"
    }

    # Items to skip in the generic loop
    ignore = ["appid", "name"]

    # HANDLE NAME FIRST (Ensures it is always at the top)
    name_value = game_data.get("name", "Unknown Game")
    controls_list.append(
        ft.Row(
            controls=[
                ft.Text(
                    name_value,
                    weight=ft.FontWeight.BOLD,
                    size=16,
                    no_wrap=True,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    tooltip=name_value,
                    expand=True  # Allows text to take available space before cutting off
                ),
            ],
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
                    ft.Text(f"{formatted_label}:", color=ft.Colors.WHITE38, weight=ft.FontWeight.BOLD),
                    ft.Text(str(content), color=ft.Colors.GREY, expand=True),  # expand prevents overflow push
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.START  # Aligns text to top if content wraps
            )
            controls_list.append(row)

    # HANDLE BUTTON LAST
    if appid and vault.is_game_owned(appid):
        # Add a vertical spacer (Container) before the button
        controls_list.append(ft.Container(height=10))

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
                alignment=ft.MainAxisAlignment.END  # Aligns button to the right (optional, looks nice)
            )
        )

    # --- CHANGE 2: Build the Stack ---
    # Instead of putting the Column directly in the Container, we put it in a Stack
    card_content = ft.Stack(
        controls=[
            # LAYER 0: The Background Image
            ft.Image(
                src=bg_image,
                width=220,  # Match container width
                #height=400,  # Large enough to cover vertical scrolling area if needed
                fit=ft.BoxFit.COVER,
                opacity=0.15,  # Very dim so text is readable
                repeat=ft.ImageRepeat.NO_REPEAT,
                gapless_playback=True,
            ),

            # LAYER 1: Your Original Content
            ft.Container(
                padding=10,
                content=ft.Column(
                    controls=controls_list,
                    spacing=5,
                    scroll=ft.ScrollMode.HIDDEN
                )
            )
        ]
    )

    # --- CHANGE 3: Return Card with Stack ---
    game_card = ft.Card(
        elevation=5,  # Add slight shadow for depth
        content=ft.Container(
            width=220,
            # Height is optional, but helps uniform look. Remove if you want auto-height.
            # height=300,
            bgcolor="#1a1a1a",  # Fallback background color
            border_radius=10,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,  # Clips the image to the rounded corners
            content=card_content
        )
    )

    return game_card

    # return ft.Card(
    #     content=ft.Container(
    #         width=220,
    #         padding=5,
    #         content=ft.Column([
    #             ft.Text(game_data.get("name", "Unknown"), weight=FontWeight.BOLD, size=16, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS, tooltip=game_data.get("name", "Unknown")),
    #             ft.Row([
    #                 ft.Icon(ft.Icons.CIRCLE, size=10, color=status_color),
    #                 ft.Text(status, size=12, color=status_color),
    #             ]),
    #             ft.Text(f"{game_data.get('hours_played', 0)}h played", size=12),
    #             ft.Text(f"Story: {game_data.get('hltb_story', "?")}h", size=12, color=ft.Colors.GREY),
    #             ft.Text(game_data.get('comment', ""), italic=True, size=12, color=ft.Colors.BLUE_GREY),
    #             ft.Container(height=5), # Spacer
    #             ft.ElevatedButton(
    #                 "Launch",
    #                 icon=ft.Icons.PLAY_ARROW,
    #                 height=30,
    #                 style=ft.ButtonStyle(padding=5),
    #                 on_click=lambda e: launch_game(appid) if appid else print("No AppID found")
    #             )
    #         ])
    #     )
    # )


def parse_and_render_message(text, is_user):
    """
    Analyzes the text. Finds ALL JSON blocks of games and renders them as Cards.
    Handles mixed content: Text -> JSON -> Text -> JSON -> Text.
    """
    controls = []
    is_user_message = False

    # If it's a user message or no JSON, just render markdown
    if "```json" not in text or is_user:
        controls.append(ft.Markdown(text, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB))
        is_user_message = True
    else:
        # Split by the start tag.
        # This gives us a list where:
        # segment[0] is text BEFORE the first json
        # segment[1] starts with the json content, followed by ``` and post-text
        # segment[2] (if any) is the same as [1]...
        segments = text.split("```json")

        # 1. Render the very first text segment (before any JSON)
        if segments[0].strip():
            controls.append(ft.Markdown(segments[0].strip(), extension_set=ft.MarkdownExtensionSet.GITHUB_WEB))

        # 2. Iterate through the remaining segments (each starts with JSON)
        for segment in segments[1:]:
            # Each segment looks like: "JSON_CONTENT```\nPost text..."
            # We split by the closing code block ```
            if "```" in segment:
                json_part, post_text = segment.split("```", 1)

                # --- RENDER CARDS (The JSON part) ---
                try:
                    games_list = json.loads(json_part)
                    if isinstance(games_list, list):
                        card_row = ft.Row(wrap=True, spacing=10, run_spacing=10)
                        for game in games_list:
                            card_row.controls.append(create_game_card(game))
                        controls.append(ft.Container(content=card_row, padding=5))
                    else:
                        # It was JSON, but not a list (maybe a single object or tool log)
                        controls.append(ft.Markdown(f"```json{json_part}```"))
                except json.JSONDecodeError:
                    # Parsing failed, render as raw code block
                    controls.append(ft.Markdown(f"```json{json_part}```"))

                # --- RENDER TEXT (The Post-text part) ---
                if post_text.strip():
                    controls.append(ft.Markdown(post_text.strip(), extension_set=ft.MarkdownExtensionSet.GITHUB_WEB))
            else:
                # Malformed markdown (no closing ```), just treat as raw text
                controls.append(ft.Markdown(f"```json{segment}", extension_set=ft.MarkdownExtensionSet.GITHUB_WEB))


    # Message Bubble Content
    bubble_content = ft.Column(controls, tight=True, spacing=5)

    # --- LAYOUT LOGIC ---

    # Logic:
    # If User:  [Spacer (1)] [Message (11)]
    # If Reaper: [Message (11)] [Spacer (1)]

    # We define the content column width
    content_col_width = 11
    spacer_col_width = 1

    # 1. The Spacer Container (Invisible)
    spacer = ft.Container(
        content=None,
        col=spacer_col_width,
        padding=0,  # Important: No padding on empty space
    )

    # 2. The Message Container (Visible)
    message_container = ft.Container(
        content=bubble_content,
        bgcolor=ft.Colors.BLUE_GREY_900 if is_user else ft.Colors.BLACK38,
        col=content_col_width,
        border_radius=10,
        padding=15,
    )

    # 3. Assemble the Row based on who is speaking
    if is_user:
        row_controls = [message_container, spacer]
    else:
        row_controls = [spacer, message_container]

    bubble_row = ft.ResponsiveRow(
        controls=row_controls,
        vertical_alignment=ft.CrossAxisAlignment.START
    )

    # Wrap in SelectionArea
    bubble_selectable = ft.SelectionArea(content=bubble_row)

    # Avatar Logic
    user_avatar_name = config.STEAM_USER if config.STEAM_USER else "USER"
    avatar_name = user_avatar_name if is_user else "Reaper"
    # Align the text label to match the message bubble's position
    avatar_alignment = ft.MainAxisAlignment.START if is_user else ft.MainAxisAlignment.END

    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Row(
                    [ft.Text(avatar_name, size=12, color=ft.Colors.GREY, weight=FontWeight.BOLD)],
                    alignment=avatar_alignment
                ),
                bubble_selectable,
            ],
            spacing=2,
        ),
        margin=ft.Margin(left=0, top=0, right=0, bottom=15),
        padding=ft.Padding(left=10, top=0, right=10, bottom=0)  # Add slight global padding
    )

def main(page: ft.Page):
    page.title = "Backlog Reaper"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 1200
    page.window.height = 800

    # --- State Variables & Refs ---

    # Review Analyzer Refs
    ra_game_name = ft.Ref[ft.TextField]()
    ra_question = ft.Ref[ft.TextField]()
    ra_review_count = ft.Ref[ft.Slider]()
    ra_review_count_label = ft.Ref[ft.Text]()
    ra_output = ft.Ref[ft.Markdown]()
    ra_status = ft.Ref[ft.Text]()
    ra_btn_analyze = ft.Ref[ft.FilledButton]()
    ra_btn_stop = ft.Ref[ft.FilledButton]()

    # Suggest Games Refs
    sg_game_name = ft.Ref[ft.TextField]()
    sg_output = ft.Ref[ft.Markdown]()
    sg_status = ft.Ref[ft.Text]()
    sg_btn_suggest = ft.Ref[ft.FilledButton]()
    sg_btn_stop = ft.Ref[ft.FilledButton]()

    # Backlog Reaping Refs
    br_chat_history = [] # OpenAI Message History
    br_chat_list = ft.Ref[ft.ListView]()
    br_input = ft.Ref[ft.TextField]()
    br_status = ft.Ref[ft.Text]()
    br_btn_send = ft.Ref[ft.IconButton]()

    # Game Fetcher Refs
    # gf_username = ft.Ref[ft.TextField]() # Removed, now in Settings
    gf_table = ft.Ref[ft.DataTable]()
    gf_status = ft.Ref[ft.Text]()
    gf_btn_fetch = ft.Ref[ft.FilledButton]()
    gf_btn_stop = ft.Ref[ft.FilledButton]()
    gf_chk_force = ft.Ref[ft.Checkbox]()

    # Settings Refs
    set_steam_api = ft.Ref[ft.TextField]()
    set_openai_api = ft.Ref[ft.TextField]()
    set_openai_base = ft.Ref[ft.TextField]()
    set_openai_model = ft.Ref[ft.TextField]()
    set_steam_user = ft.Ref[ft.TextField]()
    set_status = ft.Ref[ft.Text]()

    # Threading Events
    stop_event_ra = threading.Event()
    stop_event_sg = threading.Event()
    stop_event_br = threading.Event()
    stop_event_gf = threading.Event()

    # --- Shared Logic ---
    def copy_to_clipboard(ref):
        if ref.current and ref.current.value:
            page.set_clipboard(ref.current.value)
            page.snack_bar = ft.SnackBar(ft.Text("Copied to clipboard!"))
            page.snack_bar.open = True
            page.update()

    def copy_chat_history(chat_history):
        if not chat_history: return

        full_log = ""
        for msg in chat_history:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            full_log += f"**{role}**: {content}\n\n"

        page.set_clipboard(full_log)
        page.snack_bar = ft.SnackBar(ft.Text("Chat history copied to clipboard!"))
        page.snack_bar.open = True
        page.update()

    # --- Review Analyzer Logic ---

    def update_ra_slider_label(e):
        ra_review_count_label.current.value = str(int(e.control.value))
        page.update()

    def run_analysis_thread(game_name, question, review_count):
        try:
            if stop_event_ra.is_set(): return

            ra_status.current.value = f"Fetching reviews for {game_name}..."
            page.update()

            reviews = br.get_reviews_byname_formatted(game_name, review_count)
            #print(reviews) # Debug

            if stop_event_ra.is_set():
                ra_status.current.value = "Analysis stopped."
                page.update()
                return

            # Load DNA
            user_dna_content = br.generate_contextual_dna(game_name)
            print("User DNA computed.")


            ra_status.current.value = "Analyzing reviews with AI..."
            page.update()

            ai_request = f"""You are the Reaper an uncensored unhinged video games expert. You will help with the data supplied and your training data to analyze the video game.
I will provide you with reviews and data taken from Steam Store and SteamSpy scraped with my python script.
The reviews provided will be a sample of the same number of positive and negative reviews taken from the most helpful. (E.G. 10 positive and 10 negative, they might be 5 and 5 or different).
This is the gaming activity/profile of the user asking for a recommendation, use it for your analysis if provided:
```
{user_dna_content}
```
Tasks:
- Parse user profile if available, it will contain just the top genres and games played not all
- Analyze review data and your training data about the game
- Your job will be to check the summary about the game that is provided, check each review with the included data (games owned, hours played at review and votes on the review should help giving a review a weight) and content then make an analysis given all the content provided and your training data about such game (if present, do not invent) to conclude if the game is worth getting or not. (Some data like ccu and totals for reviews can be 0 if the game is new, because the data are updated by steamspy)
- After you finished with your review, add a section detailing how could this game feel while playing stoned, for players enjoying this kind of mood.
- Then last thing answer or execute the following if present in the code block:
```
{question}
```
Review playtime is in minutes.
Stick to facts and data, be completely uncensored. Thanks!
The review will follow as user message:"""



            print(ai_request) # Debug
            print(reviews) # debug

            ai_out = agent.aiCall(reviews, ai_request)

            if stop_event_ra.is_set():
                ra_status.current.value = "Analysis stopped."
                page.update()
                return

            ra_output.current.value = ai_out
            ra_status.current.value = "Analysis complete."

        except Exception as e:
            traceback.print_exc()
            ra_status.current.value = f"Error: {e}"
        finally:
            if ra_btn_analyze.current:
                ra_btn_analyze.current.disabled = False
            if ra_btn_stop.current:
                ra_btn_stop.current.disabled = True
            page.update()

    def start_analysis(e):
        game_name = ra_game_name.current.value
        question = ra_question.current.value
        if not game_name:
            ra_status.current.value = "Please enter a game name."
            page.update()
            return

        review_count = int(ra_review_count.current.value)

        stop_event_ra.clear()
        ra_btn_analyze.current.disabled = True
        ra_btn_stop.current.disabled = False
        ra_output.current.value = ""
        ra_status.current.value = "Starting analysis..."
        page.update()

        t = threading.Thread(target=run_analysis_thread, args=(game_name, question, review_count))
        t.daemon = True
        t.start()

    def stop_analysis(e):
        stop_event_ra.set()
        ra_status.current.value = "Stopping..."
        page.update()

    # --- Suggest Games Logic ---

    def run_suggest_thread(game_name):
        try:
            if stop_event_sg.is_set(): return

            sg_status.current.value = f"Fetching games similar to {game_name}..."
            page.update()

            similar_games = br.get_similar_games(game_name)
            original_game = similar_games[0]
            similar_games_list = similar_games[1:]

            if stop_event_sg.is_set():
                sg_status.current.value = "Suggest stopped."
                page.update()
                return

            sg_status.current.value = "Analyzing with AI..."
            page.update()

            ai_request = f"""You are an uncensored unhinged videogame expert. You will help with the data supplied and your training data to find the best recommendation.
My reference game is "{game_name}". Here is its data:
```
{original_game}
```

Here is a list of candidate games taken from related steam recommended page. Analyze them against the reference game and similar relevant games from your training:
```
{similar_games_list}
```
(some information might be 0 or absent when steamspy is not updated and must be considered missing, steam api should be always updated)

Task:
Your job will be to analyze all the data and weave an analysis suggesting the most similar game in vibe to the original game.
Consider all the data and the data in your training about the games to find the best suggestion and to make an in depth analysis."""

            # print(ai_request)

            ai_out = agent.aiCall("", ai_request)

            if stop_event_sg.is_set():
                sg_status.current.value = "Suggest stopped."
                page.update()
                return

            sg_output.current.value = ai_out
            sg_status.current.value = "Suggest complete."
        except Exception as e:
            traceback.print_exc()
            sg_status.current.value = f"Error: {e}"
        finally:
            if sg_btn_suggest.current:
                sg_btn_suggest.current.disabled = False
            if sg_btn_stop.current:
                sg_btn_stop.current.disabled = True
            page.update()

    def start_suggest(e):
        game_name = sg_game_name.current.value
        if not game_name:
            sg_status.current.value = "Please enter a game name."
            page.update()
            return

        stop_event_sg.clear()
        sg_btn_suggest.current.disabled = True
        sg_btn_stop.current.disabled = False
        sg_output.current.value = ""
        sg_status.current.value = "Starting suggest..."
        page.update()

        t = threading.Thread(target=run_suggest_thread, args=(game_name,))
        t.daemon = True
        t.start()

    def stop_suggest(e):
        stop_event_sg.set()
        sg_status.current.value = "Stopping..."
        page.update()

    # --- Backlog Reaping Logic ---

    def run_backlog_reaping_thread(user_message):
        try:
            if stop_event_br.is_set(): return

            # Update db if not done for 20 mins
            if vault.get_games_count() and vault.get_elapsed_since_update() > 1200:
                vault.update(config.STEAM_USER)

            # Add User Message to UI
            if br_chat_list.current:
                br_chat_list.current.controls.append(parse_and_render_message(user_message, is_user=True))
                page.update()

            # Prepare Agent UI Elements
            # A status label that changes ("Thinking...", "Searching...")
            status_text = ft.Text("Initializing...", italic=True, size=12, color=ft.Colors.GREY_500)

            # The main message bubble (starts empty)
            # Note: We use Markdown to support bolding/lists in the stream
            agent_markdown = ft.Markdown("", selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)

            # Container for the Agent's response
            agent_container = ft.Container(
                content=ft.Column([
                    status_text,
                    agent_markdown
                ]),
                padding=15,
                border_radius=10,
                bgcolor=ft.Colors.BLACK38,
                margin=ft.Margin(left=60, top=0, right=0, bottom=10)
            )

            if br_chat_list.current:
                br_chat_list.current.controls.append(agent_container)
                page.update()

            # 3. CONSUME THE STREAM
            # We pass the mutable 'br_chat_history' list directly
            stream = agent.agent_chat_loop_stream(user_message, br_chat_history)
            previous_was_tool = False
            first_text = True

            for event_type, content in stream:
                if stop_event_br.is_set(): break

                if event_type == "status":
                    # Update the status label
                    status_text.value = content
                    status_text.update()
                    br_status.current.value = content
                    page.update()

                elif event_type == "action":
                    # Append a small system message for progress
                    if br_chat_list.current:
                        position = len(br_chat_list.current.controls) -1
                        br_chat_list.current.controls.insert(
                            position,
                            ft.Text(content, size=14, italic=True, weight=ft.FontWeight.W_600, color=ft.Colors.GREY_500, text_align=ft.TextAlign.CENTER)
                        )
                        page.update()

                    previous_was_tool = True

                elif event_type == "text":
                    # Hide status once text starts appearing (optional, or keep it)
                    if status_text.visible:
                        status_text.visible = False
                        status_text.update()

                    # Append text chunk and update
                    if previous_was_tool and not first_text:
                        agent_markdown.value += "\n\n"
                    agent_markdown.value += content

                    agent_markdown.update()

                    previous_was_tool = False
                    first_text = False

            # 4. Final Cleanup
            if not stop_event_br.is_set():
                # If the final message contained JSON (Generative UI), we might want to re-render the whole bubble
                # to trigger your 'parse_and_render_message' logic (which creates Cards).
                # The streaming Markdown won't render the Cards automatically during the stream.

                final_text = agent_markdown.value

                # Replace the streaming container with your fancy Card-rendering container
                # Remove the last control (the streaming one)
                br_chat_list.current.controls.pop()

                # Add the fully rendered parsed message
                br_chat_list.current.controls.append(parse_and_render_message(final_text, is_user=False))

                br_status.current.value = "Ready"
                page.update()

        except Exception as e:
            traceback.print_exc()
            br_status.current.value = f"Error: {e}"
            if br_chat_list.current:
                br_chat_list.current.controls.append(ft.Text(f"Error: {e}", color=ft.Colors.RED))
        finally:
            if br_btn_send.current:
                br_btn_send.current.disabled = False
            if br_input.current:
                br_input.current.disabled = False
                # br_input.current.focus() # Removed async call in thread
            page.update()


    def send_message(e):
        user_message = br_input.current.value
        if not user_message:
            return

        br_input.current.value = ""
        br_input.current.disabled = True
        br_btn_send.current.disabled = True
        page.update()

        stop_event_br.clear()

        # Use Flet's run_thread to ensure correct context for updates
        page.run_thread(run_backlog_reaping_thread, user_message)

    # Game Fetcher
    def run_fetch_thread(username):
        try:
            if stop_event_gf.is_set(): return

            gf_status.current.value = f"Opening the Vault for {username}..."
            page.update()

            force_update = gf_chk_force.current.value

            # FETCH FROM DB
            game_count = vault.get_games_count()

            if game_count == 0 or force_update:
                # UPDATE THE DB
                vault.update(username)

            if stop_event_gf.is_set(): return

            gf_status.current.value = "Reading from Vault..."
            page.update()

            # FETCH FROM DB
            games_list = vault.get_all_games()

            if not games_list:
                gf_status.current.value = "Vault is empty. Something went wrong."
                return

            # POPULATE UI TABLE ---
            rows = []
            for game in games_list:
                # Calculate a quick status for the UI
                playtime_min = game.get('playtime_forever', 0)
                playtime_hrs = round(playtime_min / 60.0, 1)

                hltb_main = game.get('hltb_main', 0)
                hltb_comp = game.get('hltb_completionist', 0)

                if playtime_min < 60:
                    status = "Untouched"
                elif hltb_comp > 0 and playtime_hrs > (hltb_comp * 1.5):
                    status = "ADDICTED"  # Multiplayer or heavily replayed
                elif hltb_main > 0 and playtime_hrs >= (hltb_main * 0.9):
                    status = "Finished"
                elif hltb_main > 0 and playtime_hrs < (hltb_main * 0.2):
                    status = "Dropped?"  # Played > 1h but < 20% of game

                # Create cells
                cells = [
                    ft.DataCell(ft.Text(str(game['appid']))),
                    ft.DataCell(ft.Text(game['name'], overflow=ft.TextOverflow.ELLIPSIS)),
                    ft.DataCell(ft.Text(f"{playtime_hrs} h")),  # Show hours, easier to read
                    ft.DataCell(ft.Text(str(game.get('genre', 'Unknown'))[:20])),  # Truncate long genres
                    ft.DataCell(ft.Text(str(hltb_main) if hltb_main > 0 else "-")),
                    ft.DataCell(ft.Text(str(hltb_comp) if hltb_comp > 0 else "-")),
                    ft.DataCell(ft.Text(status,
                                        color=ft.Colors.GREEN if status == "Finished" else ft.Colors.RED if status == "ADDICTED" else ft.Colors.WHITE)),
                ]
                rows.append(ft.DataRow(cells=cells))

            gf_table.current.rows = rows
            gf_status.current.value = f"Vault loaded. {len(games_list)} games found."

        except Exception as e:
            gf_status.current.value = f"Error: {e}"
            traceback.print_exc()
        finally:
            if gf_btn_fetch.current:
                gf_btn_fetch.current.disabled = False
            if gf_btn_stop.current:
                gf_btn_stop.current.disabled = True
            page.update()

    def start_fetch(e):
        # username = gf_username.current.value # Removed
        username = config.STEAM_USER

        if not username:
            gf_status.current.value = "Please configure Steam Username in Settings."
            page.snack_bar = ft.SnackBar(ft.Text("Please configure Steam Username in Settings!"))
            page.snack_bar.open = True
            page.update()
            return

        if not config.STEAM_API_KEY:
             gf_status.current.value = "Please configure Steam API Key in Settings."
             page.snack_bar = ft.SnackBar(ft.Text("Please configure Steam API Key in Settings!"))
             page.snack_bar.open = True
             page.update()
             return

        stop_event_gf.clear()
        gf_btn_fetch.current.disabled = True
        gf_btn_stop.current.disabled = False
        gf_table.current.rows.clear()
        gf_status.current.value = "Starting fetch..."
        page.update()

        t = threading.Thread(target=run_fetch_thread, args=(username,))
        t.daemon = True
        t.start()

    def stop_fetch(e):
        stop_event_gf.set()
        gf_status.current.value = "Stopping..."
        page.update()

    # --- UI Components ---

    # Review Analyzer View
    view_ra = ft.Column(
        visible=True,
        expand=True,
        controls=[
            ft.Text("Review Analyzer", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM),
            ft.Row([
                ft.TextField(ref=ra_game_name, label="Game Name", expand=True),
                ft.Column([
                    ft.Text("Review Count"),
                    ft.Row([
                        ft.Slider(ref=ra_review_count, min=1, max=100, divisions=99, value=10, on_change=update_ra_slider_label),
                        ft.Text(ref=ra_review_count_label, value="10")
                    ])
                ])
            ]),
            ft.Row([ft.TextField(ref=ra_question, label="Question", expand=True)]),
            ft.Row([
                ft.FilledButton(ref=ra_btn_analyze, content=ft.Text("Start Analysis"), icon=ft.Icons.ANALYTICS, on_click=start_analysis),
                ft.FilledButton(ref=ra_btn_stop, content=ft.Text("Stop"), icon=ft.Icons.STOP, on_click=stop_analysis, disabled=True),
            ]),
            ft.Text(ref=ra_status, value="Ready", color=ft.Colors.GREY),
            ft.Divider(),
            ft.Row([
                ft.Text("Analysis Output", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                ft.IconButton(icon=ft.Icons.COPY, tooltip="Copy to Clipboard", on_click=lambda e: copy_to_clipboard(ra_output))
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Container(
                content=ft.Column(
                    controls=[ft.Markdown(ref=ra_output, selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)],
                    scroll=ft.ScrollMode.AUTO,
                ),
                expand=True,
                border=ft.Border(
                    top=ft.BorderSide(1, ft.Colors.OUTLINE),
                    right=ft.BorderSide(1, ft.Colors.OUTLINE),
                    bottom=ft.BorderSide(1, ft.Colors.OUTLINE),
                    left=ft.BorderSide(1, ft.Colors.OUTLINE)
                ),
                border_radius=5,
                padding=10,
                #bg=ft.Colors.BLACK12 # Optional background for the text area
            )
        ]
    )

    # Suggest Games View
    view_sg = ft.Column(
        visible=False,
        expand=True,
        controls=[
            ft.Text("Suggest Similar Games", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM),
            ft.Row([
                ft.TextField(ref=sg_game_name, label="Game Name", expand=True),
            ]),
            ft.Row([
                ft.FilledButton(ref=sg_btn_suggest, content=ft.Text("Suggest"), icon=ft.Icons.LIGHTBULB, on_click=start_suggest),
                ft.FilledButton(ref=sg_btn_stop, content=ft.Text("Stop"), icon=ft.Icons.STOP, on_click=stop_suggest, disabled=True),
            ]),
            ft.Text(ref=sg_status, value="Ready", color=ft.Colors.GREY),
            ft.Divider(),
            ft.Row([
                ft.Text("Suggestion Output", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                ft.IconButton(icon=ft.Icons.COPY, tooltip="Copy to Clipboard", on_click=lambda e: copy_to_clipboard(sg_output))
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Container(
                content=ft.Column(
                    controls=[ft.Markdown(ref=sg_output, selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)],
                    scroll=ft.ScrollMode.AUTO,
                ),
                expand=True,
                border=ft.Border(
                    top=ft.BorderSide(1, ft.Colors.OUTLINE),
                    right=ft.BorderSide(1, ft.Colors.OUTLINE),
                    bottom=ft.BorderSide(1, ft.Colors.OUTLINE),
                    left=ft.BorderSide(1, ft.Colors.OUTLINE)
                ),
                border_radius=5,
                padding=10
            )
        ]
    )

    # Backlog Reaping View
    view_br = ft.Column(
        visible=False,
        expand=True,
        controls=[
            ft.Row([
                ft.Text("Reaper Chat", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM, expand=True),
                ft.IconButton(icon=ft.Icons.COPY, tooltip="Copy Chat History", on_click=lambda e: copy_chat_history(br_chat_history))
            ]),
            ft.Container(
                content=ft.ListView(
                    ref=br_chat_list,
                    expand=True,
                    spacing=10,
                    padding=10,
                    auto_scroll=True,
                ),
                expand=True,
                border=ft.Border(
                    top=ft.BorderSide(1, ft.Colors.OUTLINE),
                    right=ft.BorderSide(1, ft.Colors.OUTLINE),
                    bottom=ft.BorderSide(1, ft.Colors.OUTLINE),
                    left=ft.BorderSide(1, ft.Colors.OUTLINE)
                ),
                border_radius=5,
                bgcolor=ft.Colors.BLACK12
            ),
            ft.Text(ref=br_status, value="Ready", color=ft.Colors.GREY, size=12),
            ft.Row([
                ft.TextField(
                    ref=br_input,
                    hint_text="Ask the Reaper...",
                    expand=True,
                    multiline=True,
                    shift_enter=True,
                    on_submit=send_message
                ),
                ft.IconButton(ref=br_btn_send, icon=ft.Icons.SEND, icon_color=ft.Colors.BLUE_400, on_click=send_message)
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ]
    )

    # Game Fetcher View
    view_gf = ft.Column(
        visible=False,
        expand=True,
        controls=[
            ft.Text("Game List Fetcher", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM),
            ft.Row([
                # ft.TextField(ref=gf_username, label="Steam Username", expand=True), # Removed
                ft.FilledButton(ref=gf_btn_fetch, content=ft.Text("Fetch Games"), icon=ft.Icons.DOWNLOAD, on_click=start_fetch),
                ft.FilledButton(ref=gf_btn_stop, content=ft.Text("Stop"), icon=ft.Icons.STOP, on_click=stop_fetch, disabled=True),
                ft.Checkbox(ref=gf_chk_force, label="Force Update", tooltip="Force Update"),
            ]),
            ft.Text(ref=gf_status, value="Ready", color=ft.Colors.GREY),
            ft.Divider(),
            ft.Container(
                content=ft.Column([
                    ft.DataTable(
                        ref=gf_table,
                        columns=[
                            ft.DataColumn(ft.Text("AppID"), visible=True),
                            ft.DataColumn(ft.Text("Name"), visible=True),
                            ft.DataColumn(ft.Text("Playtime (m)"), visible=True, numeric=True),
                            ft.DataColumn(ft.Text("Genre"), visible=True),
                            ft.DataColumn(ft.Text("Main Story (h)"), visible=True, numeric=True),
                            ft.DataColumn(ft.Text("Completionist (h)"), visible=True, numeric=True),
                            ft.DataColumn(ft.Text("Status"), visible=True),
                        ],
                        rows=[],
                        vertical_lines=ft.BorderSide(1, ft.Colors.GREY_400),
                        horizontal_lines=ft.BorderSide(1, ft.Colors.GREY_400),
                    )
                ], scroll=ft.ScrollMode.AUTO), # Scrollable container for the table
                expand=True,
                border=ft.Border(
                    top=ft.BorderSide(1, ft.Colors.OUTLINE),
                    right=ft.BorderSide(1, ft.Colors.OUTLINE),
                    bottom=ft.BorderSide(1, ft.Colors.OUTLINE),
                    left=ft.BorderSide(1, ft.Colors.OUTLINE)
                ),
                border_radius=5,
                padding=10
            )
        ]
    )

    # --- Settings View ---

    def save_settings_click(e):
        new_settings = {
            "STEAM_API_KEY": set_steam_api.current.value,
            "OPENAI_API_KEY": set_openai_api.current.value,
            "OPENAI_BASE_URL": set_openai_base.current.value,
            "OPENAI_MODEL": set_openai_model.current.value,
            "STEAM_USER": set_steam_user.current.value
        }

        if settings.save_settings(new_settings):
            config.reload() # Refresh live config
            set_status.current.value = "Settings Saved!"
            set_status.current.color = ft.Colors.GREEN
        else:
            set_status.current.value = "Error saving settings."
            set_status.current.color = ft.Colors.RED

        page.update()

    # Load initial values
    current_settings = settings.load_settings()
    # Use config values as default to show env vars if json is empty
    init_steam_key = current_settings.get("STEAM_API_KEY") or config.STEAM_API_KEY or ""
    init_openai_key = current_settings.get("OPENAI_API_KEY") or config.OPENAI_API_KEY or ""
    init_openai_base = current_settings.get("OPENAI_BASE_URL") or config.OPENAI_BASE_URL or ""
    init_openai_model = current_settings.get("OPENAI_MODEL") or config.OPENAI_MODEL or ""
    init_steam_user = current_settings.get("STEAM_USER") or config.STEAM_USER or ""


    view_settings = ft.Column(
        visible=False,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Text("Settings", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM),
            ft.Divider(),
            ft.Text("Steam API", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
            ft.TextField(ref=set_steam_api, label="Steam API Key", password=True, can_reveal_password=True, value=init_steam_key),
            ft.TextField(ref=set_steam_user, label="Steam Username", value=init_steam_user),
            ft.Divider(),
            ft.Text("OpenAI API (or Compatible)", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
            ft.TextField(ref=set_openai_api, label="OpenAI API Key", password=True, can_reveal_password=True, value=init_openai_key),
            ft.TextField(ref=set_openai_base, label="Base URL", hint_text="https://api.openai.com/v1", value=init_openai_base),
            ft.TextField(ref=set_openai_model, label="Model Name", hint_text="gpt-4", value=init_openai_model),
            ft.Divider(),
            ft.FilledButton(content=ft.Text("Save Settings"), icon=ft.Icons.SAVE, on_click=save_settings_click),
            ft.Text(ref=set_status, value="")
        ]
    )

    # --- Navigation Logic ---

    def on_nav_change(e):
        index = e.control.selected_index
        view_ra.visible = (index == 0)
        view_sg.visible = (index == 1)
        view_br.visible = (index == 2)
        view_gf.visible = (index == 3)
        view_settings.visible = (index == 4)
        page.update()

    rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=100,
        min_extended_width=400,
        # leading=ft.FloatingActionButton(icon=ft.Icons.CREATE, text="New"), # Removed as per user request
        group_alignment=-0.9,
        destinations=[
            ft.NavigationRailDestination(
                icon=ft.Icons.ANALYTICS_OUTLINED,
                selected_icon=ft.Icons.ANALYTICS,
                label="Review Analyzer"
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.GAMES_OUTLINED,
                selected_icon=ft.Icons.GAMES,
                label="Suggest Games"
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.CHAT_BUBBLE_OUTLINE,
                selected_icon=ft.Icons.CHAT_BUBBLE,
                label="Reaper Chat"
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.LIST_ALT_OUTLINED,
                selected_icon=ft.Icons.LIST_ALT,
                label="My Backlog"
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.SETTINGS_OUTLINED,
                selected_icon=ft.Icons.SETTINGS,
                label="Settings"
            ),
        ],
        on_change=on_nav_change,
    )

    page.add(
        ft.Row(
            [
                rail,
                ft.VerticalDivider(width=1),
                view_ra,
                view_sg,
                view_br,
                view_gf,
                view_settings
            ],
            expand=True,
        )
    )

if __name__ == "__main__":
    ft.run(main)
