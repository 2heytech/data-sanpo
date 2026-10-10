import sys, urllib.request
from pathlib import Path
sys.path.insert(0, "pipeline")
from tdm import xlsx
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def get(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
def s(r, n=14): return [str(c)[:22] for c in r][:n]
sid = "000001085925"
p = Path(f"{sid}.xlsx"); p.write_bytes(get(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind=0"))
names = xlsx.sheet_names(p); print("##", names)
for n in names:
    rows = xlsx.read_sheet(p, n); print("  --", n, len(rows))
    for r in rows[:14]: print("   ", s(r))
    for r in rows:
        if any(str(c).strip() in ("13", "13000", "東京都", "47", "47000", "沖縄県") for c in r[:6] if c is not None):
            print("   HIT", s(r))
    for r in rows[-12:]: print("   LAST", s(r))
