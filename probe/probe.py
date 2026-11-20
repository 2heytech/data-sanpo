import json, os, re, urllib.request, urllib.parse
os.makedirs("/tmp/shots", exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0"}
def get(url, method="GET"):
    req = urllib.request.Request(url, headers=UA, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.headers, (r.read() if method == "GET" else b"")
API = "https://catalog.data.metro.tokyo.lg.jp/api/3/action/"
try:
    _, _, b = get(API + "package_show?id=t000021d2000000192")
    d = json.loads(b)["result"]
    print("PKG", d.get("title"), d.get("metadata_modified"))
    for r in d["resources"]:
        print("RES", r.get("name"), "|", r.get("url"), "|", r.get("last_modified") or r.get("created"))
except Exception as e:
    print("ERR pkg", repr(e))
for q in ("進路状況", "卒業者の進路", "公立学校統計調査 進路"):
    try:
        _, _, b = get(API + "package_search?" + urllib.parse.urlencode({"q": q, "rows": 30, "sort": "metadata_modified desc"}))
        for p in json.loads(b)["result"]["results"]:
            print("SEARCH", q, "|", p["name"], "|", p["title"], "|", p["metadata_modified"], "|", len(p["resources"]))
    except Exception as e:
        print("ERR search", q, repr(e))
for y in ("r7", "r8"):
    for n in ("01", "02", "1"):
        u = f"https://www.kyoiku.metro.tokyo.lg.jp/documents/d/kyoiku/{y}-sotsugo-{n}"
        try:
            s, h, _ = get(u, "HEAD")
            print("HEAD", u, s, h.get("Content-Type"), h.get("Content-Length"), h.get("Last-Modified"))
        except Exception as e:
            print("HEAD", u, repr(e))
# 都教委の統計のページ
for u in ("https://www.kyoiku.metro.tokyo.lg.jp/administration/statistics_and_research/school_statistics/",
          "https://www.kyoiku.metro.tokyo.lg.jp/administration/statistics_and_research/statistics/",
          "https://www.kyoiku.metro.tokyo.lg.jp/administration/statistics/"):
    try:
        s, h, b = get(u)
        t = b.decode("utf-8", "replace")
        print("PAGE", u, s, len(t))
        for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', t, re.S):
            txt = re.sub(r"<[^>]+>", "", m[2]).strip()
            if re.search("進路|卒業|令和8|令和７|令和8|R8|統計調査", txt):
                print("  L", txt[:80], "|", m[1])
    except Exception as e:
        print("PAGE", u, repr(e))
