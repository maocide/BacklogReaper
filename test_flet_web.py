import flet as ft
import flet_gui
import os
import signal
import sys

def wrapped_main(page):
    print("Wrapped main called!")
    try:
        flet_gui.main(page)
        print("flet_gui.main finished setup")
    except Exception as e:
        print(f"Error in main: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("Starting Flet Web App for Testing...")
    try:
        ft.app(target=wrapped_main, view=ft.AppView.WEB_BROWSER, port=8550)
    except Exception as e:
        print(f"Error starting app: {e}")
