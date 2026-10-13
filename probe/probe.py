import urllib.request, re, io, html, sys
sys.path.insert(0, "pipeline")
UA = {"User-Agent": "Mozilla/5.0"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read()
found = {}
for y in range(2021, 2027):
    for page in (1, 2):
        u = f"https://www.e-stat.go.jp/stat-search/files?page={page}&toukei=00200241&tstat=000001039591&layout=dataset&cycle=7&year={y}0"
        t = get(u).decode("utf-8", "replace")
        print("page", y, page, len(t), t.count("statInfId="), flush=True)
        seen = set()
        for m in re.finditer(r"statInfId=(\d+)&(?:amp;)?fileKind=(\d)", t):
            sid, kind = m.groups()
            if sid in seen: continue
            seen.add(sid)
            text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t[max(0, m.start() - 2500):m.start()])))
            tail = text[-220:]
            if "市区町村別" in tail[-160:]:
                print(y, sid, kind, tail[-160:], flush=True)
                if "総計" in tail[-160:] and "年齢" not in tail[-160:]:
                    found.setdefault(y, [(sid, kind)])
print(found)
from tdm.xlsx import read_sheet
for y, ids in found.items():
    sid = next((i for i, k in ids if k == "0"), ids[0][0])
    b = get(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind=0")
    print("==", y, sid, len(b), b[:4])
    if b[:2] != b"PK":
        continue
    open("/tmp/x.xlsx", "wb").write(b)
    rows = read_sheet("/tmp/x.xlsx", 0)
    for r in rows[:9]:
        print([c for c in r[:14]])
    print("rows", len(rows))
    for r in rows:
        if r and str(r[0]).strip() in ("131016", "141003", "141011", "130001", "011002"):
            print(r[:8])
