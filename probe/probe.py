import sys, re, urllib.request
from pathlib import Path
sys.path.insert(0, "pipeline")
from tdm import xlsx
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def getb(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
TAG = re.compile(r"<[^>]+>")
def text(h): return re.sub(r"\s+", " ", TAG.sub(" ", h))
for y in range(2014, 2027):
    url = f"https://www.e-stat.go.jp/stat-search/files?page=1&toukei=00200241&tstat=000001039591&layout=dataset&cycle=7&year={y}0"
    h = getb(url).decode("utf-8", "replace")
    links = [(m.start(), m.group(1), m.group(2)) for m in re.finditer(r"statInfId=(\d+)(?:&amp;|&)fileKind=(\d)", h)]
    cands = []
    prev = 0
    for i, (pos, sid, k) in enumerate(links):
        seg = text(h[prev:pos]); prev = pos
        if re.search(r"【外国人住民】市区町村別人口", seg[-500:]):
            for j in (i - 1, i, i + 1):
                if 0 <= j < len(links) and (links[j][1], links[j][2]) not in cands: cands.append((links[j][1], links[j][2]))
    found = None
    for sid, k in cands:
        try: d = getb(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind={k}")
        except Exception as e: continue
        if d[:2] != b"PK" and d[:4] != b"\xd0\xcf\x11\xe0": continue
        if d[:2] != b"PK": print(y, sid, k, "xls (old)"); continue
        p = Path(f"{sid}.xlsx"); p.write_bytes(d)
        names = xlsx.sheet_names(p); rows = xlsx.read_sheet(p, names[0])
        head = " ".join(str(c) for r in rows[:6] for c in r if str(c) != "None")
        if "市区町村" in head and "外国人" in head:
            found = sid
            print("##", y, sid, k, names, len(rows))
            for i, r in enumerate(rows[:7]): print("   ", i, [str(c)[:10] for c in r][:16])
            for r in rows:
                if r and str(r[0]).startswith(("131016", "13101")): print("    HIT", [str(c)[:10] for c in r][:16]); break
            break
    if not found: print(y, "not found; cands", cands)
