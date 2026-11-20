import subprocess, sys, io, json, re, zipfile, urllib.request, os
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", "pipeline"], check=True)
sys.path.insert(0, "pipeline")
from pathlib import Path
UA = {"User-Agent": "Mozilla/5.0"}
def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read(), r.headers
os.makedirs("/tmp/shots", exist_ok=True)
# 1) L02-26
for yy in ("25", "26"):
    try:
        b, h = get(f"https://nlftp.mlit.go.jp/ksj/gml/data/L02/L02-{yy}/L02-{yy}_13_GML.zip")
        z = zipfile.ZipFile(io.BytesIO(b))
        print("ZIP", yy, len(b), [n for n in z.namelist()][:20])
        gj = [n for n in z.namelist() if n.endswith(".geojson")]
        d = json.loads(z.read(gj[0]))
        f0 = d["features"][0]["properties"]
        print("NFEAT", yy, len(d["features"]), "NKEYS", len(f0))
        print("PROPS", yy, json.dumps(f0, ensure_ascii=False))
        # 千代田区の住宅地1つ
        for f in d["features"]:
            p = f["properties"]
            if str(p.get("L02_020")) == "13101" or str(p.get("L02_021", "")).startswith("千代田"):
                print("CHIYODA", yy, json.dumps(p, ensure_ascii=False)); break
    except Exception as e:
        print("ERR L02", yy, repr(e))
# 2) census xlsx
from tdm.xlsx import read_sheet
from tdm.ingest.estat_census_municipal import _cell_text, HEAD
for sid in ("000040506521", "000040506530"):
    try:
        b, h = get(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind=0")
        print("FILE", sid, len(b), h.get("Content-Disposition"))
        p = Path(f"/tmp/{sid}.xlsx"); p.write_bytes(b)
        rows = read_sheet(p)
        hi = next(i for i, r in enumerate(rows[:60]) if any(c == HEAD for c in r))
        for i in range(hi + 1):
            cells = [_cell_text(c) for c in rows[i]]
            print("ROW", sid, i, " | ".join(cells))
        head = [_cell_text(c) for c in rows[hi]]
        lvl = head.index(HEAD)
        # 分類の列の値
        for j, c in enumerate(head[:lvl + 8]):
            vals = []
            for r in rows[hi + 1:]:
                v = _cell_text(r[j]) if j < len(r) else ""
                if v not in vals: vals.append(v)
                if len(vals) > 40: break
            print("COL", sid, j, c, vals[:40])
        n = 0
        for r in rows[hi + 1:]:
            cells = [_cell_text(c) for c in r]
            if any("13101" in c or "千代田区" in c for c in cells) or (n < 3):
                print("DATA", sid, " | ".join(cells)); n += 1
            if n > 25: break
        print("NROWS", sid, len(rows))
    except Exception as e:
        import traceback; traceback.print_exc()
