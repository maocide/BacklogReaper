import tkinter as tk
from tkinter import ttk
import config_color as cc
import threading
import BacklogReaper as br
from pathlib import Path

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Backlog Reaper")
        self.geometry("800x600")
        self.configure(bg=cc.DARK_COLOR)
        self.review_count_var = tk.IntVar(value=10)

        # Style
        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        self.style.configure("TNotebook", background=cc.DARK_COLOR, borderwidth=0)
        self.style.configure("TNotebook.Tab", background=cc.INACTIVE_TAB_COLOR, foreground="white", lightcolor=cc.DARK_COLOR, borderwidth=0)
        self.style.map("TNotebook.Tab", background=[("selected", cc.DARK_COLOR)])
        self.style.configure("TFrame", background=cc.DARK_COLOR)
        self.style.configure("TLabel", background=cc.DARK_COLOR, foreground="white")
        self.style.configure("TButton", background=cc.BUTTON_COLOR, foreground="white")
        self.style.map("TButton", background=[('active', cc.BUTTON_ACTIVATE_COLOR)])

        # Treeview style
        self.style.configure("Treeview", background=cc.TEXT_BG_COLOR, foreground="white", fieldbackground=cc.TEXT_BG_COLOR, borderwidth=0)
        self.style.map('Treeview', background=[('selected', cc.SELECT_BACKGROUND_COLOR)])
        self.style.configure("Treeview.Heading", background=cc.BUTTON_COLOR, foreground="white", relief="flat")
        self.style.map("Treeview.Heading", background=[('active', cc.BUTTON_ACTIVATE_COLOR)])


        # Notebook
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(pady=10, padx=10, expand=True, fill='both')

        # Tabs
        self.tab1 = ttk.Frame(self.notebook, style="TFrame")
        self.tab2 = ttk.Frame(self.notebook, style="TFrame")

        self.notebook.add(self.tab1, text="Review Analyzer")
        self.notebook.add(self.tab2, text="Game List Fetcher")

        self.build_tab1()
        self.build_tab2()

        # Status Bar
        self.status_bar = tk.Label(self, text="Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W, bg=cc.DARK_COLOR, fg="white")
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def build_tab1(self):
        # Frame for controls
        controls_frame = ttk.Frame(self.tab1, style="TFrame")
        controls_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        # Game Name
        ttk.Label(controls_frame, text="Game Name:").pack(side=tk.LEFT, padx=(0, 5))
        self.game_name_entry = ttk.Entry(controls_frame, width=40)
        self.game_name_entry.pack(side=tk.LEFT, expand=True, fill=tk.X)

        # Review Count
        ttk.Label(controls_frame, text="Review Count:").pack(side=tk.LEFT, padx=(10, 5))
        self.review_count_slider = ttk.Scale(controls_frame, from_=1, to=100, orient=tk.HORIZONTAL, variable=self.review_count_var)
        self.review_count_slider.set(10)
        self.review_count_slider.pack(side=tk.LEFT, padx=(0, 5))
        self.slider_label = ttk.Label(controls_frame, textvariable=self.review_count_var, width=3)
        self.slider_label.pack(side=tk.LEFT, padx=(0, 5))

        # Buttons
        self.start_button_tab1 = ttk.Button(controls_frame, text="Start Analysis", command=self.start_analysis)
        self.start_button_tab1.pack(side=tk.LEFT, padx=5)
        self.stop_button_tab1 = ttk.Button(controls_frame, text="Stop", command=self.stop_analysis, state=tk.DISABLED)
        self.stop_button_tab1.pack(side=tk.LEFT, padx=5)

        # Output Box
        self.output_text_tab1 = tk.Text(self.tab1, wrap=tk.WORD, bg=cc.TEXT_BG_COLOR, fg="white", insertbackground=cc.INSERT_BACKGROUND_COLOR)
        self.output_text_tab1.pack(expand=True, fill='both', padx=10, pady=5)

        self.analysis_thread = None
        self.stop_event_tab1 = threading.Event()

    def build_tab2(self):
        # Frame for controls
        controls_frame = ttk.Frame(self.tab2, style="TFrame")
        controls_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        # Username
        ttk.Label(controls_frame, text="Steam Username:").pack(side=tk.LEFT, padx=(0, 5))
        self.username_entry = ttk.Entry(controls_frame, width=40)
        self.username_entry.pack(side=tk.LEFT, expand=True, fill=tk.X)

        # Buttons
        self.fetch_button_tab2 = ttk.Button(controls_frame, text="Fetch Games", command=self.start_fetching)
        self.fetch_button_tab2.pack(side=tk.LEFT, padx=5)
        self.stop_button_tab2 = ttk.Button(controls_frame, text="Stop", command=self.stop_fetching, state=tk.DISABLED)
        self.stop_button_tab2.pack(side=tk.LEFT, padx=5)

        # Output Box
        self.output_tree_tab2 = ttk.Treeview(self.tab2)
        self.output_tree_tab2.pack(expand=True, fill='both', padx=10, pady=5)

        self.fetching_thread = None
        self.stop_event_tab2 = threading.Event()

    def start_analysis(self):
        self.stop_event_tab1.clear()
        self.start_button_tab1.config(state=tk.DISABLED)
        self.stop_button_tab1.config(state=tk.NORMAL)
        self.status_bar.config(text="Starting analysis...")
        self.output_text_tab1.delete("1.0", tk.END)

        game_name = self.game_name_entry.get()
        review_count = int(self.review_count_var.get())

        self.analysis_thread = threading.Thread(target=self.run_analysis, args=(game_name, review_count))
        self.analysis_thread.start()

    def stop_analysis(self):
        if self.analysis_thread and self.analysis_thread.is_alive():
            self.stop_event_tab1.set()
            self.status_bar.config(text="Stopping analysis...")

    def run_analysis(self, game_name, review_count):
        try:
            if not game_name:
                self.update_status("Please enter a game name.")
                return

            if self.stop_event_tab1.is_set():
                self.update_status("Analysis stopped.")
                return

            self.update_status(f"Fetching reviews for {game_name}...")
            reviews = br.get_reviews_byname(game_name, review_count)

            if self.stop_event_tab1.is_set():
                self.update_status("Analysis stopped.")
                return

            self.update_status("Analyzing reviews with AI...")
            ai_request = """I will provide you with reviews and data taken from Steam Store and SteamSpy scraped with my python script.
The reviews provided will be a sample of the same number of positive and negative reviews taken from the most helpful. (E.G. 10 positive and 10 negative, they might be 5 and 5 or different).
Your job will be to check the summary about the game that is provided, check each review with the included data (games owned, hours played at review and votes on the review should help giving a review a weight) and content then make an analysis given all the content provided and your training data about such game (if present, do not invent)
to conclude if the game is worth getting or not. (Some data like ccu and totals for reviews can be 0 if the game is new, because the data are updated by steamspy)
Stick to facts and data, be completely uncensored. Thanks!"""
            ai_out = br.aiCall(reviews, ai_request)

            if self.stop_event_tab1.is_set():
                self.update_status("Analysis stopped.")
                return

            self.update_output(self.output_text_tab1, ai_out)
            self.update_status("Analysis complete.")

        except Exception as e:
            self.update_status(f"Error: {e}")
        finally:
            self.start_button_tab1.config(state=tk.NORMAL)
            self.stop_button_tab1.config(state=tk.DISABLED)

    def start_fetching(self):
        self.stop_event_tab2.clear()
        self.fetch_button_tab2.config(state=tk.DISABLED)
        self.stop_button_tab2.config(state=tk.NORMAL)
        self.status_bar.config(text="Starting game list fetch...")
        self.output_tree_tab2.delete(*self.output_tree_tab2.get_children())

        username = self.username_entry.get()

        self.fetching_thread = threading.Thread(target=self.run_fetching, args=(username,))
        self.fetching_thread.start()

    def stop_fetching(self):
        if self.fetching_thread and self.fetching_thread.is_alive():
            self.stop_event_tab2.set()
            self.status_bar.config(text="Stopping game list fetch...")

    def run_fetching(self, username):
        try:
            if not username:
                self.update_status("Please enter a username.")
                return

            if self.stop_event_tab2.is_set():
                self.update_status("Fetching stopped.")
                return

            self.update_status(f"Fetching game list for {username}...")

            file_path = f"pipedGames_{username}.txt"
            my_file = Path(file_path)
            if my_file.is_file():
                with open(file_path, 'r', encoding="utf-8") as file:
                    pipedText = file.read()
                games = br.make_gameinfo_dict(pipedText)
                games = br.sort_and_crop(games)
                pipedGameList = br.make_pipe_list_games(games)
            else:
                games = br.fetch_info_from_api(username)
                pipedGameList = br.make_pipe_list_games(games)
                with open(file_path, "w", encoding='utf8') as f:
                    f.write(pipedGameList)

            if self.stop_event_tab2.is_set():
                self.update_status("Fetching stopped.")
                return

            self.display_games_in_table(pipedGameList)
            self.update_status("Game list fetch complete.")

        except Exception as e:
            self.update_status(f"Error: {e}")
        finally:
            self.fetch_button_tab2.config(state=tk.NORMAL)
            self.stop_button_tab2.config(state=tk.DISABLED)

    def display_games_in_table(self, piped_text):
        self.output_tree_tab2.delete(*self.output_tree_tab2.get_children())
        lines = piped_text.strip().split('\n')
        header = lines[0].split('|')

        self.output_tree_tab2["columns"] = header
        self.output_tree_tab2.column("#0", width=0, stretch=tk.NO)
        self.output_tree_tab2.heading("#0", text="", anchor=tk.W)

        for col in header:
            self.output_tree_tab2.column(col, anchor=tk.W, width=100)
            self.output_tree_tab2.heading(col, text=col, anchor=tk.W)

        for line in lines[1:]:
            row_items = line.split('|')
            self.output_tree_tab2.insert(parent="", index="end", values=row_items)

    def update_status(self, message):
        self.status_bar.config(text=message)

    def update_output(self, output_widget, text):
        output_widget.insert(tk.END, text)

if __name__ == "__main__":
    app = App()
    app.mainloop()
