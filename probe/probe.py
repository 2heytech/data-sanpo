import subprocess, sys, json, os, re, urllib.request, hashlib
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
API = "https://catalog.data.metro.tokyo.lg.jp/api/3/action/"
for pid in ("t000021d2000000177", "t000021d2000000187", "t000021d2000000192"):
    d = json.loads(get(API + "package_show?id=" + pid)[0])["result"]
    print("PKG", pid, d.get("license_id"), d.get("license_title"), d.get("license_url"), "|", d["title"], "|", (d.get("notes") or "")[:200].replace("\n", " "))
    for r in d["resources"][:3]:
        print("  RES", r.get("name"), "|", r.get("description", "")[:80].replace("\n", " "), "|", r.get("url"), "|", r.get("format"), r.get("last_modified") or r.get("created"))
    u = d["resources"][0]["url"]
    b, h = get(u)
    p = Path(f"/tmp/{pid}.xlsx"); p.write_bytes(b)
    print("  FILE", len(b), h.get("Content-Type"), hashlib.sha256(b).hexdigest()[:16])
    rows = read_sheet(p)
    print("  TOP", [str(c)[:20] for r in rows[:3] for c in r if c not in (None, "")][:6])
    print("  YEARS", [r[0] for r in rows if r and r[0] and re.search("年度", str(r[0]))][:6])
    dd = t.read_table(p)
    print("  N", len(dd))
    for k in [k for k in dd if any(s in k for s in ("千代田", "文京", "檜原", "青ヶ島", "立川"))]:
        print("  V", k, dd[k])
# 今使っている r7-sotsugo-01（ハイフン）とカタログの r7_sotsugo_01（下線）が同じものか
a, _ = get("https://www.kyoiku.metro.tokyo.lg.jp/documents/d/kyoiku/r7-sotsugo-01")
b, _ = get("https://www.kyoiku.metro.tokyo.lg.jp/documents/d/kyoiku/r7_sotsugo_01")
print("SAME_R7", hashlib.sha256(a).hexdigest()[:16], hashlib.sha256(b).hexdigest()[:16], len(a), len(b))
pa, pb = Path("/tmp/a.xlsx"), Path("/tmp/b.xlsx"); pa.write_bytes(a); pb.write_bytes(b)
print("SAME_R7_VALUES", t.read_table(pa) == t.read_table(pb))
