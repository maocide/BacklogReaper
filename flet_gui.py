import json
import webbrowser
import flet as ft
import BacklogReaper as br
import agent
import threading
import traceback
import vault
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
    status = game_data.get("status", "Unknown")
    status_color = ft.Colors.GREEN if status == "Finished" else ft.Colors.RED if status == "ADDICTED" else ft.Colors.BLUE

    # Try to find an appid if available, though simple search might not return it directly in all cases
    # The agent might need to pass it. For now, let's assume 'appid' is in the data or we can't launch.
    # We'll use a safe get.
    appid = game_data.get("appid") # Ensure agent passes this!

    return ft.Card(
        content=ft.Container(
            width=220,
            padding=10,
            content=ft.Column([
                ft.Text(game_data.get("name", "Unknown"), weight="bold", size=16, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS, tooltip=game_data.get("name", "Unknown")),
                ft.Row([
                    ft.Icon(ft.Icons.CIRCLE, size=10, color=status_color),
                    ft.Text(status, size=12, color=status_color),
                ]),
                ft.Text(f"{game_data.get('hours_played', 0)}h played", size=12),
                ft.Text(f"Story: {game_data.get('hltb_story', 0)}h", size=12, color=ft.Colors.GREY),
                ft.Container(height=5), # Spacer
                ft.ElevatedButton(
                    "Launch",
                    icon=ft.Icons.PLAY_ARROW,
                    height=30,
                    style=ft.ButtonStyle(padding=5),
                    on_click=lambda e: launch_game(appid) if appid else print("No AppID found")
                )
            ])
        )
    )

