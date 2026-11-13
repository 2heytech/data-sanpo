import subprocess, re, html, json
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
B = "https://data-sanpo.com"
def get(u):
    r = subprocess.run(["curl", "-sSL", "-A", UA, "--max-time", "60", B + u], capture_output=True, text=True)
    return r.stdout
def text(h):
    h = re.sub(r"(?s)<(script|style).*?</\1>", "", h)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h)))
def show(u, keys, w=90):
    t = text(get(u)); print("####", u, len(t))
    for k in keys:
        for m in list(re.finditer(re.escape(k), t))[:2]:
            print("   ", k, "|", t[max(0, m.start()-w):m.start()+w])
show("/indicators/total_fertility_rate/", ["1位", "人）", "2.2"])
show("/indicators/water_fee_household/", ["丹波山村", "筑北村", "鳴沢村", "赤穂市", "元の表", "伊是名村"])
show("/indicators/furusato_amount_per_capita/", ["白糠町", "2025年", "双葉町"])
show("/areas/muni-20452/", ["水道料金", "元の表"])
show("/areas/muni-47360/", ["水道料金", "元の表"])
show("/areas/muni-01668/", ["ふるさと納税", "住民1人"])
show("/areas/muni-28202/", ["住民基本台帳", "世帯"])
show("/prefectures/28/aged_65_plus_share/", ["1位", "ランキング"])
h = get("/")
m = re.search(r'/data/([^/"]+)/', h); print("release", m and m.group(1))
