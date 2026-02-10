import threading
import traceback
import flet as ft
import flet_charts as ftc
import vault
import styles
from ui.utils import get_status_color
from ui.widgets.metric_card import MetricCard

class DashboardView(ft.UserControl):
    def __init__(self):
        super().__init__()
        # Refs
        self.vs_status = ft.Ref[ft.Text]()
        self.vs_metric_games = ft.Ref[ft.Text]()
        self.vs_metric_hours = ft.Ref[ft.Text]()
        self.vs_metric_backlog = ft.Ref[ft.Text]()
        self.vs_pie_chart = ft.Ref[ftc.PieChart]()
        self.vs_bar_chart = ft.Ref[ftc.BarChart]()
        self.vs_hours_chart = ft.Ref[ftc.BarChart]()
        self.vs_dashboard_container = ft.Ref[ft.Column]()

    def build(self):
        return ft.Column(
            expand=True,
            controls=[
                ft.Row([
                    ft.Text("Dashboard", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM, expand=True, font_family="Cinzel"),
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
                                 ft.Text("Library Status", size=20, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                                 ftc.PieChart(
                                     ref=self.vs_pie_chart,
                                     sections=[],
                                     sections_space=0,
                                     center_space_radius=40,
                                     expand=True
                                 )
                             ], col=4),
                             ft.Column([
                                 ft.Text("Top Genres (Games Owned)", size=20, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                                 ftc.BarChart(
                                     ref=self.vs_bar_chart,
                                     groups=[],
                                     border=ft.Border.all(1, ft.Colors.GREY_800),
                                     left_axis=ftc.ChartAxis(label_size=40, title=ft.Text("Games"), title_size=40),
                                     bottom_axis=ftc.ChartAxis(label_size=40),
                                     horizontal_grid_lines=ftc.ChartGridLines(color=ft.Colors.GREY_800, width=1, dash_pattern=[3, 3]),
                                     tooltip=ftc.BarChartTooltip(bgcolor=ft.Colors.with_opacity(0.8, ft.Colors.GREY_900)),
                                     interactive=True,
                                     expand=True,
                                 ),
                                 ft.Divider(height=20),
                                 ft.Text("Top Genres (Hours Played)", size=20, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                                 ftc.BarChart(
                                     ref=self.vs_hours_chart,
                                     groups=[],
                                     border=ft.Border.all(1, ft.Colors.GREY_800),
                                     left_axis=ftc.ChartAxis(label_size=40, title=ft.Text("Hours"), title_size=40),
                                     bottom_axis=ftc.ChartAxis(label_size=40),
                                     horizontal_grid_lines=ftc.ChartGridLines(color=ft.Colors.GREY_800, width=1, dash_pattern=[3, 3]),
                                     tooltip=ftc.BarChartTooltip(bgcolor=ft.Colors.with_opacity(0.8, ft.Colors.GREY_900)),
                                     interactive=True,
                                     expand=True,
                                 )
                             ], col=8)
                         ])
                    ],
                    scroll=ft.ScrollMode.AUTO,
                    expand=True
                )
            ]
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
            if self.vs_metric_backlog.current: self.vs_metric_backlog.current.value = f"{stats['backlog_hours']:,.2f}h"

            # Update Pie Chart
            status_counts = stats["status_counts"]
            pie_sections = []

            for status, count in status_counts.items():
                if count > 0:
                    color = get_status_color(status)
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

            # Update Bar Chart
            genre_counts = stats["genre_counts"]
            bar_groups = []

            max_count = 0
            for i, item in enumerate(genre_counts):
                count = item["count"]
                if count > max_count: max_count = count
                bar_groups.append(
                    ftc.BarChartGroup(
                        x=i,
                        rods=[
                            ftc.BarChartRod(
                                from_y=0,
                                to_y=count,
                                width=20,
                                color=ft.Colors.PURPLE_400,
                                tooltip=f"{item['tag']}: {count}",
                                border_radius=5
                            )
                        ]
                    )
                )

            if self.vs_bar_chart.current:
                self.vs_bar_chart.current.groups = bar_groups
                # Create custom axis labels
                axis_labels = []
                for i, item in enumerate(genre_counts):
                     # Truncate long genre names
                     tag_name = item['tag']
                     if len(tag_name) > 10: tag_name = tag_name[:8] + ".."

                     axis_labels.append(ftc.ChartAxisLabel(value=i, label=ft.Container(ft.Text(tag_name, size=10), padding=5)))

                self.vs_bar_chart.current.bottom_axis.labels = axis_labels
                self.vs_bar_chart.current.max_y = max_count + 5

            # Update Hours Chart
            genre_hours = stats.get("genre_hours", [])
            hours_groups = []
            max_hours = 0

            for i, item in enumerate(genre_hours):
                count = item["count"]
                if count > max_hours: max_hours = count
                hours_groups.append(
                    ftc.BarChartGroup(
                        x=i,
                        rods=[
                            ftc.BarChartRod(
                                from_y=0,
                                to_y=count,
                                width=20,
                                color=ft.Colors.TEAL_400,
                                tooltip=f"{item['tag']}: {count}h",
                                border_radius=5
                            )
                        ]
                    )
                )

            if self.vs_hours_chart.current:
                self.vs_hours_chart.current.groups = hours_groups
                # Axis Labels for Hours
                hours_axis_labels = []
                for i, item in enumerate(genre_hours):
                     tag_name = item['tag']
                     if len(tag_name) > 10: tag_name = tag_name[:8] + ".."
                     hours_axis_labels.append(ftc.ChartAxisLabel(value=i, label=ft.Container(ft.Text(tag_name, size=10), padding=5)))

                self.vs_hours_chart.current.bottom_axis.labels = hours_axis_labels
                self.vs_hours_chart.current.max_y = max_hours + 10

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
