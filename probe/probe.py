import json, os, re, urllib.request
os.makedirs("/tmp/shots", exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0"}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read().decode("utf-8")
S = "https://data-sanpo.com"
html = get(S + "/indicators/owner_occupied_share/")
rid = re.search(r"/data/([^/\"']+)/", html)
print("RID", rid and rid[1])
for kw in ("2025年", "2020年", "間借りは分母に含みます"):
    print("HTML has", kw, kw in html)
base = f"{S}/data/{rid[1]}"
cat = json.loads(get(base + "/indicators.json"))
by = {i["id"]: i for i in cat["indicators"]}
for k in ("owner_occupied_share", "private_rented_share", "high_rise_household_share", "jhs_progress_private", "land_price_residential"):
    i = by[k]
    print("IND", k, [(p["period"], p.get("label"), p.get("levels")) for p in i["periods"]][-4:], "default", i.get("default_period"))
def row(ind, period, eid, level="municipalities"):
    d = json.loads(get(f"{base}/values/{ind}/{period}/{level}.json"))
    r = {x["entity_id"]: x for x in d["rows"]}.get(eid)
    print("VAL", ind, period, eid, r and {k: r.get(k) for k in ("value", "numerator", "denominator", "status")})
row("owner_occupied_share", "2025-10-01", "muni-13101")
row("private_rented_share", "2025-10-01", "muni-13101")
row("high_rise_household_share", "2025-10-01", "muni-13101")
row("high_rise_household_share", "2025-10-01", "pref-13", "prefectures")
row("jhs_progress_private", "2023-03-31", "muni-13101")
row("jhs_progress_private", "2024-03-31", "muni-13101")
row("jhs_progress_private", "2025-03-31", "muni-13105")
pl = json.loads(get(f"{base}/places/land_survey_price.json"))
print("PLACES", list(pl)[:12], [p["period"] for p in pl.get("periods", [])][-3:], str(pl.get("prefectures", ""))[:200])
try:
    p13 = json.loads(get(f"{base}/places/land_survey_price/13.json"))
    periods = [p["period"] for p in (p13.get("periods") or pl.get("periods"))]
    pt = next(x for x in p13["points"] if x.get("name") == "千代田(都)-1")
    print("PT", pt["name"], dict(zip(periods[-2:], pt["values"][-2:])))
except Exception as e:
    print("ERR places", repr(e))
for path in ("/map/?i=owner_occupied_share", "/indicators/jhs_progress_private/", "/indicators/land_survey_price/"):
    try:
        h = get(S + path); print("PAGE", path, len(h), "2026年" in h, "2023年3月卒業" in h)
    except Exception as e:
        print("PAGE", path, repr(e))
