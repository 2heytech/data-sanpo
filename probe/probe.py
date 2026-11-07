import json, re, subprocess, os
UA = "Mozilla/5.0 (data-sanpo probe)"
def get(u):
    r = subprocess.run(["curl", "-sSL", "-A", UA, "--max-time", "120", "-w", "\n%{http_code}", u], capture_output=True)
    body, _, code = r.stdout.rpartition(b"\n")
    return body, code.decode()
home, _ = get("https://data-sanpo.com/map/")
rel = re.search(r'data-base="/data/([^"]+)"', home.decode()).group(1)
print("release", rel)
cat = json.loads(get(f"https://data-sanpo.com/data/{rel}/indicators.json")[0])["indicators"]
by = {i["id"]: i for i in cat}
print("indicators", len(cat))
NEW = ["care_facility_capacity", "care_facility_capacity_per_1000_elderly", "city_park_area_per_capita", "sewage_treatment_coverage",
       "child_medical_age_outpatient", "child_medical_age_inpatient", "water_fee_household", "in_migration_rate", "out_migration_rate",
       "migration_in_out_ratio", "child_woman_ratio", "restaurants", "restaurants_per_1000", "food_retail_establishments",
       "food_retail_per_inhabitable_km2", "corporate_tax_per_capita", "hospital_clinic_beds", "hospital_clinic_beds_per_100k",
       "floor_area_per_person"]
for k in NEW:
    i = by.get(k)
    if not i:
        print("MISSING", k); continue
    p = i["periods"][-1]
    page, code = get(f"https://data-sanpo.com/indicators/{k}/")
    title = re.search(rb"<title>([^<]*)</title>", page)
    rows = json.loads(get(f"https://data-sanpo.com/data/{rel}/values/{k}/{p['period']}/municipalities.json")[0])["rows"]
    n = sum(r.get("value") is not None for r in rows)
    print(f"{k} | {i['category']} | {p['label']} | page {code} {title.group(1).decode() if title else ''} | munis with value {n}/{len(rows)}")
from playwright.sync_api import sync_playwright
os.makedirs("/tmp/shots", exist_ok=True)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 800})
    for k in ["water_fee_household", "child_medical_age_outpatient", "care_facility_capacity_per_1000_elderly"]:
        pg.goto(f"https://data-sanpo.com/map/?i={k}&l=municipality", wait_until="networkidle", timeout=120000)
        pg.wait_for_timeout(6000)
        pg.screenshot(path=f"/tmp/shots/map_{k}.png")
        print("shot", k, pg.title())
    pg.goto("https://data-sanpo.com/indicators/water_fee_household/", wait_until="networkidle")
    pg.screenshot(path="/tmp/shots/page_water.png")
    b.close()