def parse_and_render_message(text, is_user):
    """
    Analyzes the text. If it finds a JSON block of games, renders Cards.
    Otherwise, renders Markdown.
    """
    controls = []

    # 1. Simple JSON extraction logic (looks for code blocks marked as json)
    if "```json" in text and not is_user:
        # Split text into parts: Pre-JSON, JSON, Post-JSON
        try:
            parts = text.split("```json")
            pre_text = parts[0]

            # Find the end of the json block
            json_and_post = parts[1].split("```")
            json_str = json_and_post[0]
            post_text = json_and_post[1] if len(json_and_post) > 1 else ""

            # Handle multiple JSON blocks? For now, let's assume one main block or handle the first one.
            # Ideally we should iterate, but let's stick to the requirements for now.
            # If there are more parts, append them to post_text?
            if len(json_and_post) > 2:
                 post_text += "```" + "```".join(json_and_post[2:])

            # Render Pre-Text
            if pre_text.strip():
                controls.append(ft.Markdown(pre_text.strip(), extension_set=ft.MarkdownExtensionSet.GITHUB_WEB))

            # Render Cards
            try:
                games_list = json.loads(json_str)
                if isinstance(games_list, list):
                    # Use wrap=True for natural flow instead of horizontal scrolling
                    card_row = ft.Row(wrap=True, spacing=10, run_spacing=10)
                    for game in games_list:
                        card_row.controls.append(create_game_card(game))

                    # Height removal: Let it grow naturally with content
                    controls.append(ft.Container(content=card_row, padding=5))
                else:
                    controls.append(ft.Markdown(f"```json{json_str}```")) # Not a list, render raw
            except json.JSONDecodeError:
                 controls.append(ft.Markdown(f"```json{json_str}```")) # Failed to parse

            # Render Post-Text
            if post_text.strip():
                controls.append(ft.Markdown(post_text.strip(), extension_set=ft.MarkdownExtensionSet.GITHUB_WEB))

        except Exception as e:
            # Fallback if parsing fails: just show original text
            controls.append(ft.Markdown(text, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB))
    else:
        # Standard Text Message
        controls.append(ft.Markdown(text, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB))

    # Message Bubble
    bubble = ft.Container(
        content=ft.Column(controls, tight=True, spacing=5),
        padding=15,
        border_radius=10,
        bgcolor=ft.Colors.BLUE_GREY_900 if is_user else ft.Colors.BLACK38,
    )

    # Avatar Label
    avatar_name = "User" if is_user else "Reaper"
    avatar_alignment = ft.MainAxisAlignment.END if is_user else ft.MainAxisAlignment.START

    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Row(
                    [ft.Text(avatar_name, size=12, color=ft.Colors.GREY, weight="bold")],
                    alignment=avatar_alignment
                ),
                ft.Row(
                    [bubble],
                    alignment=avatar_alignment
                )
            ],
            spacing=2,
        ),
        margin=ft.margin.only(bottom=15)
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
    ra_btn_analyze = ft.Ref[ft.ElevatedButton]()
    ra_btn_stop = ft.Ref[ft.ElevatedButton]()

    # Suggest Games Refs
    sg_game_name = ft.Ref[ft.TextField]()
    sg_output = ft.Ref[ft.Markdown]()
    sg_status = ft.Ref[ft.Text]()
    sg_btn_suggest = ft.Ref[ft.ElevatedButton]()
    sg_btn_stop = ft.Ref[ft.ElevatedButton]()

    # Backlog Reaping Refs
    br_chat_history = [] # OpenAI Message History
    br_chat_list = ft.Ref[ft.ListView]()
    br_input = ft.Ref[ft.TextField]()
    br_status = ft.Ref[ft.Text]()
    br_btn_send = ft.Ref[ft.IconButton]()

    # Game Fetcher Refs
    gf_username = ft.Ref[ft.TextField]()
    gf_table = ft.Ref[ft.DataTable]()
    gf_status = ft.Ref[ft.Text]()
    gf_btn_fetch = ft.Ref[ft.ElevatedButton]()
    gf_btn_stop = ft.Ref[ft.ElevatedButton]()
    gf_chk_force = ft.Ref[ft.Checkbox]()

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

            reviews = br.get_reviews_byname(game_name, review_count)
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

            # Add user message to UI immediately
            if br_chat_list.current:
                br_chat_list.current.controls.append(parse_and_render_message(user_message, is_user=True))
                page.update()

            br_status.current.value = "Reaper is thinking..."
            page.update()

            def on_progress(msg):
                if stop_event_br.is_set(): return
                # Append a small system message for progress
                # Remove generic "thinking" messages if you only want actionable updates
                if br_chat_list.current:
                    br_chat_list.current.controls.append(
                        ft.Text(msg, size=10, italic=True, color=ft.Colors.GREY_500, text_align=ft.TextAlign.CENTER)
                    )
                    page.update()

            # Call Agent
            # Note: We pass the mutable list `br_chat_history`.
            # `agent_chat_loop` appends to it and returns (response, updated_history).
            # Since it modifies the list in-place (if it's the same object), we might not strictly need the return value for history,
            # but let's be safe and assign it back or just rely on the reference.
            # However, `br_chat_history` is a local variable in main, so we need to access it properly.
            # In Python nested functions, we can modify list contents.

            response_text, updated_history = agent.agent_chat_loop(user_message, br_chat_history, on_progress=on_progress)

            # Update the global history reference (though list mutation handles it)
            # br_chat_history[:] = updated_history[:] # Not strictly needed if agent appends, but safe.

            if stop_event_br.is_set():
                br_status.current.value = "Reaping stopped."
                page.update()
                return

            # Add Agent Response to UI
            if br_chat_list.current:
                br_chat_list.current.controls.append(parse_and_render_message(response_text, is_user=False))

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
                 br_input.current.focus()
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

        t = threading.Thread(target=run_backlog_reaping_thread, args=(user_message,))
        t.daemon = True
        t.start()

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
        username = gf_username.current.value
        if not username:
            gf_status.current.value = "Please enter a username."
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
            ft.Text("Review Analyzer", style=ft.TextThemeStyle.HEADLINE_MEDIUM),
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
                ft.ElevatedButton(ref=ra_btn_analyze, text="Start Analysis", icon=ft.Icons.ANALYTICS, on_click=start_analysis),
                ft.ElevatedButton(ref=ra_btn_stop, text="Stop", icon=ft.Icons.STOP, on_click=stop_analysis, disabled=True),
            ]),
            ft.Text(ref=ra_status, value="Ready", color=ft.Colors.GREY),
            ft.Divider(),
            ft.Row([
                ft.Text("Analysis Output", style=ft.TextThemeStyle.TITLE_MEDIUM),
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
            ft.Text("Suggest Similar Games", style=ft.TextThemeStyle.HEADLINE_MEDIUM),
            ft.Row([
                ft.TextField(ref=sg_game_name, label="Game Name", expand=True),
            ]),
            ft.Row([
                ft.ElevatedButton(ref=sg_btn_suggest, text="Suggest", icon=ft.Icons.LIGHTBULB, on_click=start_suggest),
                ft.ElevatedButton(ref=sg_btn_stop, text="Stop", icon=ft.Icons.STOP, on_click=stop_suggest, disabled=True),
            ]),
            ft.Text(ref=sg_status, value="Ready", color=ft.Colors.GREY),
            ft.Divider(),
            ft.Row([
                ft.Text("Suggestion Output", style=ft.TextThemeStyle.TITLE_MEDIUM),
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
                ft.Text("Reaper Chat", style=ft.TextThemeStyle.HEADLINE_MEDIUM, expand=True),
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
            ft.Text("Game List Fetcher", style=ft.TextThemeStyle.HEADLINE_MEDIUM),
            ft.Row([
                ft.TextField(ref=gf_username, label="Steam Username", expand=True),
                ft.ElevatedButton(ref=gf_btn_fetch, text="Fetch Games", icon=ft.Icons.DOWNLOAD, on_click=start_fetch),
                ft.ElevatedButton(ref=gf_btn_stop, text="Stop", icon=ft.Icons.STOP, on_click=stop_fetch, disabled=True),
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
                            ft.DataColumn(ft.Text("Main Story (h)"), visible=True, numeric=True),  # NEW
                            ft.DataColumn(ft.Text("Completionist (h)"), visible=True, numeric=True),  # NEW
                            ft.DataColumn(ft.Text("Status"), visible=True),  # NEW (Derived)
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

    # --- Navigation Logic ---

    def on_nav_change(e):
        index = e.control.selected_index
        view_ra.visible = (index == 0)
        view_sg.visible = (index == 1)
        view_br.visible = (index == 2)
        view_gf.visible = (index == 3)
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
                view_gf
            ],
            expand=True,
        )
    )

if __name__ == "__main__":
    ft.app(target=main)
