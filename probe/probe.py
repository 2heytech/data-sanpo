import sys, re, io, json, zipfile, urllib.request, html
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def get(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
def text(h): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style).*?</\1>", " ", h))))
# 地理院コンテンツ利用規約
for u in ["https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html", "https://maps.gsi.go.jp/development/ichiran.html"]:
    try:
        t = text(get(u).decode("utf-8", "replace"))
        if "40182" in u:
            for kw in ["商用", "出典", "申請", "第三者", "政府標準", "CC BY", "クリエイティブ"]:
                for m in list(re.finditer(kw, t))[:3]: print("TERMS", kw, "|", t[max(0, m.start()-150):m.start()+200])
        else:
            for kw in ["色別標高図", "relief", "陰影起伏", "hillshade"]:
                for m in list(re.finditer(kw, t))[:3]: print("ICHIRAN", kw, "|", t[max(0, m.start()-100):m.start()+250])
    except Exception as e: print("ERR", u, e)
for u in ["https://cyberjapandata.gsi.go.jp/xyz/relief/5/28/12.png", "https://cyberjapandata.gsi.go.jp/xyz/relief/15/29100/12902.png", "https://cyberjapandata.gsi.go.jp/xyz/ort_USA10/12/3637/1612.png"]:
    try: print("TILE", u, len(get(u)))
    except Exception as e: print("TILE ERR", u, e)
# L02 地価調査
z = zipfile.ZipFile(io.BytesIO(get("https://nlftp.mlit.go.jp/ksj/gml/data/L02/L02-25/L02-25_13_GML.zip")))
print("L02 files", [n for n in z.namelist()][:20])
for n in z.namelist():
    if n.endswith(".geojson"):
        d = json.loads(z.read(n).decode("utf-8"))
        fs = d["features"]; print("L02", n, len(fs))
        for f in fs[:2]: print(json.dumps(f, ensure_ascii=False)[:3000])
        break
