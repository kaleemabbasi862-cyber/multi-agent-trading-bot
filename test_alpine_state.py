import time
import json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto('http://localhost:8000/', wait_until='networkidle')
    time.sleep(2)
    state = page.evaluate('() => { var el = document.querySelector("[x-data]"); return el ? el._x_dataStack[0].cbotStatus : null; }')
    print('Alpine cbotStatus in page:', json.dumps(state, indent=2))
    browser.close()
