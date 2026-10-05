import re, urllib.request
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def getb(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
TAG = re.compile(r"<[^>]+>")
def text(h): return re.sub(r"\s+", " ", TAG.sub(" ", h))
for y in range(2012, 2026):
    for mon in ("24101212",):
        url = f"https://www.e-stat.go.jp/stat-search/files?page=1&toukei=00250012&tstat=000001018034&tclass1=000001060399&layout=dataset&cycle=1&year={y}0&month={mon}"
        try: h = getb(url).decode("utf-8", "replace")
        except Exception as e: print(y, "ERR", e); continue
        prev = 0; seen = set(); n = 0
        for m in re.finditer(r"statInfId=(\d+)(?:&amp;|&)fileKind=(\d)", h):
            seg = text(h[prev:m.start()]); prev = m.end()
            if m.group(1) in seen: continue
            seen.add(m.group(1)); n += 1
            title = re.split(r" 在留外国人統計（旧登録外国人統計） 在留外国人統計（旧登録外国人統計） /", seg)[0][-90:]
            if "市区町村" in title:
                print(y, m.group(1), "k" + m.group(2), "::", title.strip())
        print(y, "items", n)
