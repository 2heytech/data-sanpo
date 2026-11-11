import json, re, subprocess
UA = "Mozilla/5.0 (data-sanpo probe)"
def get(u):
    return subprocess.run(["curl", "-sSL", "-A", UA, "--max-time", "120", u], capture_output=True).stdout
home = get("https://data-sanpo.com/map/").decode()
rel = re.search(r'data-base="/data/([^"]+)"', home).group(1)
print("release", rel)
B = f"https://data-sanpo.com/data/{rel}"
def J(p):
    return json.loads(get(f"{B}/{p}"))
cat = {i["id"]: i for i in J("indicators.json")["indicators"]}
areas = J("areas.json")
name = {m["id"]: m["name"] for m in areas["municipalities"]}
prefname = {("pref-" + p["id"][-2:] if not p["id"].startswith("pref-") else p["id"]): p["name"] for p in areas["prefectures"]}
print("TFR unit:", repr(cat["total_fertility_rate"]["unit"]))
print("furusato periods:", [p["period"] for p in cat["furusato_amount"]["periods"]])
print("population periods:", [p["period"] for p in cat["population_total"]["periods"]])
def rows(ind, period, level="municipalities"):
    return {r["entity_id"]: r for r in J(f"values/{ind}/{period}/{level}.json")["rows"]}
p20 = rows("population_total", "2020-10-01")
p25 = rows("population_total", "2025-10-01")
print("pop rows 2020:", len(p20), "with value", sum(r["value"] is not None for r in p20.values()),
      "| 2025:", len(p25), "with value", sum(r["value"] is not None for r in p25.values()))
only20 = [e for e, r in p20.items() if r["value"] is not None and (e not in p25 or p25[e]["value"] is None)]
only25 = [e for e, r in p25.items() if r["value"] is not None and (e not in p20 or p20[e]["value"] is None)]
print("2020 only:", [(e, name.get(e)) for e in only20])
print("2025 only:", [(e, name.get(e)) for e in only25])
P = "2025-04-01"
amt = rows("furusato_amount", P)
pc = rows("furusato_amount_per_capita", P)
print("amount rows", len(amt), "with value", sum(r["value"] is not None for r in amt.values()),
      "| per capita rows", len(pc), "with value", sum(r["value"] is not None for r in pc.values()))
new = {}
lost = []
for e, r in amt.items():
    d = p25.get(e)
    if d is None:
        if e in pc: lost.append((e, name.get(e), "no 2025 row"))
        continue
    if r["value"] is None or d["value"] is None:
        new[e] = None
        if pc.get(e, {}).get("value") is not None: lost.append((e, name.get(e), "2025 value none"))
        continue
    new[e] = r["value"] / d["value"] * 1e6 if d["value"] > 0 else None
print("new per capita rows", len(new), "with value", sum(v is not None for v in new.values()), "lost:", lost)
def top(d, n=15):
    return sorted(((v, e) for e, v in d.items() if v is not None), reverse=True)[:n]
old = {e: r["value"] for e, r in pc.items()}
print("== top 15 now (2020 pop)")
for i, (v, e) in enumerate(top(old), 1):
    print(i, e, name.get(e), round(v), "pop20", p20.get(e, {}).get("value"))
print("== top 15 new (2025 pop)")
for i, (v, e) in enumerate(top(new), 1):
    print(i, e, name.get(e), round(v), "pop25", p25.get(e, {}).get("value"))
for nm in ["赤村", "北山村", "別海町", "白糠町"]:
    for e, n_ in name.items():
        if n_ == nm:
            ro = [x for _, x in top(old, 2000)].index(e) + 1 if old.get(e) is not None else None
            rn = [x for _, x in top(new, 2000)].index(e) + 1 if new.get(e) is not None else None
            print(nm, e, "old rank", ro, round(old[e]) if old.get(e) else None, "new rank", rn, round(new[e]) if new.get(e) else None)
# 上位3%の顔ぶれ（地域ページの考察に使う）
n_old = sum(v is not None for v in old.values()); n_new = sum(v is not None for v in new.values())
t_old = {e for _, e in top(old, int(n_old * 0.03))}; t_new = {e for _, e in top(new, int(n_new * 0.03))}
print("top3% old", len(t_old), "new", len(t_new), "left:", [(e, name.get(e)) for e in t_old - t_new], "joined:", [(e, name.get(e)) for e in t_new - t_old])
# 値の変わり方
import statistics
ch = [(new[e] / old[e] - 1) * 100 for e in new if new.get(e) and old.get(e)]
print("change % median", round(statistics.median(ch), 2), "min", round(min(ch), 1), "max", round(max(ch), 1))
# 都道府県
ppc = rows("furusato_amount_per_capita", P, "prefectures")
pam = rows("furusato_amount", P, "prefectures")
beds = rows("hospital_clinic_beds_per_100k", cat["hospital_clinic_beds_per_100k"]["periods"][-1]["period"], "prefectures")
print("pref per capita with value (now):", sum(r["value"] is not None for r in ppc.values()), "/", len(ppc),
      "| beds per 100k pref (2025 pop) with value:", sum(r["value"] is not None for r in beds.values()), "/", len(beds))
sums25 = {}
for e, r in p25.items():
    k = "pref-" + e[5:7]
    sums25.setdefault(k, []).append(r["value"])
for k in sorted(ppc):
    r = ppc[k]; vals = sums25.get(k, [])
    ok = all(v is not None for v in vals)
    d25 = sum(vals) if ok else None
    bd = beds.get(k, {}).get("denominator")
    print(k, "den now", r.get("denominator"), "sum25", d25, "beds den", bd, "value now", round(r["value"]) if r["value"] is not None else None,
          "new", round(pam[k]["value"] / d25 * 1e6) if ok and pam.get(k, {}).get("value") is not None else None)
# ほかの年度で、2025年の人口がなくて値がなくなる市区町村
for per in [p["period"] for p in cat["furusato_amount"]["periods"]][::3]:
    a = rows("furusato_amount", per); c = rows("furusato_amount_per_capita", per)
    gone = [e for e, r in c.items() if r["value"] is not None and (p25.get(e, {}).get("value") is None)]
    print(per, "per capita with value", sum(r["value"] is not None for r in c.values()), "would lose", len(gone), gone[:5])
