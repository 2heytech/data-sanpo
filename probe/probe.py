import re, urllib.request, urllib.parse, html, subprocess
UA={"User-Agent":"Mozilla/5.0"}
def get(u): return urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=120).read()
for q in ["不詳補完値 昼間人口","不詳補完値 昼夜間人口比率","不詳補完値 従業地・通学地"]:
  for lay in ["datalist","dataset"]:
    u="https://www.e-stat.go.jp/stat-search/files?page=1&layout=%s&toukei=00200521&query=%s"%(lay,urllib.parse.quote(q))
    try: t=get(u).decode("utf-8","ignore")
    except Exception as e: print("ERR",q,e); continue
    for blk in re.findall(r'<article class="stat-dataset_list-item.*?</article>|<li class="stat-search_result-item.*?</li>', t, re.S):
        tx=re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]+>',' ',blk))).strip()
        sid=sorted(set(re.findall(r'statInfId=(\d+)&fileKind=(\d)', blk)))
        tst=sorted(set(re.findall(r'tstat=(\d+)', blk)))
        if '2020' in tx or '令和2' in tx or '令和２' in tx: print("HIT",lay,q,"|",tx[:300],sid,tst)
open("n.pdf","wb").write(get("https://www.stat.go.jp/info/mail/pdf/20220722_no1471.pdf"))
subprocess.run(["sudo","apt-get","install","-y","-qq","poppler-utils"],capture_output=True)
t=subprocess.run(["pdftotext","-layout","n.pdf","-"],capture_output=True,text=True).stdout
for l in t.splitlines():
    if re.search(r'補完|昼夜|東京|埼玉|大阪|e-Stat|表',l): print("PDF",l.strip()[:200])
