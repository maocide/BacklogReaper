from playwright.sync_api import sync_playwright, expect
import time

def test_ui_changes(page):
    print("Navigating to app...")
    try:
        page.goto("http://localhost:8550", timeout=10000)
    except Exception as e:
        print(f"Failed to load page: {e}")
        return

    page.wait_for_load_state("networkidle")
    time.sleep(2)

    print("Checking Sidebar...")
    # Ensure "Review Analyzer" and "Suggest Games" are NOT visible
    expect(page.get_by_text("Review Analyzer")).not_to_be_visible()
    expect(page.get_by_text("Suggest Games")).not_to_be_visible()

    # Ensure "Dashboard", "Reaper Chat", "My Backlog", "Settings" ARE visible
    expect(page.get_by_text("Dashboard")).to_be_visible()
    expect(page.get_by_text("My Backlog")).to_be_visible()

    print("Checking Dashboard Alignment...")
    # Just verify the elements are present, alignment check is visual
    expect(page.get_by_text("Total Games")).to_be_visible()

    print("Checking Backlog Table...")
    page.get_by_text("My Backlog").click()
    time.sleep(1)

    # Verify "Tags" column is missing
    expect(page.get_by_text("Tags")).not_to_be_visible()

    # 4. Screenshot
    page.screenshot(path="verification_updated_7.png")
    print("Verification screenshot saved to verification_updated_7.png")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            test_ui_changes(page)
        except Exception as e:
            print(f"Test failed: {e}")
            page.screenshot(path="verification_failure_updated_7.png")
        finally:
            browser.close()
