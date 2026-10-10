import math, urllib.request, json, re
def tile(lat, lon, z):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return x, y
def code(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as r:
            return r.status, len(r.read())
    except urllib.error.HTTPError as e:
        return e.code, 0
    except Exception as e:
        return str(e)[:30], 0
places = {"千代田": (35.684, 139.754), "世田谷": (35.646, 139.653), "札幌": (43.062, 141.354), "大阪": (34.702, 135.496),
          "名古屋": (35.170, 136.881), "福岡": (33.590, 130.402), "仙台": (38.260, 140.882), "松本": (36.238, 137.972),
          "那覇": (26.212, 127.681), "高知": (33.559, 133.531)}
layers = [f"nendophoto{y}" for y in range(2004, 2027)] + ["gazo1", "gazo2", "gazo3", "gazo4", "ort_old10", "ort_USA10", "ort_riku10", "ort_1928", "airphoto", "ort", "seamlessphoto"]
for lay in layers:
    out = []
    for name, (lat, lon) in places.items():
        z = 14 if not lay.startswith("ort_riku") else 14
        x, y = tile(lat, lon, z)
        ext = "jpg" if lay in ("gazo1", "gazo2", "gazo3", "gazo4", "ort_old10", "ort_USA10", "ort_riku10", "ort_1928", "airphoto", "ort", "seamlessphoto") else "png"
        st, n = code(f"https://cyberjapandata.gsi.go.jp/xyz/{lay}/{z}/{x}/{y}.{ext}")
        if st == 404 and ext == "jpg":
            st, n = code(f"https://cyberjapandata.gsi.go.jp/xyz/{lay}/{z}/{x}/{y}.png")
            st = f"{st}p"
        out.append(f"{name}:{st}/{n//1000}k")
    print(lay, " ".join(out), flush=True)
for u in ["https://maps.gsi.go.jp/layers_txt/layers3.txt", "https://maps.gsi.go.jp/layers_txt/layers2.txt"]:
    try:
        t = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read().decode("utf-8", "replace")
        print("==", u, len(t))
        for m in re.finditer(r'"id"\s*:\s*"([^"]+)"\s*,\s*"title"\s*:\s*"([^"]+)"', t):
            if re.search(r"photo|gazo|ort|airphoto|nendo|写真", m.group(1) + m.group(2)):
                print(m.group(1), m.group(2))
        for m in re.finditer(r'nendophoto\d{4}[^"]*', t):
            pass
        print(sorted(set(re.findall(r'nendophoto\d{4}', t))))
    except Exception as e:
        print("ERR", u, e)
