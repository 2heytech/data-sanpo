import subprocess, re, os
subprocess.run("sudo apt-get -qq install -y poppler-utils > /dev/null 2>&1", shell=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
def fetch(u, p):
    r = subprocess.run(["curl", "-sSL", "-A", UA, "--max-time", "180", "-o", p, "-w", "%{http_code} %{content_type} %{size_download}", u], capture_output=True, text=True)
    return r.stdout
for name, u in [("r6_page", "https://www.pref.yamanashi.jp/jogesuido/r6yamanashikennosuidou.html"),
                ("r5_page", "https://www.pref.yamanashi.jp/jogesuido/r5yamanashikennosuidou.html")]:
    st = fetch(u, "/tmp/p.html")
    print("####", name, st)
    s = open("/tmp/p.html", "rb").read().decode("utf-8", "replace")
    for m in re.finditer(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', s, flags=re.S | re.I):
        print("  ", re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip()[:60], m.group(1))
# 料金の表（令和5年度版）
for name, u in [("r5_ryokin", "https://www.pref.yamanashi.jp/documents/124831/01-6_suidouryoukin.pdf"),
                ("r4_full", "https://www.pref.yamanashi.jp/documents/119454/r4zentaiban1.pdf")]:
    st = fetch(u, f"/tmp/{name}.pdf")
    print("####", name, st)
    t = subprocess.run(["pdftotext", "-layout", f"/tmp/{name}.pdf", "-"], capture_output=True, text=True).stdout
    lines = t.splitlines()
    if name == "r4_full":
        i0 = next(i for i, l in enumerate(lines) if "道志村" in l and "公営" in l)
        # 表の見出しを探す（上へさかのぼる）
        for j in range(max(0, i0 - 60), i0 + 45):
            print(f"{j:5d}| {lines[j][:260]}")
    else:
        for i, l in enumerate(lines):
            if re.search(r"鳴沢|丹波山|道志|西桂|山中湖", l) or i < 30:
                print(f"{i:5d}| {l[:260]}")
