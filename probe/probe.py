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
            if True:
                print(year, page, m[1], m[2], "|", before[:190], flush=True)
        if new == 0: break
    print("-- leaves", year, len(seen), flush=True)



t = get(f"{B}&tstat=000001039448&tclass1=000001049567")
for k, (u, n) in links(t, 2).items():
    print("2010 L2", k, n[:50], flush=True)
    if "北海道" in n or "東京" in n:
        sub = links(get(f"{B}&tstat=000001039448&tclass1=000001049567&tclass2={k}"), 3)
        for k3, (u3, n3) in sub.items(): print("   L3", k3, n3[:60], flush=True)
        if not sub:
            leaves("2010 " + n[:6], f"{B}&tstat=000001039448&tclass1=000001049567&tclass2={k}&tclass3val=0")
