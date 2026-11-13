import csv, io, subprocess, zipfile, re, os, tomllib, urllib.parse
subprocess.run("sudo apt-get -qq install -y poppler-utils > /dev/null 2>&1", shell=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
cfg = tomllib.load(open("probe/sources.toml", "rb"))["digital_water_2024"]
subprocess.run(["curl", "-sSL", "--max-time", "300", "-o", "/tmp/w.zip", cfg["download_url"]], check=True)
z = zipfile.ZipFile("/tmp/w.zip")
K = {"f10_13": "6.料金__(2)料金(家庭用)__1か月10㎥当たり料金__口径13mm", "f10": "6.料金__(2)料金(家庭用)__1か月10㎥当たり料金__口径20mm",
     "f20_13": "6.料金__(2)料金(家庭用)__1か月20㎥当たり料金__口径13mm", "f20": "6.料金__(2)料金(家庭用)__1か月20㎥当たり料金__口径20mm",
     "pop": "4.施設__(3)現在給水人口(人)"}
inv = {v: k for k, v in K.items()}
data = {}
for n in z.namelist():
    y = int(n.rsplit("/", 1)[-1][:4])
    for r in csv.DictReader(io.StringIO(z.read(n).decode("utf-8-sig"))):
        k = inv.get(r["item_name"])
        if not k:
            continue
        u = data.setdefault(y, {}).setdefault((r["local_public_enterprise_code"], r["facility_code"]),
                                            {"name": r["local_public_enterprise_name"], "ent": r["cond_2_operating_entity"][:1]})
        v = r["item_value"].replace(",", "").strip()
        u[k] = float(v) if v else None
d = data[2024]
def main(code):
    for f in ("001", "005"):
        if d.get((code, f), {}).get("f20"):
            return f, d[(code, f)]
    return None, None
used = {}
for (code, f), u in d.items():
    if u["ent"] in "234":
        fac, m = main(code)
        if m:
            used[code] = (fac, m, "own")
for s in cfg.get("suppliers", {}):
    if len(s) == 6:
        fac, m = main(s)
        if m:
            used[s] = (fac, m, "supplier")
print("used", len(used))
def hist(code, fac):
    return [(y, data[y][(code, fac)].get("f20")) for y in sorted(data) if y < 2024 and (code, fac) in data[y]]
rows = sorted(used.items(), key=lambda x: x[1][1]["f20"])
print("== used, f20 < 1300 or f20-f10 < 400 or f20 < f10 or f20 > 3*f10")
for code, (fac, m, how) in rows:
    a, b = m.get("f10") or 0, m["f20"]
    if b < 1300 or b - a < 400 or b < a or (a and b > 3 * a):
        print(code, fac, m["name"], how, "13mm", m.get("f10_13"), m.get("f20_13"), "20mm", a, b, "pop", m.get("pop"), "hist", hist(code, fac)[-3:])
print("== highest 8")
for code, (fac, m, how) in rows[-8:]:
    print(code, fac, m["name"], how, "13mm", m.get("f10_13"), m.get("f20_13"), "20mm", m.get("f10"), m["f20"], "pop", m.get("pop"), "hist", hist(code, fac)[-3:])
# 沖縄県の伊是名村の料金
def fetch(u, p):
    r = subprocess.run(["curl", "-sSL", "-A", UA, "--max-time", "120", "-o", p, "-w", "%{http_code} %{content_type}", u], capture_output=True, text=True)
    return r.stdout
def dec(p):
    raw = open(p, "rb").read()
    for enc in ("utf-8", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")
for u in ["https://www.pref.okinawa.jp/machizukuri/suido/1012445/1012447.html", "https://www.pref.okinawa.jp/machizukuri/suido/1012445/1012448.html",
          "https://vill.izena.okinawa.jp/userfiles/files/topics/2018/0320/jigyo_naiyou.pdf", "https://vill.izena.okinawa.jp/lifeevent/residence/1539833929/"]:
    p = "/tmp/x" + ("pdf" if u.endswith(".pdf") else "html")
    st = fetch(u, p)
    print("####", st, u)
    if not st.startswith("200"):
        continue
    if u.endswith(".pdf"):
        t = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout
        for l in t.splitlines():
            if re.search(r"料金|円", l) and re.search(r"水道|㎥|m3|基本|超過|従量", l):
                print("   ", l.strip()[:200])
    else:
        s = dec(p)
        for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', s, flags=re.S | re.I):
            t = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if re.search(r"料金|水道|\.pdf|\.xlsx", t + m.group(1)):
                print("  link", t[:80], urllib.parse.urljoin(u, m.group(1)))
        txt = re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S))
        for l in re.split(r"\s{2,}", txt):
            if re.search(r"料金|円", l):
                print("   T", l.strip()[:200])
