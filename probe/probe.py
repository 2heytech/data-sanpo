import sys, re, urllib.request, zipfile
from pathlib import Path
sys.path.insert(0, "pipeline")
from tdm import xlsx
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def getb(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
TAG = re.compile(r"<[^>]+>")
def text(h): return re.sub(r"\s+", " ", TAG.sub(" ", h))
for y in (2024, 2025):
    url = f"https://www.e-stat.go.jp/stat-search/files?page=1&toukei=00250012&tstat=000001018034&tclass1=000001060399&layout=dataset&cycle=1&year={y}0&month=24101212"
    h = getb(url).decode("utf-8", "replace")
    for m in re.finditer(r"statInfId=(\d+)(?:&amp;|&)fileKind=(\d)", h):
        before = text(h[max(0, m.start() - 4000):m.start()])
        lab = re.findall(r"\d\d-12-[0-9A-Za-z-]+ [^ ]+(?: [^ ]+){0,3}", before)
        print(y, m.group(1), "k" + m.group(2), "::", lab[-1] if lab else "?")
for sid in ("000040292373", "000040472266"):
    d = getb(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind=0")
    p = Path(f"{sid}.xlsx"); p.write_bytes(d)
    z = zipfile.ZipFile(p)
    print("##", sid, [(i.filename, i.file_size) for i in z.infolist() if i.file_size > 50000])
    rows = xlsx.read_sheet(p, "PVT")
    for i in range(4, 9): print("  ", i, [str(c)[:9] for c in rows[i]][:30])
    print("  last", [str(c)[:9] for c in rows[-1]][:20])
    hit = [r for r in rows if len(r) > 3 and str(r[0]) == "13101"]
    for r in hit[:3]: print("  HIT", [str(c)[:9] for c in r][:40])
    print("  ncols per row sample", sorted({len(r) for r in rows})[:10])
