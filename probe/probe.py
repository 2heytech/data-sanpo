import re, urllib.request, html
UA={"User-Agent":"Mozilla/5.0"}
def get(u): return urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=120).read().decode("utf-8","ignore")
def links(u, pat):
    t=get(u); out=[]
    for m in re.finditer(r'<a[^>]+href="([^"]*%s[^"]*)"[^>]*>(.*?)</a>'%pat, t, re.S):
        out.append((html.unescape(m.group(1)), re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]+>','',m.group(2)))).strip()))
    return out
B="https://www.e-stat.go.jp"
top=B+"/stat-search/files?page=1&toukei=00200521&tstat=000001136464"
seen=set()
for h,tx in links(top,"tclass1="):
    if h in seen: continue
    seen.add(h); print("T1",tx[:120],"|",h[:200])
    for h2,tx2 in links(B+h if h.startswith("/") else h,"tclass2="):
        if h2 in seen: continue
        seen.add(h2); print("   T2",tx2[:120],"|",h2[:200])
# 不詳補完値の表を探す
for h in list(seen):
    if "tclass" not in h: continue
    u=(B+h if h.startswith("/") else h)+"&layout=datalist"
    try: t=get(u)
    except Exception: continue
    for blk in re.findall(r'<article class="stat-dataset_list-item.*?</article>', t, re.S):
        tx=re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]+>',' ',blk))).strip()
        if re.search(r'補完|昼夜間',tx): print("ROW",tx[:250],sorted(set(re.findall(r'statInfId=(\d+)&fileKind=(\d)',blk))))
