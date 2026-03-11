import threading
import traceback
import flet as ft
import flet_charts as ftc

import vault
import styles
from ui.utils import get_status_color
from ui.widgets.metric_card import MetricCard

class DashboardView(ft.Container):
    def __init__(self):
        super().__init__()
        self.expand = True
        self.padding = ft.Padding(0, 5, 5, 10) # Consistent Padding

        # Refs
        self.vs_status = ft.Ref[ft.Text]()
        self.vs_metric_games = ft.Ref[ft.Text]()
        self.vs_metric_hours = ft.Ref[ft.Text]()
        self.vs_metric_backlog = ft.Ref[ft.Text]()
        self.vs_pie_chart = ft.Ref[ftc.PieChart]()
        self.vs_bar_chart = ft.Ref[ft.Column]()
        self.vs_hours_chart = ft.Ref[ft.Column]()
        self.vs_dashboard_container = ft.Ref[ft.Column]()

        self.content = ft.Column([
            ft.Row([
                ft.Text("Dashboard", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM, expand=True, font_family=styles.FONT_HEADING),
                ft.IconButton(icon=ft.Icons.REFRESH, on_click=self._refresh_stats_click, tooltip="Refresh Stats")
            ]),
            ft.Text(ref=self.vs_status, value="Ready", color=styles.COLOR_TEXT_SECONDARY),
            ft.Column(
                ref=self.vs_dashboard_container,
                visible=False,
                controls=[
                     # Metrics
                     ft.Row([
                         MetricCard("Total Games", self.vs_metric_games, ft.Icons.GAMES),
                         MetricCard("Lifetime Hours", self.vs_metric_hours, ft.Icons.ACCESS_TIME),
                         MetricCard("Backlog Debt", self.vs_metric_backlog, ft.Icons.MONEY_OFF, ft.Colors.RED)
                     ], alignment=ft.MainAxisAlignment.CENTER, spacing=20),

                     ft.Divider(height=30),

                     # Charts
                     ft.ResponsiveRow([
                         ft.Column([
                             ft.Text("Library Status", size=20, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER, font_family=styles.FONT_HEADING),
                             ftc.PieChart(
                                 ref=self.vs_pie_chart,
                                 sections=[],
                                 sections_space=0,
                                 center_space_radius=40,
                                 expand=True
                             )
                         ], col=4),
                         ft.Column([
                             ft.Text("Top Genres (Hours Played)", size=20, weight=ft.FontWeight.BOLD,
                                     text_align=ft.TextAlign.CENTER, font_family=styles.FONT_HEADING),
                             ft.Column(
                                 ref=self.vs_hours_chart,
                                 expand=True,
                             ),
                             ft.Divider(height=20),
                             ft.Text("Top Genres (Games Owned)", size=20, weight=ft.FontWeight.BOLD,
                                     text_align=ft.TextAlign.CENTER, font_family=styles.FONT_HEADING),
                             ft.Column(
                                 ref=self.vs_bar_chart,
                                 expand=True,
                             )
                         ], col=8)
                     ])
                ],
                scroll=ft.ScrollMode.AUTO,
                expand=True
            )
        ])

    def build_horizontal_stat_bar(self, label_text: str, current_val: float, max_val: float, bar_color: str, unit: str = "", label_width: int = 120, value_width: int = 60):
        """
        Creates a single horizontal bar for the custom chart.
        """
        # Calculate percentage for the progress bar (0.0 to 1.0)
        fraction = current_val / max_val if max_val > 0 else 0

        return ft.Row(
            controls=[
                # The Label
                ft.Text(
                    label_text,
                    width=label_width,  # Adjust based on longest genre name
                    color=styles.COLOR_TEXT_PRIMARY,
                    font_family=styles.FONT_MONO,
                    size=12,
                    text_align=ft.TextAlign.RIGHT,
                    no_wrap=True,
                ),

                # The Bar
                ft.Container(
                    content=ft.ProgressBar(
                        value=fraction,
                        color=bar_color,
                        bgcolor=styles.COLOR_BACKGROUND,
                        border_radius=ft.border_radius.all(2),
                    ),
                    border=ft.border.all(1, styles.COLOR_BORDER_BRONZE),
                    border_radius=ft.border_radius.all(2),
                    padding=ft.padding.all(2),
                    bgcolor=styles.COLOR_SURFACE,
                    expand=True,  # Fills the middle space
                    height=16,  # Slightly thicker than a normal progress bar
                ),

                # The Value
                ft.Text(
                    f"{current_val}{unit}",  # or f"{current_val}h" for hours
                    width=value_width,
                    color=styles.COLOR_TEXT_GOLD,
                    weight=ft.FontWeight.BOLD,
                    font_family=styles.FONT_MONO,
                    size=12,
                    no_wrap=True,
                )
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,

        )

    def did_mount(self):
        # Auto-load on mount
        self.load_stats()

    def _refresh_stats_click(self, e):
        self.load_stats()

    def load_stats(self):
        if hasattr(self.page, 'run_thread'):
             self.page.run_thread(self._load_stats_thread)
        else:
             threading.Thread(target=self._load_stats_thread, daemon=True).start()

    def _load_stats_thread(self):
        try:
            self.vs_bar_chart.current.controls.clear()
            self.vs_hours_chart.current.controls.clear()

            if self.vs_status.current:
                self.vs_status.current.value = "Crunching the numbers..."
                self.vs_status.current.update()

            stats = vault.get_vault_statistics()

            # Handle empty stats
            if not stats or stats.get("total_games", 0) == 0:
                 if self.vs_status.current:
                     self.vs_status.current.value = "No data found in Vault. Please go to 'My Backlog' and Fetch Games first."
                     self.vs_status.current.update()
                 if self.vs_dashboard_container.current:
                     self.vs_dashboard_container.current.visible = False
                     self.vs_dashboard_container.current.update()
                 return

            # Update Metrics
            if self.vs_metric_games.current: self.vs_metric_games.current.value = f"{stats['total_games']:,}"
            if self.vs_metric_hours.current: self.vs_metric_hours.current.value = f"{stats['total_hours']:,}h"
            if self.vs_metric_backlog.current: self.vs_metric_backlog.current.value = f"{stats['backlog_hours']:,}h"

            # Update Pie Chart
            status_counts = stats["status_counts"]
            pie_sections = []

            for status, count in status_counts.items():
                if count > 0:
                    color = get_status_color(status)
                    if status.lower() in ["backlog", "unplayed", "untouched"]:
                        color = styles.COLOR_CHART_VOID

                    pie_sections.append(
                        ftc.PieChartSection(
                            count,
                            title=f"{status}\n{count}",
                            title_style=ft.TextStyle(size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                            color=color,
                            radius=100
                        )
                    )

            if self.vs_pie_chart.current: self.vs_pie_chart.current.sections = pie_sections

            # Update Hours Chart (Hours Played)
            genre_hours = stats.get("genre_hours", [])
            max_hours = max([item["count"] for item in genre_hours]) if genre_hours else 0

            # Find longest string for alignment, multiply by 8px (Monospace size 12 width)
            max_label_len_hrs = max([len(str(item["tag"])) for item in genre_hours]) if genre_hours else 0
            label_width_hrs = max(max_label_len_hrs * 8, 80)

            chart_column_hrs = self.vs_hours_chart.current

            for item in genre_hours:
                row = self.build_horizontal_stat_bar(
                    label_text=item["tag"],
                    current_val=int(item["count"]),  # Cast to int so you don't get 14.500000h
                    max_val=max_hours,
                    bar_color=styles.COLOR_BORDER_BRONZE,  # MANA BLUE for Time
                    unit="h",
                    label_width=label_width_hrs,
                    value_width=50,
                )
                chart_column_hrs.controls.append(row)

            # Update Bar Chart (Games Owned)
            genre_counts = stats["genre_counts"]
            max_count = max([item["count"] for item in genre_counts]) if genre_counts else 0

            # Find longest string for alignment, multiply by 8px (Monospace size 12 width)
            max_label_len = max([len(str(item["tag"])) for item in genre_counts]) if genre_counts else 0
            label_width = max(max_label_len * 8, 80)  # Minimum 80px width

            chart_column = self.vs_bar_chart.current

            for item in genre_counts:
                row = self.build_horizontal_stat_bar(
                    label_text=item["tag"],
                    current_val=item["count"],
                    max_val=max_count,
                    bar_color=styles.COLOR_BORDER_BRONZE,  # GOLD for Owned
                    unit="",
                    label_width=label_width,
                    value_width=40,  # Fixed width for values is usually cleaner
                )
                chart_column.controls.append(row)





            if self.vs_status.current:
                self.vs_status.current.value = "Dashboard updated."
                self.vs_status.current.update()

            if self.vs_dashboard_container.current:
                self.vs_dashboard_container.current.visible = True
                self.vs_dashboard_container.current.update()

            self.update()

        except Exception as e:
            traceback.print_exc()
            if self.vs_status.current:
                self.vs_status.current.value = f"Error loading stats: {e}"
                self.vs_status.current.update()


