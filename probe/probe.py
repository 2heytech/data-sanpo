import subprocess, re, os
subprocess.run("sudo apt-get -qq install -y poppler-utils > /dev/null 2>&1", shell=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
URLS = {
  "yamanashi_r4": "https://www.pref.yamanashi.jp/documents/119454/r4zentaiban1.pdf",
  "narusawa_page": "https://www.vill.narusawa.yamanashi.jp/gyosei/soshikikarasagasu/shinkoka/jogesuido/554.html",
  "narusawa_reiki": "https://www1.g-reiki.net/vill.narusawa/reiki_honbun/e662RG00000264.html",
  "okinawa_suidou": "https://www.pref.okinawa.lg.jp/_res/projects/default_project/_page_/001/012/446/suidou.pdf",
}
KEYS = ["鳴沢", "丹波山", "道志", "西桂", "山中湖"]
os.makedirs("/tmp/d", exist_ok=True)
def text_of(k, p):
    if p.endswith(".pdf"):
        return subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout
    raw = open(p, "rb").read()
    for enc in ("utf-8", "shift_jis", "euc-jp", "cp932"):
        try:
            s = raw.decode(enc); break
        except UnicodeDecodeError:
            continue
    s = re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S)
    s = re.sub(r"<(br|/p|/tr|/li|/h\d|/div)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<td[^>]*>|<th[^>]*>", " | ", s, flags=re.I)
    return re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", "", s))
for k, u in URLS.items():
    p = f"/tmp/d/{k}." + ("pdf" if u.endswith(".pdf") else "html")
    r = subprocess.run(["curl", "-sSL", "-A", UA, "--max-time", "120", "-o", p, "-w", "%{http_code} %{size_download}", u], capture_output=True, text=True)
    print("####", k, r.stdout, u)
    if not r.stdout.startswith("200"):
        continue
    t = text_of(k, p)
    lines = t.splitlines()
    print("lines", len(lines))
    if k.startswith("narusawa"):
        for i, l in enumerate(lines):
            if re.search(r"料金|円|立方|m3|㎥|基本|超過|別表", l):
                print(f"{i:5d}| {l.strip()[:220]}")
        continue
    if k == "okinawa_suidou":
        for i, l in enumerate(lines):
            if "伊是名" in l or "渡名喜" in l:
                for j in range(max(0, i - 25), min(len(lines), i + 3)):
                    print(f"{j:5d}| {lines[j][:220]}")
                print("   ...")
                break
        continue
    # 料金のページを探す
    hits = [i for i, l in enumerate(lines) if any(x in l for x in KEYS)]
    print("hits", len(hits))
    for i in hits:
        print(f"{i:5d}| {lines[i][:300]}")
    for i, l in enumerate(lines):
        if re.search(r"料金", l) and re.search(r"(10|20)\s*(m3|㎥|ｍ３|m³)", l):
            print("FEEHDR", i, l[:250])
