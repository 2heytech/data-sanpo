import sys, re, urllib.request, collections
from pathlib import Path
sys.path.insert(0, "pipeline")
from tdm import xlsx
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def getb(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
d = getb("https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040472266&fileKind=0")
p = Path("a.xlsx"); p.write_bytes(d)
rows = xlsx.read_sheet(p, "PVT")
print("nrows", len(rows), collections.Counter(len(r) for r in rows).most_common(6))
for i, r in enumerate(rows[:14]): print(i, len(r), [str(c)[:8] for c in r if str(c) != "None"][:40])
wide = [i for i, r in enumerate(rows) if len(r) >= 100]
print("wide rows", wide[:5], len(wide))
if wide:
    w = wide[0]
    for i in range(max(0, w - 3), w + 4): print("W", i, [str(c)[:8] for c in rows[i]][:60])
codes = [r for r in rows if r and re.fullmatch(r"\d{5}", str(r[0]))]
print("coded rows", len(codes), "distinct", len({r[0] for r in codes}))
print("13101 rows", [[str(c)[:8] for c in r][:12] for r in codes if r[0] == "13101"][:5])
for sid in ("000040472260",):
    for k in ("0", "4"):
        try: d = getb(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind={k}")
        except Exception as e: print(sid, k, e); continue
        q = Path(f"{sid}{k}.xlsx"); q.write_bytes(d)
        if d[:2] != b"PK": print(sid, k, d[:10]); continue
        for sn in xlsx.sheet_names(q):
            rr = xlsx.read_sheet(q, sn)
            print("##", sid, k, sn, len(rr))
            for i, r in enumerate(rr[:6]): print("  ", i, [str(c)[:10] for c in r][:10])
