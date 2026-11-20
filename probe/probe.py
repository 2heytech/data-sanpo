import subprocess, sys, io, json, zipfile, urllib.request, os
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", "pipeline"], check=True)
from pathlib import Path
from tdm.config import load_sources
from tdm.ingest import mlit_landprice
from tdm.ingest.estat_census_municipal import read_table
os.makedirs("/tmp/shots", exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0"}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
        return r.read()
cfg = load_sources()
for key in ("mlit_l02_2026", "mlit_l01_2026"):
    c = cfg[key]; tot = bad = 0; worst = (0, "")
    years = set()
    for i in range(1, 48):
        pref = f"{i:02d}"
        try:
            z = zipfile.ZipFile(io.BytesIO(get(c["download_url"].format(pref=pref))))
            name = next(n for n in z.namelist() if n.endswith(".geojson"))
            feats = json.loads(z.read(name))["features"]
            m = sum(1 for f in feats if not mlit_landprice._price_matches(f["properties"]))
            years |= {f["properties"][mlit_landprice._fields(f["properties"])["year"]] for f in feats}
            tot += len(feats); bad += m
            if feats and m / len(feats) > worst[0]: worst = (m / len(feats), pref)
            if m:
                ex = next(f["properties"] for f in feats if not mlit_landprice._price_matches(f["properties"]))
                fl = mlit_landprice._fields(ex)
                print("MISMATCH", key, pref, m, len(feats), ex.get(fl["price"]), mlit_landprice.price_history(ex), mlit_landprice.point_name(ex))
            if pref == "13":
                p0 = feats[0]["properties"]; fl = mlit_landprice._fields(p0)
                print("SAMPLE", key, mlit_landprice.point_name(p0), {k: p0.get(fl[k]) for k in ("station", "distance", "zoning", "current_use", "address", "area", "change")})
        except Exception as e:
            print("ERR", key, pref, repr(e))
    print("TOTAL", key, tot, "mismatch", bad, "worst", worst, "years", sorted(years))
for key in ("census2025_municipal_tenure", "census2025_municipal_building_type"):
    c = cfg[key]
    p = Path(f"/tmp/{c['files'][0]}"); p.write_bytes(get(c["download_url"]))
    t = read_table(p, c["columns"], c.get("filters"))
    rows = {r["KEY_CODE"]: r for r in t.rows}
    print("TABLE", key, len(rows), "munis", sum(len(k) == 5 for k in rows), "prefs", sum(len(k) == 2 for k in rows))
    for k in ("13101", "13", "01", "14341", "47382", "13421", "01101"):
        print("ROW", key, k, {n: v for n, v in rows.get(k, {}).items() if n not in ("HTKSYORI", "HTKSAKI", "GASSAN")})
    odd = [(k, n, v) for k, r in rows.items() for n, v in r.items() if n not in ("KEY_CODE", "HTKSYORI", "HTKSAKI", "GASSAN") and not v.isdigit()]
    print("NONDIGIT", key, len(odd), odd[:15])
