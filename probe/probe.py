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
def crawl(year, params, depth, label):
    q = "".join(f"&{k}={v}" for k, v in params)
    t = get(f"{B}{q}&tclass{depth}val=0&page=1")
    if "statInfId=" in t:
        seen = set()
        for page in range(1, 30):
            if page > 1:
                t = get(f"{B}{q}&tclass{depth}val=0&page={page}")
            new = 0
            for m in re.finditer(r"statInfId=(\d+)&(?:amp;)?fileKind=(\d)", t):
                sid = m[1]
                if sid in seen: continue
                seen.add(sid); new += 1
                before = text(t[max(0, m.start() - 1500):m.start()])[-150:]
                after = text(t[m.end():m.end() + 1500])[:150]
                if re.search("外国|国籍", before + after):
                    print(year, label, page, sid, m[2], "| B:", before, "| A:", after, flush=True)
            if new == 0: break
        print("--", year, label, "files", len(seen), flush=True)
        return
    subs = {}
    for m in re.finditer(rf'tclass{depth}=(\d+)[^>]*>(.*?)</a>', t, re.S):
        subs.setdefault(m[1], text(m[2]))
    print("sub", year, label, depth, subs, len(t), t.count("statInfId"), t.count("tclass"), flush=True)
    for c, name in subs.items():
        if depth >= 2 and re.search(r"^\s*\d\d[：:]|北海道|青森|岩手|宮城|秋田|山形|福島", name) and "13" not in name[:3]:
            continue  # 都道府県別は東京都だけ見る
        crawl(year, params + [(f"tclass{depth}", c)], depth + 1, label + " > " + name[:30])
for year, tstat, c1 in (("2025", "000001230925", "000001230926"), ("2020", "000001136464", "000001136466"),
                        ("2015", "000001080615", "000001089055"), ("2010", "000001039448", "000001045009")):
    crawl(year, [("tstat", tstat), ("tclass1", c1)], 2, "")
