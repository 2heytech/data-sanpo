import urllib.request, re, html
UA = {"User-Agent": "Mozilla/5.0"}
def get(u):
    try:
        return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read().decode("utf-8", "replace")
    except Exception as e:
        print("ERR", u, e); return ""
def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()
B = "https://www.e-stat.go.jp/stat-search/files?toukei=00200521&layout=datalist&tclass3val=0"
for year, tstat in (("2025", "000001230925"), ("2020", "000001136464"), ("2015", "000001080615"), ("2010", "000001039448")):
    top = get(f"https://www.e-stat.go.jp/stat-search/files?toukei=00200521&tstat={tstat}")
    cls = {}
    for m in re.finditer(r'tclass1=(\d+)[^>]*>(.*?)</a>', top, re.S):
        cls.setdefault(m[1], text(m[2]))
    print("==", year, tstat, cls, flush=True)
    for c1, name in cls.items():
        if year != "2025" and "人口等基本集計" not in name:
            continue
        seen = set()
        for page in range(1, 60):
            t = get(f"{B}&tstat={tstat}&tclass1={c1}&page={page}")
            new = 0
            for m in re.finditer(r"statInfId=(\d+)&(?:amp;)?fileKind=(\d)", t):
                sid = m[1]
                if sid in seen: continue
                seen.add(sid); new += 1
                before = text(t[max(0, m.start() - 1500):m.start()])[-200:]
                after = text(t[m.end():m.end() + 1500])[:200]
                if re.search("外国|国籍", before + after):
                    print(year, c1, page, sid, m[2], "| B:", before[-170:], "| A:", after[:170], flush=True)
            if new == 0:
                break
        print("--", year, name, "files", len(seen), flush=True)
