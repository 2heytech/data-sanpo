import subprocess, sys, json, os, re, urllib.request, urllib.parse
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", "pipeline"], check=True)
sys.path.insert(0, "pipeline")
from pathlib import Path
from tdm.xlsx import read_sheet
from tdm.ingest import tokyo_jhs_progress as t
os.makedirs("/tmp/shots", exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0"}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()
API = "https://catalog.data.metro.tokyo.lg.jp/api/3/action/"
for params in ({"q": "title:進路状況調査編"}, {"q": "title:公立学校統計調査報告書"}, {"q": "公立学校卒業者"},
               {"fq": "organization:t000021", "sort": "metadata_modified desc"}, {"q": "進路状況調査編 令和8年度"}):
    try:
        params = {"rows": 20, **params}
        res = json.loads(get(API + "package_search?" + urllib.parse.urlencode(params)))["result"]
        print("SEARCH", params, "count", res["count"])
        for p in res["results"]:
            print("  P", p["name"], "|", p["title"], "|", p["metadata_created"][:10], p["metadata_modified"][:10], "|",
                  (p.get("organization") or {}).get("name"), "|", [r.get("name", "")[:30] for r in p["resources"][:2]])
    except Exception as e:
        print("ERR", params, repr(e))
for y in ("r7", "r8"):
    p = Path(f"/tmp/{y}.xlsx"); p.write_bytes(get(f"https://www.kyoiku.metro.tokyo.lg.jp/documents/d/kyoiku/{y}-sotsugo-01"))
    rows = read_sheet(p)
    for i in range(0, 4):
        print("TOP", y, i, [c for c in rows[i] if c not in (None, "")][:8])
    yrs = [r[0] for r in rows if r and r[0] and re.search("年度", str(r[0]))]
    print("YEARS", y, yrs[:12])
    d = t.read_table(p)
    print("N", y, len(d))
    for k in list(d)[:3] + [k for k in d if any(s in k for s in ("文京", "港区", "千代田", "檜原", "青ヶ島"))]:
        print("V", y, k, d[k])
