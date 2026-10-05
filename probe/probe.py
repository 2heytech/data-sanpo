import sys, re, urllib.request
from pathlib import Path
sys.path.insert(0, "pipeline")
from tdm import xlsx
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def getb(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
TAG = re.compile(r"<[^>]+>")
def text(h): return re.sub(r"\s+", " ", TAG.sub(" ", h))
for y in range(2014, 2026):
    url = f"https://www.e-stat.go.jp/stat-search/files?page=1&toukei=00250012&tstat=000001018034&tclass1=000001060399&layout=dataset&cycle=1&year={y}0&month=24101212"
    try: h = getb(url).decode("utf-8", "replace")
    except Exception as e: print(y, "ERR", e); continue
    # split into items by the title anchor
    items = re.split(r'class="stat-dataset_list-item', h)
    for it in items[1:]:
        t = text(it)
        ids = re.findall(r"statInfId=(\d+)(?:&amp;|&)fileKind=(\d)", it)
        m = re.search(r"(\S*市区町村別\S*(?: \S+){0,6})", t)
        if ids and "市区町村" in t:
            print(y, ids, "::", t[:160])
