import re, urllib.request
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def getb(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
TAG = re.compile(r"<[^>]+>")
def text(h): return re.sub(r"\s+", " ", TAG.sub(" ", h))
def show(url):
    print("=== ", url)
    h = getb(url).decode("utf-8", "replace")
    seen = set()
    for m in re.finditer(r"(tclass\d|year|month)=(\d+)", h):
        if m.group(0) in seen: continue
        seen.add(m.group(0))
        after = re.sub(r'^[^>]*>', '', h[m.end():m.end() + 500])
        print("  ", m.group(0), "::", text(after)[:70])
    prev = 0
    for m in re.finditer(r"statInfId=(\d+)(?:&amp;|&)fileKind=(\d)", h):
        seg = text(h[prev:m.start()]); prev = m.end()
        if "外国人" in seg[-400:]:
            print("   FILE", m.group(1), "k" + m.group(2), "::", seg[-260:])
    return h
show("https://www.e-stat.go.jp/stat-search/files?page=1&layout=datalist&toukei=00200241&tstat=000001039591&tclass1val=0")
show("https://www.e-stat.go.jp/stat-search/files?page=1&toukei=00200241&tstat=000001039591&layout=datalist&cycle=7")
for y in (2025, 2026):
    show(f"https://www.e-stat.go.jp/stat-search/files?page=1&toukei=00200241&tstat=000001039591&layout=dataset&cycle=7&year={y}0")
