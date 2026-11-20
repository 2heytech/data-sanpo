import subprocess, re, html
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
def get(u):
    return subprocess.run(["curl", "-sSL", "-A", UA, "--max-time", "120", u], capture_output=True).stdout.decode("utf-8", "replace")
B = "https://www.senkyo.metro.tokyo.lg.jp"
h = get(B + "/")
cand = [l for l, t in re.findall(r'href="([^"]+)"[^>]*>\s*([^<]*)<', h) if "衆議院議員選挙・投開票結果" in t]
print("cand", cand)
for c in cand[:1]:
    u = c if c.startswith("http") else B + c
    h2 = get(u)
    for l, t in re.findall(r'href="([^"]+)"[^>]*>\s*([^<]{2,80})<', h2):
        if re.search(r"令和8|51回|r8|2026", l + t): print("  ", t.strip()[:70], "|", l)
    for l, t in re.findall(r'href="([^"]+)"[^>]*>\s*([^<]{2,80})<', h2):
        if re.search(r"令和8|51回", t):
            u3 = l if l.startswith("http") else B + l
            h3 = get(u3)
            for l3, t3 in re.findall(r'href="([^"]+)"[^>]*>\s*([^<]{1,80})<', h3):
                if re.search(r"csv|xlsx|xls|投票", l3 + t3, re.I): print("     ", t3.strip()[:60], "|", l3[:150])
            break
