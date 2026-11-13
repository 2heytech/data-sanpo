import subprocess, re
subprocess.run("sudo apt-get -qq install -y poppler-utils > /dev/null 2>&1", shell=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
u = "https://www.pref.yamanashi.jp/documents/124831/03-3_kanisuidoujigyou.pdf"
r = subprocess.run(["curl", "-sSL", "-A", UA, "--max-time", "180", "-o", "/tmp/k.pdf", "-w", "%{http_code} %{size_download}", u], capture_output=True, text=True)
print("####", r.stdout, u)
t = subprocess.run(["pdftotext", "-layout", "/tmp/k.pdf", "-"], capture_output=True, text=True).stdout
lines = t.splitlines()
for i, l in enumerate(lines):
    if re.search(r"道志|西桂|鳴沢|丹波山|山中湖|忍野|令和|現在", l):
        print(f"{i:5d}| {l[:300]}")
        if "鳴沢村" in l:
            print(f"{i+1:5d}| {lines[i+1][:300]}")
