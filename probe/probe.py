import base64, os
from playwright.sync_api import sync_playwright
os.makedirs("/tmp/shots", exist_ok=True)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 800})
    for k in ["water_fee_household", "child_medical_age_outpatient"]:
        pg.goto(f"https://data-sanpo.com/map/?i={k}&l=municipality", wait_until="networkidle", timeout=120000)
        pg.wait_for_timeout(8000)
        data = pg.screenshot(type="jpeg", quality=55)
        print(f"SHOT {k} " + base64.b64encode(data).decode())
    b.close()
