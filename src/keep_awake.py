import os
from playwright.sync_api import sync_playwright

url = os.environ["STREAMLIT_APP_URL"]

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(url, timeout=60000)
    page.wait_for_timeout(6000)

    try:
        wake_button = page.get_by_text("Yes, get this app back up!", exact=False)
        if wake_button.is_visible():
            wake_button.click()
            print("App was asleep — clicked wake button. Waiting for it to fully wake up...")
            try:
                wake_button.wait_for(state="hidden", timeout=120000)
                print("App woke up successfully.")
            except Exception:
                print("Wake button still visible after 2 min — app may be slow or stuck.")
            page.wait_for_timeout(5000)
        else:
            print("App already awake.")
    except Exception as e:
        print(f"No wake button found (app likely already awake). Details: {e}")

    browser.close()