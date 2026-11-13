import csv, io, json, subprocess, zipfile, collections, statistics
URL = "https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/9112b58e-556c-429e-906f-45be48b63fd9/db7e75fb/20260703_resources_govdashboard_watersupply_table_02.zip"
subprocess.run(["curl", "-sSL", "--max-time", "300", "-o", "/tmp/w.zip", URL], check=True)
z = zipfile.ZipFile("/tmp/w.zip")
print("files", z.namelist())
items = collections.Counter()
data = {}   # year -> (code, fac) -> dict
for n in z.namelist():
    if not n.endswith(".csv"):
        continue
    y = int(n.rsplit("/", 1)[-1][:4])
    t = z.read(n).decode("utf-8-sig")
    rd = csv.DictReader(io.StringIO(t))
    if y == 2024:
        print("columns", rd.fieldnames)
    for r in rd:
        if r["item_name"].startswith("6.料金") or r["item_name"].startswith("4.施設__(3)"):
            items[r["item_name"]] += 1
            u = data.setdefault(y, {}).setdefault((r["local_public_enterprise_code"], r["facility_code"]),
                                                {"name": r["local_public_enterprise_name"], "ent": r["cond_2_operating_entity"]})
            v = r["item_value"].replace(",", "").strip()
            u[r["item_name"]] = float(v) if v else None
for k, c in sorted(items.items()):
    print("ITEM", c, k)
F20 = "6.料金__(2)料金(家庭用)__1か月20㎥当たり料金__口径20mm"
F10 = [k for k in items if "10㎥" in k]
print("F10 items", F10)
F10 = F10[0] if F10 else None
POP = "4.施設__(3)現在給水人口(人)"
d24 = data[2024]
fees = [u.get(F20) for u in d24.values() if u.get(F20)]
print("2024 rows with fee", len(fees), "median", statistics.median(fees))
for fac in ("001", "005", "006"):
    fs = sorted(u[F20] for (c, f), u in d24.items() if f == fac and u.get(F20))
    print("fac", fac, "n", len(fs), "lowest 15", fs[:15])
print("== 2024 fee20 < 1500 (all facilities)")
def hist(code, fac):
    return [(y, data[y].get((code, fac), {}).get(F20)) for y in sorted(data) if (code, fac) in data[y]]
low = sorted(((u[F20], c, f) for (c, f), u in d24.items() if u.get(F20) and u[F20] < 1500))
for fee, c, f in low:
    u = d24[(c, f)]
    print(c, f, u["name"], "ent", u["ent"][:12], "f20", fee, "f10", u.get(F10) if F10 else None, "pop", u.get(POP),
          "hist", [(y, v) for y, v in hist(c, f) if y < 2024][-4:], "other fac", [ff for (cc, ff) in d24 if cc == c and ff != f])
# 10m3 と 20m3 の差が小さい（単価の疑い）もの
print("== 2024 f20 - f10 < 300 or f20 < f10")
if F10:
    for (c, f), u in sorted(d24.items()):
        a, b = u.get(F10), u.get(F20)
        if a and b and (b - a < 300 or b < a):
            print(c, f, u["name"], "f10", a, "f20", b, "pop", u.get(POP), "hist", [(y, v) for y, v in hist(c, f) if y < 2024][-3:])
