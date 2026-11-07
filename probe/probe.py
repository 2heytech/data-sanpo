import json, re, subprocess
UA = "Mozilla/5.0 (data-sanpo probe)"
def get(u):
    return subprocess.run(["curl", "-sSL", "-A", UA, "--max-time", "120", u], capture_output=True).stdout
home = get("https://data-sanpo.com/map/").decode()
rel = re.search(r'data-base="/data/([^"]+)"', home).group(1)
print("release", rel)
cat = {i["id"]: i for i in json.loads(get(f"https://data-sanpo.com/data/{rel}/indicators.json"))["indicators"]}
print("TFR caveat:", [c for c in cat["total_fertility_rate"].get("caveats", []) if "ベイズ" in c])
for k, p in [("child_medical_age_outpatient", "2025-04-01"), ("sewage_treatment_coverage", "2026-03-31")]:
    rows = json.loads(get(f"https://data-sanpo.com/data/{rel}/values/{k}/{p}/municipalities.json"))["rows"]
    print(k, "rows", len(rows), "with value", sum(r.get("value") is not None for r in rows))
    for r in rows:
        if r["entity_id"].startswith("muni-431") or r["entity_id"] == "muni-29441":
            print("  ", r)
page = get("https://data-sanpo.com/indicators/total_fertility_rate/").decode()
print("TFR page has 都道府県の出生:", "その市区町村を含む都道府県の出生" in page, "/ old text:", "二次医療圏" in page)
