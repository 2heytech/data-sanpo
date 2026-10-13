import urllib.request, sys, csv, io, re
sys.path.insert(0, "pipeline")
from tdm.xlsx import read_sheet
UA = {"User-Agent": "Mozilla/5.0"}
def get(u):
    try:
        return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120).read()
    except Exception as e:
        print("ERR", u, e); return b""
for year, sid in (("2025", "000040506619"), ("2020", "000032142708"), ("2015", "000031473275"), ("2010", "000012460729")):
    for kind in ("0", "1"):
        b = get(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind={kind}")
        print("==", year, sid, kind, len(b), b[:8], flush=True)
        if not b: continue
        if b[:2] == b"PK":
            open("/tmp/x.xlsx", "wb").write(b)
            rows = [[("" if c is None else str(c)) for c in r] for r in read_sheet("/tmp/x.xlsx")]
        elif b[:4] == b"\xd0\xcf\x11\xe0":
            print("xls (old)"); continue
        else:
            t = b.decode("cp932", "replace")
            rows = list(csv.reader(io.StringIO(t)))
        print("rows", len(rows), "maxcols", max(len(r) for r in rows))
        for i, r in enumerate(rows[:16]):
            print(i, [c[:22] for c in r[:40]])
        n = 0
        for r in rows:
            j = " ".join(r[:12])
            if re.search(r"13101|千代田区|20304|川上村|13000|東京都", j) and n < 14:
                print("R", [c[:22] for c in r[:40]]); n += 1
        print("LAST", [c[:22] for c in rows[-1][:20]])
