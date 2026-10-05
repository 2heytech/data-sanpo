import sys, re, urllib.request
from pathlib import Path
sys.path.insert(0, "pipeline")
from tdm import xlsx
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def getb(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
TAG = re.compile(r"<[^>]+>")
def text(h): return re.sub(r"\s+", " ", TAG.sub(" ", h))
PAT = re.compile(r"(t2 在留外国人統計テーブルデータ（国籍・地域別 在留資格別 市区町村別）|\d\d-12-0[37](?:-1)? 市区町村別 国籍・地域別)")
for y in range(2019, 2026):
    url = f"https://www.e-stat.go.jp/stat-search/files?page=1&toukei=00250012&tstat=000001018034&tclass1=000001060399&layout=dataset&cycle=1&year={y}0&month=24101212"
    h = getb(url).decode("utf-8", "replace")
    links = [(m.start(), m.group(1), m.group(2)) for m in re.finditer(r"statInfId=(\d+)(?:&amp;|&)fileKind=(\d)", h)]
    t = PAT.search(text(h))
    pos = [m.start() for m in re.finditer(re.escape(t.group(1).split(" ")[0]) if t else "zzz", h)]
    cands = []
    for p in pos:
        near = [l for l in links if abs(l[0] - p) < 6000]
        for l in near:
            if (l[1], l[2]) not in cands: cands.append((l[1], l[2]))
    print("##", y, t.group(1) if t else None, cands[:8])
    for sid, k in cands[:8]:
        try: d = getb(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind={k}")
        except Exception as e: print("  ", sid, k, "ERR", e); continue
        if d[:2] != b"PK": print("  ", sid, k, "not xlsx", d[:20]); continue
        p = Path(f"{sid}.xlsx"); p.write_bytes(d)
        names = xlsx.sheet_names(p)
        print("  ", sid, k, len(d), names[:6])
        for sn in names[-1:]:
            rows = xlsx.read_sheet(p, sn)
            for i, r in enumerate(rows[:9]): print("     ", i, [str(c)[:10] for c in r][:14])
            hit = [r for r in rows if any(str(c).startswith(("千代田", "13101")) for c in r[:4])][:2]
            for r in hit: print("      HIT", [str(c)[:10] for c in r][:16])
            print("      nrows", len(rows), "maxcols", max(len(r) for r in rows))
