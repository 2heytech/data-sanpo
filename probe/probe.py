import sys, re, urllib.request, collections
from pathlib import Path
sys.path.insert(0, "pipeline")
from tdm import xlsx
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def getb(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
TAG = re.compile(r"<[^>]+>")
def text(h): return re.sub(r"\s+", " ", TAG.sub(" ", h))
def links(url, pat=r"(tclass\d|statInfId|stat_infid)=(\d+)", maxn=80):
    print("==== ", url)
    h = getb(url).decode("utf-8", "replace")
    prev = 0; n = 0
    for m in re.finditer(pat, h):
        after = text(h[m.end():m.end() + 300])[:90]
        print(f"  {m.group(1)}={m.group(2)} :: {after}")
        n += 1
        if n >= maxn: break
    if not n: print("  none", text(h)[:400])
    return h
h = links("https://www.e-stat.go.jp/stat-search/files?stat_infid=000040186957", maxn=40)
for m in re.findall(r'href="([^"]*tclass[^"]*)"', h)[:20]: print("  HREF", m.replace("&amp;", "&"))
links("https://www.e-stat.go.jp/stat-search/files?page=1&layout=datalist&toukei=00250012&tstat=000001018034&cycle=1&tclass1val=0")
links("https://www.e-stat.go.jp/stat-search/files?page=1&layout=datalist&toukei=00250012&tstat=000001018034&tclass1val=0")
d = getb("https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040186957&fileKind=0")
p = Path("t2.xlsx"); p.write_bytes(d)
for sn in xlsx.sheet_names(p):
    rows = xlsx.read_sheet(p, sn)
    print("### sheet", sn, len(rows))
    for i, r in enumerate(rows[:10]): print(i, [str(c)[:20] for c in r][:12])
    body = [r for r in rows if r and re.fullmatch(r"\d{5}", str(r[0]))]
    print("body", len(body), "munis", len({r[0] for r in body}))
    print("nat", collections.Counter(r[3] for r in body).most_common(12))
    print("odd first col", collections.Counter(str(r[0])[:12] for r in rows if r and not re.fullmatch(r"\d{5}", str(r[0]))).most_common(8))
    tot = collections.Counter()
    for r in body:
        if r[0] == "13101": tot[r[3]] += float(r[5])
    print("chiyoda", sum(tot.values()), tot.most_common(8))
    print("vals nonnum", collections.Counter(str(r[5]) for r in body if not isinstance(r[5], float)).most_common(5))
    print("wards", sorted({(r[0], r[2]) for r in body if r[0][:2] in ("01", "14") and r[0][2] == "1"})[:12])
