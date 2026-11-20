import subprocess, re, html
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
def get(u):
    return subprocess.run(["curl", "-sSL", "-A", UA, "--max-time", "120", u], capture_output=True).stdout.decode("utf-8", "replace")
print("#### census raw")
h = get("https://www.e-stat.go.jp/stat-search/files?page=1&layout=datalist&toukei=00200521&tstat=000001230925&cycle=0&tclass1=000001230926&tclass2=000001232187&tclass3val=0")
i = h.find("1-1"); print(len(h), i)
print(re.sub(r"\s+", " ", h[i-1500:i+1500]))
links = re.findall(r'href="([^"]*tclass[^"]*)"[^>]*>\s*([^<]{2,80})<', h)
for l, t in links[:60]: print("  L", t.strip()[:60], "|", html.unescape(l)[:200])
print("#### tokyo senkyo")
h = get("https://www.senkyo.metro.tokyo.lg.jp/")
for l, t in re.findall(r'href="([^"]+)"[^>]*>([^<]*衆議院[^<]*)<', h)[:10]: print("  ", t.strip(), l)
