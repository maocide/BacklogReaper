import flet as ft
import time
import sys

class MyControl(ft.Column):
    def __init__(self):
        super().__init__()
        self.controls = [ft.Text("Hello from Column subclass")]

    def did_mount(self):
        print("MyControl did_mount executed")
        sys.exit(0)

def main(page: ft.Page):
    c = MyControl()
    page.add(c)
    time.sleep(2)
    print("Main finished without mount?")
    sys.exit(1)

if __name__ == "__main__":
    ft.app(target=main)
