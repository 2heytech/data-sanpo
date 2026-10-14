import urllib.request
UA = {"User-Agent": "Mozilla/5.0"}
for y in ("2020", "2015"):
    u = f"https://www.toukei.metro.tokyo.lg.jp/tyukanj/{y}/tj{y[2:]}zv0100.csv"
    t = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read().decode("utf-8-sig")
    for line in t.splitlines():
        if line.split(",")[1:2] and line.split(",")[1] in ("13000", "13101", "13104", "13421", "地域コード"): print(y, line[:200])
