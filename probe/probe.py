import subprocess, sys, json, re, collections, urllib.request
from pathlib import Path
sh = lambda c: subprocess.run(c, shell=True)
pass
sys.path.insert(0, "/tmp/nw/pipeline")
from tdm.config import load_sources, load_indicators
from tdm.db import connect, init_schema, upsert_indicators, insert_observation
from tdm.fetch import fetch_source
from tdm.sources import find_files
from tdm.ingest import mhlw_care, mlit_parks, mlit_sewerage, cfa_child_medical, digital_water

UA = "Mozilla/5.0 (data-sanpo probe)"
def get(u):
    return subprocess.run(["curl", "-sSL", "-A", UA, "--max-time", "300", u], capture_output=True).stdout
home = get("https://data-sanpo.com/map/").decode("utf-8", "replace")
rel = re.search(r'data-base="/data/([^"]+)"', home).group(1)
print("release", rel)
areas = json.loads(get(f"https://data-sanpo.com/data/{rel}/areas.json"))
popf = json.loads(get(f"https://data-sanpo.com/data/{rel}/values/population_total/2025-10-01/municipalities.json"))
conn = connect(":memory:")
init_schema(conn)
conn.execute("PRAGMA foreign_keys = OFF")
catalog = load_indicators()
upsert_indicators(conn, catalog)
for p in areas["prefectures"]:
    conn.execute("INSERT INTO entities (entity_id, entity_type, name) VALUES (?, 'prefecture', ?)", (p["id"], p["name"]))
names = {}
for m in areas["municipalities"]:
    conn.execute("INSERT INTO entities (entity_id, entity_type, name, region) VALUES (?, 'municipality', ?, ?)",
                 (m["id"], m["name"], m["region"]))
    names[m["id"]] = m["name"]
print("entities", len(areas["prefectures"]), len(areas["municipalities"]))
for r in popf["rows"]:
    if r.get("value") is not None:
        insert_observation(conn, entity_id=r["entity_id"], indicator_id="population_total", definition_version=1,
                           value=r["value"], status="observed", period_start="2025-10-01", period_end="2025-10-01",
                           period_kind="point", source_id="pop")
sources = load_sources()
raw = Path("/tmp/raw")
def run(key, fn):
    cfg = sources[key]
    try:
        fetch_source(key, cfg, raw / key)
    except Exception as e:
        print(key, "FETCH FAILED", e); return
    files = find_files(raw / key, cfg["files"])
    print(f"\n===== {key} files={[f.name for f in files]}")
    try:
        res = fn(cfg, files)
    except Exception as e:
        import traceback; traceback.print_exc(); return
    print("result", json.dumps(res, ensure_ascii=False)[:3000])
def summary(ids, picks):
    for ind in ids:
        rows = conn.execute("SELECT entity_id, value, status, method_note FROM observations WHERE indicator_id = ?", (ind,)).fetchall()
        st = collections.Counter((r["entity_id"][:4], r["status"]) for r in rows)
        vals = sorted(r["value"] for r in rows if r["value"] is not None and r["entity_id"].startswith("muni"))
        print(f"-- {ind}: {dict(st)}")
        if vals:
            n = len(vals); print("   muni min/p10/median/p90/max", vals[0], vals[n//10], vals[n//2], vals[n*9//10], vals[-1])
        notes = collections.Counter((r["method_note"] or "")[:40] for r in rows if r["entity_id"].startswith("muni"))
        print("   notes", notes.most_common(8))
        covered = {r["entity_id"] for r in rows}
        miss = [f"{e}{names[e]}" for e in names if e not in covered]
        print("   municipalities without row", len(miss), miss[:30])
        for e in picks:
            r = next((x for x in rows if x["entity_id"] == e), None)
            print("   ", e, names.get(e), None if r is None else (r["value"], r["status"], r["method_note"]))
PICKS = ["muni-01101", "muni-01209", "muni-13101", "muni-13104", "muni-13201", "muni-13361", "muni-14101", "muni-14150",
         "muni-12101", "muni-27127", "muni-26100", "muni-26101", "muni-47201", "muni-40131", "muni-34101", "muni-37201", "muni-28205", "pref-13", "pref-01"]
run("mhlw_care_2024", lambda cfg, f: mhlw_care.ingest(conn, f[0], "s", catalog, (cfg["period"], cfg["period"], "point")))
summary(["care_facility_capacity"], PICKS)
run("mlit_parks_2025", lambda cfg, f: mlit_parks.ingest(conn, f[0], "s", catalog, (cfg["period"], cfg["period"], "point")))
summary(["city_park_area_per_capita"], PICKS)
run("mlit_sewerage_2026", lambda cfg, f: mlit_sewerage.ingest(conn, f[0], "s", catalog, cfg["period"]))
summary(["sewage_treatment_coverage"], PICKS)
fetch_source("cfa_child_medical_2025", sources["cfa_child_medical_2025"], raw / "cfa_child_medical_2025")
_t = subprocess.run(["pdftotext", "-layout", str(raw / "cfa_child_medical_2025" / "child_medical_2025.pdf"), "-"], capture_output=True, text=True).stdout.splitlines()
for i, l in enumerate(_t):
    if "安堵" in l or "奈良県" in l and ("三郷" in l or "平群" in l or "斑鳩" in l or "川西" in l or "三宅" in l):
        print("NARA", i, repr(l))
run("cfa_child_medical_2025", lambda cfg, f: cfa_child_medical.ingest(conn, f[0], "s", catalog, cfg["period"]))
summary(["child_medical_age_outpatient", "child_medical_age_inpatient"], PICKS)
run("digital_water_2024", lambda cfg, f: digital_water.ingest(conn, f[0], "s", catalog, cfg))
summary(["water_fee_household"], PICKS)
# 水道: 値なしの市区町村（注記ごと）
rows = conn.execute("SELECT entity_id, method_note FROM observations WHERE indicator_id = 'water_fee_household' AND value IS NULL").fetchall()
by = collections.defaultdict(list)
for r in rows:
    by[(r["method_note"] or "")[:30]].append(f"{r['entity_id'][5:]}{names.get(r['entity_id'], '')}")
for k, v in by.items():
    print("WATER NULL", k, len(v), " ".join(v))
