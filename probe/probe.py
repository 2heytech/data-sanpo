import sys, re, urllib.request
from pathlib import Path
sys.path.insert(0, "pipeline")
from tdm import xlsx
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def get(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
def s(r, n=22): return [str(c)[:16] for c in r][:n]
def dl(sid):
    d = get(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind=0")
    ext = "xlsx" if d[:2] == b"PK" else "xls"
    p = Path(f"{sid}.{ext}"); p.write_bytes(d); print("##", sid, ext, len(d)); return p
def isname(c, keys): return c is not None and any(k in str(c) for k in keys)
# 住宅・土地統計
for sid in ("000040209921", "000040209842", "000031865704", "000031865669"):
    try:
        p = dl(sid)
        if p.suffix != ".xlsx": continue
        for n in xlsx.sheet_names(p)[:3]:
            rows = xlsx.read_sheet(p, n); print("  --", n, len(rows))
            for r in rows[:16]: print("   ", s(r))
            for i, r in enumerate(rows):
                if any(isname(c, ("13101", "千代田区", "13000", "東京都", "01303", "当別町")) for c in r[:8]):
                    print("   HIT", i, s(r, 30))
            print("   LAST", s(rows[-1], 30))
    except Exception as e: print("ERR", sid, e)
# 出生率: 東京都の行
try:
    p = dl("000040174881"); rows = xlsx.read_sheet(p, xlsx.sheet_names(p)[0])
    for i, r in enumerate(rows):
        c0 = str(r[0] or "")
        if c0.startswith("13") or c0.startswith("01") and i < 80: print("   TFR", i, s(r, 12))
    import collections
    print("   PREFIXLEN", collections.Counter(len(re.match(r"\d*", str(r[0] or "").strip()).group()) for r in rows))
except Exception as e: print("ERR tfr", e)
# 生命表: 千代田区の表と女
try:
    p = dl("000040052725")
    for n in xlsx.sheet_names(p)[1:3]:
        rows = xlsx.read_sheet(p, n)
        for i, r in enumerate(rows):
            if any(isname(c, ("表13101", "表13000", "表00000")) for c in r[:6]):
                for rr in rows[i:i+8]: print("   LT", n, s(rr))
                for j in range(i+1, min(i+400, len(rows))):
                    if any(str(c).strip() == "女" for c in rows[j][:10] if c is not None):
                        for rr in rows[j:j+3]: print("   LTF", j, s(rr))
                        break
    rows = xlsx.read_sheet(p, "目次")
    print("   TOC", len(rows)); [print("   ", s(r)) for r in rows[:6]]
    print("   TOC-13", [s(r) for r in rows if "13101" in str(r) or "1310" in str(r)[:40]][:3])
except Exception as e: print("ERR lt", e)
