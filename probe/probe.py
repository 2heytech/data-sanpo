import re, urllib.request
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def getb(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
TAG = re.compile(r"<[^>]+>")
def text(h): return re.sub(r"\s+", " ", TAG.sub(" ", h))
def show(url, pages=1, only=None):
    print("=== ", url)
    seen = set()
    for p in range(1, pages + 1):
        h = getb(url.format(p=p)).decode("utf-8", "replace")
        prev = 0; n = 0
        for m in re.finditer(r"statInfId=(\d+)(?:&amp;|&)fileKind=(\d)", h):
            t = text(h[prev:m.start()]); prev = m.end()
            if m.group(1) in seen: continue
            seen.add(m.group(1)); n += 1
            if only and not re.search(only, t[-250:]): continue
            print(f"  p{p} {m.group(1)} k{m.group(2)} :: {t[-150:]}")
        others = sorted(set(re.findall(r"(?:year|month|tclass2|tclass3)=(\d+)", h)))
        print(f"  page {p}: files {n}, params {others[:40]}")
        if not n: print("   body:", text(h)[1500:2300]); break
show("https://www.e-stat.go.jp/stat-search/files?page={p}&toukei=00250012&tstat=000001018034&tclass1=000001060399&layout=datalist&cycle=1", 30, only="市区町村")
show("https://www.e-stat.go.jp/stat-search/files?page={p}&toukei=00250012&tstat=000001018034&tclass1=000001060399&layout=dataset&cycle=1&year=20230&month=24101212", 1)
