import flet as ft
import styles

class MetricCard(ft.Card):
    def __init__(self, title, value_ref, icon, color=ft.Colors.WHITE):
        super().__init__()
        self.elevation = 5
        self.bgcolor = styles.COLOR_SURFACE
        self.shape = ft.RoundedRectangleBorder(radius=10)

        self.title = title
        self.value_ref = value_ref
        self.icon = icon
        self.color = color

        self.content = self._build_content()

    def _build_content(self):
        return ft.Container(
            content=ft.Column([
                ft.Row([ft.Icon(self.icon, color=styles.COLOR_TEXT_GOLD), ft.Text(self.title, weight=ft.FontWeight.BOLD, color=styles.COLOR_TEXT_SECONDARY)], alignment=ft.MainAxisAlignment.CENTER),
                ft.Text("0", ref=self.value_ref, size=30, weight=ft.FontWeight.BOLD, color=self.color, text_align=ft.TextAlign.CENTER)
            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=20,
            #width=200,
            height=120,
            border=ft.border.all(1, styles.COLOR_BORDER_BRONZE),
            border_radius=10
        )
