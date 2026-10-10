import sys, io, zipfile, urllib.request
from pathlib import Path
sys.path.insert(0, "pipeline")
from tdm import xlsx
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def get(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
def s(r, n=24): return [str(c)[:18] for c in r][:n]
# 経済センサス 小地域 T001167 東京都・北海道
for code in ("13", "01"):
    try:
        d = get(f"https://www.e-stat.go.jp/gis/statmap-search/data?statsId=T001167&code={code}&downloadType=2")
        print("## T001167", code, len(d), d[:4])
        z = zipfile.ZipFile(io.BytesIO(d))
        for n in z.namelist():
            t = z.read(n).decode("cp932", "replace").splitlines()
            print("  file", n, len(t))
            for l in t[:12]: print("   ", l[:400])
            import collections
            print("   HTK", collections.Counter(l.split(",")[4] if len(l.split(","))>4 else "" for l in t[2:]))
            print("   X rows", sum(1 for l in t if ",X" in l), "lens", collections.Counter(len(l.split(",")[0]) for l in t[2:]))
            for l in t[2:]:
                if l.startswith("13101") or l.startswith("01101"):
                    print("   C", l[:300])
                    break
            print("   LAST", t[-1][:300])
    except Exception as e: print("ERR T001167", code, e)
# 国勢調査 時系列 表6（東京都）と表1
for sid in ("000001085987", "000001085925"):
    try:
        d = get(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind=0")
        ext = "xlsx" if d[:2] == b"PK" else "xls"
        print("##", sid, ext, len(d))
        if ext != "xlsx":
            import subprocess; Path(f"{sid}.xls").write_bytes(d)
            try:
                import xlrd
            except ImportError:
                subprocess.run([sys.executable, "-m", "pip", "install", "-q", "xlrd"])
                import xlrd
            b = xlrd.open_workbook(f"{sid}.xls")
            for sh in b.sheets()[:3]:
                print("  --", sh.name, sh.nrows, sh.ncols)
                for i in range(min(sh.nrows, 22)): print("   ", s(sh.row_values(i)))
                for i in range(sh.nrows):
                    r = sh.row_values(i)
                    if any(str(c).strip() in ("13101", "千代田区", "13362", "利島村") for c in r[:8]):
                        print("   HIT", i, s(r, 30))
                print("   LAST", [s(sh.row_values(i), 30) for i in range(max(0, sh.nrows - 6), sh.nrows)])
            continue
        p = Path(f"{sid}.xlsx"); p.write_bytes(d)
        for n in xlsx.sheet_names(p)[:3]:
            rows = xlsx.read_sheet(p, n); print("  --", n, len(rows))
            for r in rows[:22]: print("   ", s(r))
            for i, r in enumerate(rows):
                if any(str(c).strip() in ("13101", "千代田区", "13362", "利島村", "13000", "東京都") for c in r[:8] if c is not None):
                    print("   HIT", i, s(r, 30))
            for r in rows[-8:]: print("   LAST", s(r, 30))
    except Exception as e: print("ERR", sid, e)
