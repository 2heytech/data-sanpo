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
for year, q in (("2025", "tstat=000001230925&tclass1=000001230926&tclass2=000001232187&tclass3val=0"),
                ("2015", "tstat=000001080615&tclass1=000001089055&tclass2=000001089056&tclass3val=0"),
                ("2010", "tstat=000001039448&tclass1=000001045009&tclass2=000001046265&tclass3val=0")):
    seen = set()
    for page in range(1, 30):
        t = get(f"{B}&{q}&page={page}")
        new = 0
        for m in re.finditer(r"statInfId=(\d+)&(?:amp;)?fileKind=(\d)", t):
            sid = m[1]
            if sid in seen: continue
            seen.add(sid); new += 1
            before = text(t[max(0, m.start() - 1500):m.start()])[-170:]
            before = before.split("表番号")[-1]
            if re.search("外国|国籍", before):
                print(year, page, sid, m[2], "|", before[:150], flush=True)
        if new == 0: break
    print("--", year, "files", len(seen), flush=True)
