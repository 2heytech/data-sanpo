import sys, re, urllib.request
from pathlib import Path
sys.path.insert(0, "pipeline")
from tdm import xlsx
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def getb(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
TAG = re.compile(r"<[^>]+>")
def text(h): return re.sub(r"\s+", " ", TAG.sub(" ", h))
for t1 in ["000001060399", "000001060436"]:
    base = f"https://www.e-stat.go.jp/stat-search/files?page={{p}}&layout=datalist&toukei=00250012&tstat=000001018034&cycle=1&tclass1={t1}&tclass2val=0"
    print("=== tclass1", t1)
    seen = set()
    for p in range(1, 60):
        h = getb(base.format(p=p)).decode("utf-8", "replace")
        ids = re.findall(r"statInfId=(\d+)", h)
        new = [i for i in ids if i not in seen]
        if not new:
            # maybe a class listing
            t2s = re.findall(r"tclass2=(\d+)", h)
            if p == 1: print(" no files; tclass2:", t2s[:30], text(h)[200:600])
            break
        prev = 0
        for m in re.finditer(r"statInfId=(\d+)(?:&amp;|&)fileKind=(\d)", h):
            t = text(h[prev:m.start()]); prev = m.end()
            if m.group(1) in seen: continue
            seen.add(m.group(1))
            mm = re.findall(r"(\d\d-\d\d-[0-9a-zA-Z-]+ [^ ]+)", t)
            label = mm[-1] if mm else t[-80:]
            if "市区町村" in t[-200:] or "t2" in label or "-07" in label:
                print(f"  p{p} {m.group(1)} k{m.group(2)} :: {label} :: {t[-120:]}")
d = getb("https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040186957&fileKind=0")
p = Path("t2.xlsx"); p.write_bytes(d)
for r in xlsx.read_sheet(p, "注意事項"): print("NOTE", [c for c in r if c and c != "None"])
