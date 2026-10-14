# 一時的な確認用（元ファイルの形を見る）。PR に入れる前に消す。
import re, sys, urllib.request, io, zipfile
import openpyxl

UA = {"User-Agent": "Mozilla/5.0"}
def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read(), r.headers.get("Content-Type"), r.headers.get("Content-Disposition")

FILES = {
  "maff2024": "https://www.maff.go.jp/j/tokei/kouhyou/sityoson_sansyutu/attach/xls/index-25.xlsx",
  "maff2017": "https://www.maff.go.jp/j/tokei/kouhyou/sityoson_sansyutu/attach/xls/index-14.xlsx",
  "meti2025": "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040480531&fileKind=0",
  "meti2024ref": "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040480518&fileKind=0",
  "meti2022": "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040137360&fileKind=0",
  "com1": "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040032863&fileKind=0",
  "com2": "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040032864&fileKind=0",
}
PAGES = {
  "com_page": "https://www.e-stat.go.jp/stat-search/files?layout=dataset&stat_infid=000040032863",
}
KEYS = re.compile(r"豊田|川上村|千代田|檜原|札幌|北区|全国|合計|X|x|…|－|-")

def show_sheet(ws, n=25):
    rows = list(ws.iter_rows(values_only=True))
    print(f"  sheet {ws.title!r} rows={len(rows)} cols={ws.max_column}")
    for i, r in enumerate(rows[:n]):
        print("   ", i, [c for c in r[:40]])
    hits = 0
    for i, r in enumerate(rows):
        s = " ".join(str(c) for c in r if c is not None)
        if re.search(r"豊田市|川上村|千代田区|檜原村|中央区", s):
            print("   HIT", i, [c for c in r[:40]])
            hits += 1
            if hits > 8: break

for k, u in FILES.items():
    print("=" * 30, k, u)
    try:
        b, ct, cd = get(u)
    except Exception as e:
        print("  ERROR", e); continue
    print("  bytes", len(b), ct, cd)
    try:
        wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
    except Exception as e:
        print("  not xlsx", e, b[:200]); continue
    print("  sheets", wb.sheetnames[:60])
    for name in wb.sheetnames[:4]:
        show_sheet(wb[name])
    if len(wb.sheetnames) > 4:
        show_sheet(wb[wb.sheetnames[-1]], 12)

for k, u in PAGES.items():
    print("=" * 30, k, u)
    b, ct, cd = get(u)
    html = b.decode("utf-8", "replace")
    for m in sorted(set(re.findall(r'href="([^"]*(?:tclass|tstat|statInfId|stat_infid)[^"]*)"', html)))[:80]:
        print("  ", m.replace("&amp;", "&"))
    for m in re.findall(r'<span class="stat-title-text">(.*?)</span>|<li class="stat-dataset_list-detail-item[^>]*>(.*?)</li>', html, re.S)[:40]:
        print("  T", [re.sub(r"\s+", " ", re.sub("<[^>]+>", "", x)) for x in m])
