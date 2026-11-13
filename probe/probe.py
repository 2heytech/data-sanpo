import subprocess, re, os, sys
subprocess.run("sudo apt-get -qq install -y poppler-utils > /dev/null 2>&1", shell=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
URLS = {
  "izena_2020": "https://vill.izena.okinawa.jp/userfiles/files/autoupload/2020/04/1586940131.pdf",
  "okinawa_suidou": "https://www.pref.okinawa.lg.jp/_res/projects/default_project/_page_/001/012/446/suidou.pdf",
  "yamanashi_r6_houteki": "https://www.pref.yamanashi.jp/documents/28428/r6_houteki_kohai.pdf",
  "yamanashi_ryokin_h31": "https://www.pref.yamanashi.jp/documents/96246/6suidoryokin.pdf",
  "yamanashi_018": "https://www.pref.yamanashi.jp/documents/80968/018.pdf",
  "yamanashi_6ryoukin": "https://www.pref.yamanashi.jp/documents/25450/6ryoukin.pdf",
}
KEYS = ["伊是名", "鳴沢", "丹波山", "道志", "西桂", "山中湖", "梼原", "檮原", "基本料金", "超過"]
os.makedirs("/tmp/d", exist_ok=True)
for k, u in URLS.items():
    p = f"/tmp/d/{k}.pdf"
    r = subprocess.run(["curl", "-sSL", "-A", UA, "--max-time", "120", "-o", p, "-w", "%{http_code} %{size_download}", u], capture_output=True, text=True)
    print("####", k, r.stdout, u)
    if not r.stdout.startswith("200"):
        continue
    t = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout
    info = subprocess.run(["pdfinfo", p], capture_output=True, text=True).stdout
    print("pages:", re.search(r"Pages:\s+(\d+)", info).group(1) if "Pages" in info else "?", "chars:", len(t))
    lines = t.splitlines()
    shown = set()
    for i, l in enumerate(lines):
        if any(x in l for x in KEYS[:8]):
            for j in range(max(0, i - 2), min(len(lines), i + 4)):
                if j not in shown:
                    shown.add(j)
                    print(f"{j:5d}| {lines[j][:260]}")
            print("     ...")
    if k == "izena_2020":
        print("\n".join(l[:200] for l in lines[:80]))
