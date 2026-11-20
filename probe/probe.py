import subprocess, re, html
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
def get(u, head=False):
    args = ["curl", "-sSL", "-A", UA, "--max-time", "120"]
    if head: args += ["-o", "/dev/null", "-w", "%{http_code} %{size_download} %{content_type}"]
    return subprocess.run(args + [u], capture_output=True).stdout.decode("utf-8", "replace")
def text(h):
    h = re.sub(r"(?s)<(script|style).*?</\1>", "", h)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h)))
print("#### census2025 titles")
seen = set()
for tc2 in ["000001232187", ""]:
    for page in range(1, 12):
        u = f"https://www.e-stat.go.jp/stat-search/files?page={page}&layout=datalist&toukei=00200521&tstat=000001230925&cycle=0&tclass1=000001230926" + (f"&tclass2={tc2}&tclass3val=0" if tc2 else "&tclass2val=0")
        h = get(u)
        for m in re.finditer(r'class="stat-dataset_list-detail-item[^"]*"[^>]*>(.*?)</', h, re.S):
            pass
        t = text(h)
        found = re.findall(r"((?:表|第)\s?[0-9０-９]+(?:-[0-9]+)?\s?表?\s[^E]{5,120}?)\s(?:EXCEL|CSV|ＣＳＶ|DB)", t)
        if not found and page == 1: print("  no titles", tc2, t[:300])
        for f in found:
            if f not in seen:
                seen.add(f)
                if re.search(r"住宅|住居|所有|建て方|延べ面積|教育|在学|通勤|常住", f): print("  *", f[:160])
        if not found: break
print("  total titles", len(seen))
for f in list(seen)[:15]: print("   sample", f[:120])
print("#### tokyo election 2026")
for u in ["https://www.opendata.metro.tokyo.lg.jp/senkyokanri/r8_syuugiin_hirei_touhyou.csv",
          "https://www.opendata.metro.tokyo.lg.jp/senkyokanri/r8_syuugiin_senkyoku_touhyou.csv",
          "https://www.senkyo.metro.tokyo.lg.jp/election/shugiin-all/"]:
    print("  ", get(u, head=True), u)
t = text(get("https://www.senkyo.metro.tokyo.lg.jp/"))
for k in ["衆議院", "令和8年2月"]:
    for m in list(re.finditer(k, t))[:5]: print("   ", k, "|", t[max(0,m.start()-60):m.start()+100])
