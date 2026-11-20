import subprocess, re, json, html, io, zipfile
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
def get(u, binary=False, head=False):
    args = ["curl", "-sSL", "-A", UA, "--max-time", "120"]
    if head: args += ["-o", "/dev/null", "-w", "%{http_code} %{size_download} %{content_type}"]
    r = subprocess.run(args + [u], capture_output=True)
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")
def text(h):
    h = re.sub(r"(?s)<(script|style).*?</\1>", "", h)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h)))
print("#### 1 tokyo ckan")
for pid in ["t000021d2000000192", "t000054d0000000374", "t000021d2000000176"]:
    j = json.loads(get(f"https://catalog.data.metro.tokyo.lg.jp/api/3/action/package_show?id={pid}") or "{}")
    res = j.get("result", {}).get("resources", [])
    print(pid, j.get("result", {}).get("title"), j.get("result", {}).get("metadata_modified"))
    for r in res[:60]:
        print("   ", (r.get("name") or "")[:70], "|", (r.get("url") or "")[:110], "|", r.get("last_modified") or r.get("created"))
for q in ["衆議院議員選挙 令和8年", "衆議院議員総選挙 投票結果 令和8年2月8日"]:
    j = json.loads(get("https://catalog.data.metro.tokyo.lg.jp/api/3/action/package_search?rows=10&q=" + subprocess.run(["python3","-c","import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))",q],capture_output=True,text=True).stdout.strip()) or "{}")
    for p in j.get("result", {}).get("results", []):
        print("  S", p.get("name"), p.get("title"), p.get("metadata_modified"))
        for r in p.get("resources", [])[:8]:
            print("      ", (r.get("name") or "")[:60], "|", (r.get("url") or "")[:110])
print("#### 2 L02-26")
print(get("https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L02-2026.html", head=True))
t = text(get("https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L02-2026.html"))
for m in re.finditer(r"L02-26[^ ]*zip", t): print("   ", m.group(0)); break
i = t.find("更新履歴"); print("   ", t[i:i+300])
print(get("https://nlftp.mlit.go.jp/ksj/gml/data/L02/L02-26/L02-26_13_GML.zip", head=True))
print("#### 3 ports")
t = text(get("https://www.e-stat.go.jp/stat-search/files?tstat=000001018967&toukei=00600280"))
for k in ["2025年", "令和7年", "2024年"]:
    for m in list(re.finditer(k, t))[:4]: print("   ", k, "|", t[max(0,m.start()-80):m.start()+80])
print("#### 4 census2025 tables")
for page in range(1, 6):
    h = get(f"https://www.e-stat.go.jp/stat-search/files?page={page}&layout=datalist&toukei=00200521&tstat=000001230925&cycle=0&tclass1=000001230926&tclass2=000001232187&tclass3val=0")
    t = text(h)
    for m in re.finditer(r"(表\s?\d+-\d+[^。]{0,90}?)(?=\s(?:EXCEL|CSV|DB|PDF))", t):
        s = m.group(1)
        if re.search(r"住宅|住居|所有|建て方|延べ面積|世帯の種類", s): print("   p", page, s[:140])
print("#### 5 zairyu 2026")
t = text(get("https://www.e-stat.go.jp/stat-search/files?page=1&toukei=00250012&tstat=000001018034&tclass1=000001060399&layout=dataset&cycle=1&year=20260"))
for k in ["2026年", "26-06", "令和8年"]:
    for m in list(re.finditer(k, t))[:4]: print("   ", k, "|", t[max(0,m.start()-80):m.start()+100])
print("#### 6 water dashboard")
h = get("https://www.digital.go.jp/resources/govdashboard/watersupply")
links = sorted(set(re.findall(r'href="([^"]+\.zip)"', h)))
for l in links: print("   ", l)
for l in links:
    if "table_02" in l:
        u = l if l.startswith("http") else "https://www.digital.go.jp" + l
        b = get(u, binary=True)
        try: print("   files", zipfile.ZipFile(io.BytesIO(b)).namelist())
        except Exception as e: print("   zip err", e, len(b))
print("#### 7 parks R07")
print(get("https://www.mlit.go.jp/toshi/park/content/05_R07.xlsx", head=True))
