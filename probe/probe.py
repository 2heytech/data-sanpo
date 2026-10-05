import re, urllib.request
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def getb(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
TAG = re.compile(r"<[^>]+>")
def text(h): return re.sub(r"\s+", " ", TAG.sub(" ", h))
def links(url, pat=r"(tstat|tclass\d|statInfId|year|month)=(\d+)", maxn=60):
    print("=== ", url)
    h = getb(url).decode("utf-8", "replace")
    seen = set(); n = 0
    for m in re.finditer(pat, h):
        key = m.group(0)
        if key in seen: continue
        seen.add(key)
        after = text(h[m.end():m.end() + 400])
        after = re.sub(r'^[^>]*>', '', after)[:80]
        print(f"  {key} :: {after}"); n += 1
        if n >= maxn: break
    return h
links("https://www.e-stat.go.jp/stat-search/files?page=1&toukei=00200241")
links("https://www.e-stat.go.jp/stat-search/files?page=1&layout=datalist&toukei=00200241&tstat=000001039591&cycle=7&tclass1val=0")
