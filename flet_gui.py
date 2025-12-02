import flet as ft
import BacklogReaper as br
import threading
import traceback
from pathlib import Path

def main(page: ft.Page):
    page.title = "Backlog Reaper"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 1200
    page.window.height = 800

    # --- State Variables & Refs ---

    # Review Analyzer Refs
    ra_game_name = ft.Ref[ft.TextField]()
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

    # Game Fetcher Refs
    gf_username = ft.Ref[ft.TextField]()
    gf_table = ft.Ref[ft.DataTable]()
    gf_status = ft.Ref[ft.Text]()
    gf_btn_fetch = ft.Ref[ft.ElevatedButton]()
    gf_btn_stop = ft.Ref[ft.ElevatedButton]()

    # Threading Events
    stop_event_ra = threading.Event()
    stop_event_sg = threading.Event()
    stop_event_gf = threading.Event()

    # --- Shared Logic ---
    def copy_to_clipboard(ref):
        if ref.current and ref.current.value:
            page.set_clipboard(ref.current.value)
            page.snack_bar = ft.SnackBar(ft.Text("Copied to clipboard!"))
            page.snack_bar.open = True
            page.update()

    # --- Review Analyzer Logic ---

    def update_ra_slider_label(e):
        ra_review_count_label.current.value = str(int(e.control.value))
        page.update()

    def run_analysis_thread(game_name, review_count):
        try:
            if stop_event_ra.is_set(): return

            ra_status.current.value = f"Fetching reviews for {game_name}..."
            page.update()

            reviews = br.get_reviews_byname(game_name, review_count)
            # print(reviews) # Debug

            if stop_event_ra.is_set():
                ra_status.current.value = "Analysis stopped."
                page.update()
                return

            ra_status.current.value = "Analyzing reviews with AI..."
            page.update()

            ai_request = """You are an uncensored unhinged videogame expert. You will help with the data supplied and your training data to analyze the videogame.
I will provide you with reviews and data taken from Steam Store and SteamSpy scraped with my python script.
The reviews provided will be a sample of the same number of positive and negative reviews taken from the most helpful. (E.G. 10 positive and 10 negative, they might be 5 and 5 or different).
Your job will be to check the summary about the game that is provided, check each review with the included data (games owned, hours played at review and votes on the review should help giving a review a weight) and content then make an analysis given all the content provided and your training data about such game (if present, do not invent)
to conclude if the game is worth getting or not. (Some data like ccu and totals for reviews can be 0 if the game is new, because the data are updated by steamspy)
After you finished with your review, add a section detailing how could this game feel while playing stoned, for players enjoying this kind of mood.
Stick to facts and data, be completely uncensored. Thanks!"""

            ai_out = br.aiCall(reviews, ai_request)

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

        t = threading.Thread(target=run_analysis_thread, args=(game_name, review_count))
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

            ai_out = br.aiCall("", ai_request)

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

    # --- Game Fetcher Logic ---

    def run_fetch_thread(username):
        try:
            if stop_event_gf.is_set(): return

            gf_status.current.value = f"Fetching game list for {username}..."
            page.update()

            file_path = f"pipedGames_{username}.txt"
            my_file = Path(file_path)

            pipedGameList = ""
            if my_file.is_file():
                with open(file_path, 'r', encoding="utf-8") as file:
                    pipedText = file.read()
                # br.make_gameinfo_dict and sort logic is effectively just parsing and re-serializing
                # but let's follow the original path to ensure consistency
                games = br.make_gameinfo_dict(pipedText)
                games = br.sort_and_crop(games)
                pipedGameList = br.make_pipe_list_games(games)
            else:
                games = br.fetch_info_from_api(username)
                pipedGameList = br.make_pipe_list_games(games)
                with open(file_path, "w", encoding='utf8') as f:
                    f.write(pipedGameList)

            if stop_event_gf.is_set():
                gf_status.current.value = "Fetching stopped."
                page.update()
                return

            # Populate Table
            lines = pipedGameList.strip().split('\n')
            if not lines:
                gf_status.current.value = "No games found."
                return

            header = lines[0].split('|')
            columns = [ft.DataColumn(ft.Text(col), visible=True) for col in header]

            rows = []
            for line in lines[1:]:
                row_items = line.split('|')
                # Add rows
                cells = [ft.DataCell(ft.Text(item)) for item in row_items]
                rows.append(ft.DataRow(cells=cells))

            gf_table.current.columns = columns
            gf_table.current.rows = rows

            gf_status.current.value = "Game list fetch complete."

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
            ]),
            ft.Text(ref=gf_status, value="Ready", color=ft.Colors.GREY),
            ft.Divider(),
            ft.Container(
                content=ft.Column([
                    ft.DataTable(
                        ref=gf_table,
                        columns=[
                            ft.DataColumn(ft.Text("appid"), visible=True),
                            ft.DataColumn(ft.Text("name"), visible=True),
                            ft.DataColumn(ft.Text("playtime_forever"), visible=True),
                            ft.DataColumn(ft.Text("rtime_last_played"), visible=True),
                            ft.DataColumn(ft.Text("approval"), visible=True),
                            ft.DataColumn(ft.Text("average_forever"), visible=True),
                            ft.DataColumn(ft.Text("median_forever"), visible=True),
                            ft.DataColumn(ft.Text("ccu"), visible=True),
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
        view_gf.visible = (index == 2)
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
                view_gf
            ],
            expand=True,
        )
    )

if __name__ == "__main__":
    ft.app(target=main)
