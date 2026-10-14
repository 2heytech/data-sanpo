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



for year, tstat, pairs in (("2015", "000001080615", [("000001089055","000001089056"),("000001095955","000001100295"),("000001104835","000001105295"),("000001104855","000001108965"),("000001101935","000001101936"),("000001104875","000001109275"),("000001093875","000001093876"),("000001103715","000001103716")]),
                           ("2010", "000001039448", [("000001045009","000001046265"),("000001047544","000001050184"),("000001051859","000001055398"),("000001059198","000001062444"),("000001049567","000001051128"),("000001057366","000001057367"),("000001062588","000001062589"),("000001048107","000001048108"),("000001051632","000001051633"),("000001058685","000001058686")])):
    for a, b in pairs:
        leaves(year + " " + a, f"{B}&tstat={tstat}&tclass1={a}&tclass2={b}&tclass3val=0")
