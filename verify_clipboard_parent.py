import flet as ft
import inspect
import asyncio

def main():
    print("Testing Clipboard instantiation...")
    try:
        # Simulate context page if needed, but we can't easily without a full running app.
        # However, we can check if Clipboard() has a parent.
        c = ft.Clipboard()
        print(f"Clipboard parent: {c.parent}")

        try:
            p = c.page
            print(f"Clipboard page: {p}")
        except RuntimeError as e:
            print(f"Clipboard page access failed: {e}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
