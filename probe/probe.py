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
for year, tstat in (("2015", "000001080615"), ("2010", "000001039448")):
    top = get(f"{B}&tstat={tstat}")
    l1 = links(top, 1)
    for k, (u, name) in l1.items():
        print(year, "L1", k, name, flush=True)
    for k, (u, name) in l1.items():
        if "従業" not in name: continue
        t = get(f"{B}&tstat={tstat}&tclass1={k}")
        l2 = links(t, 2)
        for k2, (u2, n2) in l2.items():
            print(year, " L2", k2, n2, flush=True)
        for k2, (u2, n2) in l2.items():
            if "全国" not in n2 and "都道府県" not in n2: continue
            t3 = get(f"{B}&tstat={tstat}&tclass1={k}&tclass2={k2}")
            l3 = links(t3, 3)
            for k3, (u3, n3) in l3.items():
                print(year, "  L3", k3, n3, flush=True)
            if l3:
                for k3, (u3, n3) in l3.items():
                    if "全国" in n3:
                        leaves(year, f"{B}&tstat={tstat}&tclass1={k}&tclass2={k2}&tclass3={k3}&tclass4val=0")
            else:
                leaves(year, f"{B}&tstat={tstat}&tclass1={k}&tclass2={k2}&tclass3val=0")
