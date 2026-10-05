import sys, re, urllib.request, collections
from pathlib import Path
sys.path.insert(0, "pipeline")
from tdm import xlsx
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def get(sid):
    p = Path(f"{sid}.xlsx")
    p.write_bytes(urllib.request.urlopen(urllib.request.Request(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind=0", headers=UA), timeout=300).read())
    return p
def s(r): return [str(c)[:12] for c in r][:15]
for sid in ("000040306693", "000040479057"):
    p = get(sid); rows = xlsx.read_sheet(p, xlsx.sheet_names(p)[0])
    print("## juki", sid, len(rows))
    for r in rows[6:12]: print("  ", s(r))
    for r in rows:
        c = str(r[0])
        if c.startswith(("13", "14100", "14101", "01100", "01101", "47")) and (c.endswith("0001") or c[:5] in ("13101", "13361", "13362", "13421", "14100", "14101", "01100", "01101")): print("  P", s(r))
    print("  tail", [s(r) for r in rows[-3:]])
    bad = [s(r) for r in rows[7:] if not re.fullmatch(r"\d{6}", str(r[0]))]
    print("  noncode", bad[:5], len(bad))
for sid in ("000032213255", "000040068661"):
    p = get(sid); names = xlsx.sheet_names(p); rows = xlsx.read_sheet(p, names[0])
    print("## zairyu", sid, names, len(rows))
    for r in rows[:6]: print("  ", s(r))
    for r in rows:
        c = str(r[0]); t = " ".join(map(str, r[:2]))
        if c in ("13000", "13100", "13101", "13361", "13362", "13421", "14100", "14101", "01000") or "その他" in t or "北方" in t: print("  P", s(r))
    print("  tail", [s(r) for r in rows[-4:]])
    nonnum = collections.Counter(str(c) for r in rows[2:] for c in r[2:] if not re.fullmatch(r"-?\d+(\.0)?", str(c)))
    print("  nonnum", nonnum.most_common(8))
p = get("000040186957"); names = xlsx.sheet_names(p)
rows = xlsx.read_sheet(p, "令和５年末")
print("## zairyu2023", names, len(rows)); print("  ", [s(r) for r in rows[:3]])
codes = collections.Counter(); oth = []
for r in rows[1:]:
    codes[str(r[0])] += 1
    if "その他" in str(r[2]) or not re.fullmatch(r"\d{5,6}", str(r[0])): oth.append(s(r))
print("  oth", len(oth), oth[:8])
print("  codes sample", [c for c in codes if c.endswith("000") or c.startswith("13")][:30])
nat = collections.Counter(str(r[3]) for r in rows[1:]); print("  nat", len(nat), nat.most_common(15))
vals = collections.Counter(str(r[5]) for r in rows[1:] if not re.fullmatch(r"\d+(\.0)?", str(r[5]))); print("  nonnum", vals.most_common(5))
tot = sum(float(r[5]) for r in rows[1:] if re.fullmatch(r"\d+(\.0)?", str(r[5]))); print("  total", tot)
for n in names:
    if n != "令和５年末": print("  sheet", n, [s(r) for r in xlsx.read_sheet(p, n)[:4]])
