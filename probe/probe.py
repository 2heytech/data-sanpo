import subprocess, re, sys, io, csv, html as H
subprocess.run([sys.executable,"-m","pip","install","-q","--user","--break-system-packages","openpyxl"]); import site; sys.path.append(site.getusersitepackages())
import openpyxl
UA="Mozilla/5.0 (data-sanpo probe)"
def get(u):
    return subprocess.run(["curl","-sSL","-A",UA,"--max-time","300",u],capture_output=True).stdout
def dl(sid,kind=0): return get(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind={kind}")
def sec(t): print("\n==========",t,flush=True)
def headers_xlsx(data,maxrow=15,pat=None):
    wb=openpyxl.load_workbook(io.BytesIO(data),read_only=True,data_only=True)
    for ws in wb.worksheets[:3]:
        print("-- sheet",ws.title)
        for i,row in enumerate(ws.iter_rows(max_row=maxrow,values_only=True)):
            cells=[str(c) for c in row if c is not None]
            if pat: cells=[c for c in cells if re.search(pat,c)]
            if cells: print(i,cells[:80])
def listing(q):
    u="https://www.e-stat.go.jp/stat-search/files?"+q
    t=get(u).decode("utf-8","replace")
    ids=re.findall(r'statInfId=(\d{12})',t)
    # titles near
    for m in re.finditer(r'<span class="stat-title-text"[^>]*>(.*?)</span>|statInfId=(\d{12})&amp;fileKind=(\d)',t,re.S):
        pass
    blocks=re.split(r'<article',t)
    for b in blocks[1:]:
        txt=re.sub(r'<[^>]+>',' ',b); txt=H.unescape(re.sub(r'\s+',' ',txt)).strip()
        sid=sorted(set(re.findall(r'statInfId=(\d{12})&amp;fileKind=(\d)',b)))
        if sid: print(sid, txt[:260])
    print("ids:",len(set(ids)))
try:
    sec("A t9-1a headers (economic census)")
    d=dl("000040067884"); print(len(d))
    headers_xlsx(d,maxrow=14,pat=r"^(5[6-9]|7[67]|58\d|76\d)_|飲食")
except Exception as e: print("ERR",e)
try:
    sec("B settlement city_2 2024 headers")
    d=get("https://www.soumu.go.jp/main_content/001061670.xlsx"); print(len(d))
    headers_xlsx(d,maxrow=14)
except Exception as e: print("ERR",e)
try:
    sec("C tax collection 2024 row names")
    d=dl("000040375642",1).decode("cp932","replace")
    names=[]
    for r in csv.reader(io.StringIO(d)):
        if len(r)>9 and r[9] not in names: names.append(r[9])
    print(names[:120])
except Exception as e: print("ERR",e)
for title,q in [
  ("D 医療施設調査 病床 市区町村", "page=1&query=%E5%B8%82%E5%8C%BA%E7%94%BA%E6%9D%91%E5%88%A5+%E7%97%85%E5%BA%8A&layout=dataset&toukei=00450021"),
  ("D2 医療施設調査 2023 list", "page=1&layout=dataset&toukei=00450021&tstat=000001030908&cycle=7&year=20230"),
  ("E 住宅土地 2023 市区町村 tables p1", "page=1&layout=dataset&toukei=00200522&tstat=000001207800&tclass1=000001207808&tclass2=000001207809"),
  ("E2 p2", "page=2&layout=dataset&toukei=00200522&tstat=000001207800&tclass1=000001207808&tclass2=000001207809"),
  ("E3 p3", "page=3&layout=dataset&toukei=00200522&tstat=000001207800&tclass1=000001207808&tclass2=000001207809"),
  ("F 可住地面積", "page=1&query=%E5%8F%AF%E4%BD%8F%E5%9C%B0%E9%9D%A2%E7%A9%8D&layout=dataset"),
  ("F2 市区町村のすがた", "page=1&query=%E7%B5%B1%E8%A8%88%E3%81%A7%E3%81%BF%E3%82%8B%E5%B8%82%E5%8C%BA%E7%94%BA%E6%9D%91%E3%81%AE%E3%81%99%E3%81%8C%E3%81%9F&layout=dataset"),
  ("G 介護サービス施設 市区町村", "page=1&query=%E4%BB%8B%E8%AD%B7%E4%BF%9D%E9%99%BA%E6%96%BD%E8%A8%AD+%E5%B8%82%E5%8C%BA%E7%94%BA%E6%9D%91&layout=dataset&toukei=00450042"),
]:
    try:
        sec(title); listing(q)
    except Exception as e: print("ERR",e)
for title,u in [("H 汚水処理 MLIT","https://www.mlit.go.jp/mizukokudo/sewerage/crd_sewerage_tk_000135.html"),
                ("I 都市公園 MLIT","https://www.mlit.go.jp/toshi/park/toshi_parkgreen_tk_000060.html"),
                ("I2 都市公園 MLIT","https://www.mlit.go.jp/toshi/park/toshi_parkgreen_fr_000011.html")]:
    try:
        sec(title); t=get(u).decode("utf-8","replace")
        print(re.sub(r'\s+',' ',H.unescape(re.sub(r'<[^>]+>',' ',t)))[:1500])
        for m in re.finditer(r'href="([^"]+\.(?:xlsx?|csv|zip|pdf))"[^>]*>(.*?)</a>',t,re.S):
            print(m.group(1), re.sub(r'<[^>]+>|\s+',' ',m.group(2))[:100])
    except Exception as e: print("ERR",e)
