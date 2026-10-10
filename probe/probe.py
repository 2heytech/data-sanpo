import sys, io, zipfile, urllib.request, csv, re, unicodedata, json, collections
sys.path.insert(0, "pipeline")
from tdm.ingest.keishicho_crime import normalize_name
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def get(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
def rows(stats, pref):
    z = zipfile.ZipFile(io.BytesIO(get(f"https://www.e-stat.go.jp/gis/statmap-search/data?statsId={stats}&code={pref}&downloadType=2")))
    t = z.read(z.namelist()[0]).decode("cp932")
    return list(csv.reader(io.StringIO(t)))
K = {c: i for i, c in enumerate("〇一二三四五六七八九")}
def kan(t):
    if "十" in t:
        a, _, b = t.partition("十"); return str((K.get(a, 1) if a else 1) * 10 + (K.get(b, 0) if b else 0))
    return "".join(str(K[c]) for c in t)
def strong(n):
    s = normalize_name(n)
    return re.sub(r"[〇一二三四五六七八九十]+(?=(条|丁目|線|号|番|地割|区))", lambda m: kan(m.group()), s)
for pref in ("01", "13", "27"):
    gis = rows("T001081", pref)
    head = gis[0]; ci, ni, hi = head.index("KEY_CODE"), head.index("NAME"), head.index("HYOSYO")
    areas = collections.defaultdict(dict)
    hy = collections.Counter()
    for r in gis[2:]:
        hy[r[hi]] += 1
        if r[ni]:
            areas[r[ci][:5]].setdefault(r[hi], set()).add(r[ni])
    print("##", pref, "HYOSYO", dict(hy))
    sample = [(k, sorted(v.get("3", v.get("2", set())))[:8]) for k, v in list(areas.items())[:3]]
    print("  sample", sample)
    econ = rows("T001167", pref)
    for name, f in (("now", normalize_name), ("strong", strong)):
        names = collections.defaultdict(set)
        for code, hv in areas.items():
            for h, ns in hv.items():
                for n in ns: names[code].add(f(n))
        un = [r for r in econ[2:] if r[3] not in ("", "その他") and f(r[3]) not in names[r[0][:5]]]
        print("  ", name, "econ rows", len(econ) - 2, "unmatched", len(un))
        if name == "strong":
            for r in un[:40]:
                cand = [n for n in names[r[0][:5]] if f(r[3])[:2] in n][:4]
                print("     U", r[1], r[3], "|", cand)
# L02 の市区町村コード
d = get("https://nlftp.mlit.go.jp/ksj/gml/data/L02/L02-25/L02-25_27_GML.zip")
z = zipfile.ZipFile(io.BytesIO(d)); g = [n for n in z.namelist() if n.endswith(".geojson")][0]
fs = json.loads(z.read(g))["features"]
print("L02 27 codes", collections.Counter(f["properties"]["L02_020"] for f in fs).most_common(60))
