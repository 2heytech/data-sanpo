import sys, io, zipfile, urllib.request, subprocess
from pathlib import Path
sys.path.insert(0, "pipeline")
from tdm import xlsx
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def get(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
def s(r, n=12): return [str(c)[:20] for c in r][:n]
sid = "000001085975"
d = get(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind=0")
p = Path(f"{sid}.xlsx"); p.write_bytes(d)
names = xlsx.sheet_names(p); print("##", sid, len(d), names)
for n in names[:1] + names[-1:]:
    rows = xlsx.read_sheet(p, n); print("  --", n, len(rows))
    for r in rows[:9]: print("   ", [str(c) for c in r if c is not None][:3])
    for r in rows:
        if any(str(c).strip() in ("01236", "北斗市", "01100", "01101", "01000") for c in r[:5] if c is not None):
            print("   HIT", s(r))
sid = "000001085925"
d = get(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind=0")
p = Path(f"{sid}.xlsx"); p.write_bytes(d)
z = zipfile.ZipFile(p); print("## t1 names", z.namelist()[:20])
print(z.read("[Content_Types].xml")[:600])
wb = [n for n in z.namelist() if "workbook" in n.lower()]
for n in wb[:2]: print(n, z.read(n)[:800])
