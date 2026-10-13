import urllib.request, re, html
u = "https://www.jiji.com/sp/article?k=2026101300604&g=pol"
t = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read().decode("utf-8", "replace")
m = re.search(r"<title>(.*?)</title>", t, re.S); print("TITLE", m and html.unescape(m.group(1)))
body = re.sub(r"<script.*?</script>|<style.*?</style>", "", t, flags=re.S)
txt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "\n", body)))
for k in ("外国人", "％", "%", "万人"):
    pass
i = txt.find("外国人")
print(txt[max(0, i - 1500): i + 3500])
