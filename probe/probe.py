import subprocess, re, os, urllib.parse
subprocess.run("sudo apt-get -qq install -y poppler-utils > /dev/null 2>&1", shell=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
os.makedirs("/tmp/d", exist_ok=True)
n = 0
def fetch(u):
    global n
    n += 1
    p = f"/tmp/d/f{n}"
    r = subprocess.run(["curl", "-sSL", "-A", UA, "--max-time", "120", "-o", p, "-w", "%{http_code} %{content_type}", u], capture_output=True, text=True)
    return r.stdout, p
def html_text(p):
    raw = open(p, "rb").read()
    for enc in ("utf-8", "cp932", "euc-jp"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")
def strip(s):
    s = re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S)
    s = re.sub(r"<(br|/p|/tr|/li|/h\d|/div)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<td[^>]*>|<th[^>]*>", " | ", s, flags=re.I)
    return re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", "", s))
def links(base, s, pat):
    out = []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', s, flags=re.S | re.I):
        t = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if re.search(pat, t) or re.search(pat, m.group(1)):
            out.append((urllib.parse.urljoin(base, m.group(1)), t[:80]))
    return out
def show_pdf(u, keys=r"料金|円|㎥|m3|ｍ３|立方"):
    st, p = fetch(u)
    print("  PDF", st, u)
    if not st.startswith("200"):
        return
    t = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout
    pages = t.split("\f")
    print("  pages", len(pages), "chars", len(t))
    for i, pg in enumerate(pages):
        if re.search(r"料金", pg) and re.search(r"基本|超過|従量|使用料", pg):
            print(f"  --- page {i + 1}")
            for l in pg.splitlines():
                if re.search(keys, l):
                    print("   ", l.strip()[:200])
# 筑北村
print("#### chikuhoku")
st, p = fetch("https://www.vill.chikuhoku.lg.jp/docs/159.html")
print(st)
if st.startswith("200"):
    s = html_text(p)
    for u, t in links("https://www.vill.chikuhoku.lg.jp/docs/159.html", s, r"\.pdf|経営戦略|水道"):
        print("  link", t, u)
        if u.lower().endswith(".pdf") and ("簡易水道" in t or "kan" in u.lower() or "経営" in t):
            show_pdf(u)
    print(strip(s)[:1500])
# 伊是名村
print("#### izena")
for seed in ["https://vill.izena.okinawa.jp/", "https://vill.izena.okinawa.jp/sitemap/"]:
    st, p = fetch(seed)
    print(seed, st)
    if st.startswith("200"):
        s = html_text(p)
        for u, t in links(seed, s, r"水道|上下水|料金|例規"):
            print("  link", t, u)
# 沖縄の水道の料金の表
print("#### okinawa table")
st, p = fetch("https://www.pref.okinawa.lg.jp/_res/projects/default_project/_page_/001/012/446/suidou.pdf")
t = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout
lines = t.splitlines()
idx = [i for i, l in enumerate(lines) if "伊是名村" in l and "簡易水道" in l]
for i in idx[:1]:
    for j in range(max(0, i - 45), min(len(lines), i + 5)):
        print(f"{j:5d}| {lines[j][:200]}")
