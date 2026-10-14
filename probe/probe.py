import urllib.request, re, html
UA = {"User-Agent": "Mozilla/5.0"}
def get(u):
    try:
        return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read().decode("utf-8", "replace")
    except Exception as e:
        print("ERR", u, e); return ""
def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()
B = "https://www.e-stat.go.jp/stat-search/files?toukei=00200521&layout=datalist&cycle=0"
def crawl(year, q):
    seen = set()
    for page in range(1, 40):
        t = get(f"{B}&{q}&page={page}")
        new = 0
        for m in re.finditer(r"statInfId=(\d+)&(?:amp;)?fileKind=(\d)", t):
            sid = m[1]
            if sid in seen: continue
            seen.add(sid); new += 1
            before = text(t[max(0, m.start() - 1500):m.start()])[-200:].split("表番号")[-1]
            if "昼間人口" in before or "昼夜間" in before:
                print(year, q[-40:], page, sid, m[2], "|", before[:170], flush=True)
        if new == 0: break
    print("--", year, q, len(seen), flush=True)
crawl("2020", "tstat=000001136464&tclass1=000001136469&tclass2val=0")
for c in ("000001089055", "000001095955", "000001104835", "000001104855", "000001101935", "000001104875", "000001093875", "000001103715"):
    top = get(f"{B}&tstat=000001080615&tclass1={c}&tclass2val=0")
    subs = dict(re.findall(r'tclass2=(\d+)[^>]*>(.*?)</a>', top, re.S))
    sub = next((k for k, v in subs.items() if "全国" in text(v)), None)
    if sub: crawl("2015", f"tstat=000001080615&tclass1={c}&tclass2={sub}&tclass3val=0")
    else: crawl("2015", f"tstat=000001080615&tclass1={c}&tclass2val=0")
for c in ("000001045009", "000001047544", "000001051859", "000001059198", "000001049567", "000001057366", "000001062588", "000001048107", "000001051632", "000001058685"):
    top = get(f"{B}&tstat=000001039448&tclass1={c}&tclass2val=0")
    subs = dict(re.findall(r'tclass2=(\d+)[^>]*>(.*?)</a>', top, re.S))
    sub = next((k for k, v in subs.items() if "全国" in text(v)), None)
    if sub: crawl("2010", f"tstat=000001039448&tclass1={c}&tclass2={sub}&tclass3val=0")
    else: crawl("2010", f"tstat=000001039448&tclass1={c}&tclass2val=0")
