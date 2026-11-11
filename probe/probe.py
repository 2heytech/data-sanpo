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
areas = J("areas.json")
name = {m["id"]: m["name"] for m in areas["municipalities"]}
def rows(ind, period, level="municipalities"):
    return {r["entity_id"]: r for r in J(f"values/{ind}/{period}/{level}.json")["rows"]}
p25 = rows("population_total", "2025-10-01")
p20 = rows("population_total", "2020-10-01")
for per in ["2020-04-01", "2021-04-01", "2022-04-01", "2023-04-01", "2024-04-01", "2025-04-01"]:
    amt = rows("furusato_amount", per)
    pc = rows("furusato_amount_per_capita", per)
    new = {e: r["value"] / p25[e]["value"] * 1e6 for e, r in amt.items()
           if r["value"] is not None and p25.get(e, {}).get("value")}
    old = {e: r["value"] for e, r in pc.items() if r["value"] is not None}
    tn = sorted(((v, e) for e, v in new.items()), reverse=True)[:4]
    to = sorted(((v, e) for e, v in old.items()), reverse=True)[:4]
    print(per, "NEW(2025 pop):", [(name.get(e), round(v)) for v, e in tn])
    print(per, "OLD(2020 pop):", [(name.get(e), round(v)) for v, e in to])
    f = "muni-07546"
    print("   双葉町 amount", amt.get(f, {}).get("value"), "new", round(new[f]) if f in new else None,
          "rank", sorted(new.values(), reverse=True).index(new[f]) + 1 if f in new else None)
P = "2025-04-01"
amt = rows("furusato_amount", P)
s, b = "muni-01668", "muni-01691"
ns = amt[s]["value"] / p25[s]["value"] * 1e6; nb = amt[b]["value"] / p25[b]["value"] * 1e6
print("白糠", round(ns), "別海x2", round(2 * nb), "ok", ns > 2 * nb, "| pop25 白糠", p25[s]["value"], "北山", p25["muni-30427"]["value"])
