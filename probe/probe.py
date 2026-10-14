import urllib.request, re, html
UA = {"User-Agent": "Mozilla/5.0"}
def get(u):
    try:
        return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read().decode("utf-8", "replace")
    except Exception as e:
        print("ERR", u, e); return ""
def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()
B = "https://www.e-stat.go.jp/stat-search/files?toukei=00200521&cycle=0"
def links(t, n):
    out = {}
    for m in re.finditer(r'<a[^>]+href="([^"]*tclass%d=(\d+)[^"]*)"[^>]*>(.*?)</a>' % n, t, re.S):
        if m[2] not in out: out[m[2]] = (html.unescape(m[1]), text(m[3]))
    return out
def leaves(year, url):
    seen = set()
    for page in range(1, 40):
        t = get(url.replace("layout=normal", "layout=datalist") + f"&layout=datalist&page={page}")
        new = 0
        for m in re.finditer(r"statInfId=(\d+)&(?:amp;)?fileKind=(\d)", t):
            if m[1] in seen: continue
            seen.add(m[1]); new += 1
            before = text(t[max(0, m.start() - 1500):m.start()])[-220:].split("表番号")[-1]
            if "昼間" in before or "昼夜間" in before or "従業地・通学地" in before:
                print(year, page, m[1], m[2], "|", before[:190], flush=True)
        if new == 0: break
    print("-- leaves", year, len(seen), flush=True)

def walk(year, base, depth):
    t = get(f"{base}&tclass{depth+1}val=0") if False else get(base)
    sub = links(t, depth + 1)
    if not sub or depth >= 4:
        leaves(year, f"{base}&tclass{depth+1}val=0"); return
    for k, (u, n) in sub.items():
        print(year, "  " * depth, depth + 1, k, n[:60], flush=True)
        walk(year, f"{base}&tclass{depth+1}={k}", depth + 1)
for year, tstat, l1s in (("2015", "000001080615", ["000001101935", "000001104835", "000001104855"]),
                         ("2010", "000001039448", ["000001049567", "000001051859", "000001048107"])):
    for k in l1s:
        print(year, "L1", k, flush=True)
        walk(year, f"{B}&tstat={tstat}&tclass1={k}", 1)
