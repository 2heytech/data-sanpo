import subprocess, sys, json, os, re, urllib.request, hashlib, csv, io
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", "pipeline"], check=True)
sys.path.insert(0, "pipeline")
from pathlib import Path
from tdm.xlsx import read_sheet
from tdm.ingest import tokyo_jhs_progress as t
os.makedirs("/tmp/shots", exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0"}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read(), r.headers
def show_xlsx(tag, b):
    p = Path(f"/tmp/{hashlib.md5(tag.encode()).hexdigest()}.xlsx"); p.write_bytes(b)
    rows = read_sheet(p)
    print("  YEARS", tag, [r[0] for r in rows if r and r[0] and re.search("年度", str(r[0]))][:3])
    dd = t.read_table(p)
    print("  N", tag, len(dd), {k: dd[k] for k in dd if any(s in k for s in ("千代田", "文京"))})
    return dd
API = "https://catalog.data.metro.tokyo.lg.jp/api/3/action/"
cat = {}
for pid in ("t000021d2000000177", "t000021d2000000187", "t000021d2000000192"):
    d = json.loads(get(API + "package_show?id=" + pid)[0])["result"]
    print("PKG", pid, d.get("license_id"), d["metadata_created"][:10])
    r = d["resources"][0]
    print("  RES0", r.get("name"), "|", r.get("description", "")[:40], "|", r.get("url"), "|", r.get("format"))
    b, h = get(r["url"])
    print("  FILE", len(b), h.get("Content-Type"), b[:4])
    if b[:2] == b"PK":
        cat[pid] = show_xlsx(pid, b)
    else:
        for enc in ("utf-8-sig", "cp932"):
            try:
                txt = b.decode(enc); break
            except UnicodeDecodeError:
                pass
        rows = list(csv.reader(io.StringIO(txt)))
        print("  CSV", enc, len(rows))
        for row in rows[:9]:
            print("   C", [c.strip()[:12] for c in row][:14])
        for row in rows:
            if row and any(s in row[0] for s in ("千代田", "文京", "令和")):
                print("   R", [c.strip()[:12] for c in row][:26])
for u in ("sotsugo-01_3", "sotsugo-01_4", "statistics_and_research_report2024_sotsugo-01_r61119", "r7-sotsugo-01", "r7_sotsugo_01", "r6-sotsugo-01", "r6_sotsugo_01", "sotsugo_01_4"):
    try:
        b, h = get("https://www.kyoiku.metro.tokyo.lg.jp/documents/d/kyoiku/" + u)
        print("SITE", u, len(b), h.get("Content-Type"), h.get("Last-Modified"), hashlib.sha256(b).hexdigest()[:12])
        if b[:2] == b"PK":
            show_xlsx(u, b)
    except Exception as e:
        print("SITE", u, repr(e))
