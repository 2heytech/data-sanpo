import sys, re, urllib.request, urllib.parse, io, zipfile, csv
sys.path.insert(0, "pipeline")
from tdm import xlsx
from pathlib import Path
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def getb(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
TAG = re.compile(r"<[^>]+>")
def text(h): return re.sub(r"\s+", " ", TAG.sub(" ", h))
def listing(url, n=4):
    print("==== LIST", url)
    for page in range(1, n + 1):
        h = getb(url.replace("page=1", f"page={page}")).decode("utf-8", "replace")
        prev = 0
        found = 0
        for m in re.finditer(r"(statInfId|stat_infid|tclass\d)=(\d+)", h):
            t = text(h[prev:m.start()])[-140:]
            prev = m.end()
            print(f"  {m.group(1)}={m.group(2)} :: {t}")
            found += 1
        if not found:
            print("  (none)", text(h)[:600]); break
q = urllib.parse.quote("市区町村別 国籍・地域別 在留外国人")
try: listing(f"https://www.e-stat.go.jp/stat-search/files?page=1&layout=datalist&toukei=00250012&query={q}", 3)
except Exception as e: print("ERR", e)
try: listing("https://www.e-stat.go.jp/stat-search/files?page=1&layout=datalist&toukei=00250012&tstat=000001018034&cycle=1&tclass1val=0", 1)
except Exception as e: print("ERR", e)
for sid in ["000031669242", "000040186957"]:
    for kind in ("0", "1"):
        try:
            d = getb(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind={kind}")
        except Exception as e:
            print("ERR", sid, kind, e); continue
        print("######", sid, kind, len(d), d[:8])
        if d[:2] == b"PK" and b"xl/" in d[:2000]:
            p = Path(f"{sid}.xlsx"); p.write_bytes(d)
            for sn in xlsx.sheet_names(p):
                rows = xlsx.read_sheet(p, sn)
                print("### sheet", sn, len(rows))
                for i, r in enumerate(rows[:14]): print(i, [str(c)[:14] for c in r][:24])
                for r in rows:
                    if any(str(c).startswith(("千代田", "13101", "札幌市中央")) for c in r[:4]): print("  HIT", [str(c)[:12] for c in r][:24])
        else:
            for enc in ("cp932", "utf-8-sig"):
                try: s = d.decode(enc); break
                except Exception: s = None
            if s:
                lines = s.splitlines()
                print("lines", len(lines))
                for l in lines[:12]: print("  ", l[:300])
                for l in lines:
                    if "千代田" in l or "13101" in l: print("  HIT", l[:300]); break
