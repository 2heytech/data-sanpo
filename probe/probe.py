import subprocess, re, sys, io, csv, html as H
subprocess.run([sys.executable,"-m","pip","install","-q","--user","--break-system-packages","openpyxl"]); import site; sys.path.append(site.getusersitepackages())
import openpyxl
subprocess.run([sys.executable,"-m","pip","install","-q","--user","--break-system-packages","xlrd"])
import xlrd
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
    seen=set()
    for m in re.finditer(r'statInfId=(\d{12})',t):
        sid=m.group(1)
        if sid in seen: continue
        seen.add(sid)
        a=t.rfind('stat-dataset_list-detail-item',0,m.start())
        chunk=t[max(0,m.start()-1500):m.start()]
        txt=H.unescape(re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',chunk))).strip()
        print(sid, "|", txt[-300:])
    print("ids:",len(seen))
def head_rows(data, maxrow=12, maxcol=200):
    wb=openpyxl.load_workbook(io.BytesIO(data),read_only=True,data_only=True)
    for ws in wb.worksheets[:2]:
        print("-- sheet",ws.title, ws.max_row, ws.max_column)
        for i,row in enumerate(ws.iter_rows(max_row=maxrow,values_only=True)):
            cells=[str(c).replace("\n","") for c in row[:maxcol] if c is not None]
            if cells: print(i,cells)
urls=["000607404","000607409","000676021","000676026","000738077","000738082","000800820","000800828","000871019","000871024","000937288","000937293","000999901","000999906","001061670","001061675"]
sec("settlement 法人分")
for u in urls:
    try:
        d=get(f"https://www.soumu.go.jp/main_content/{u}.xlsx")
        wb=openpyxl.load_workbook(io.BytesIO(d),read_only=True,data_only=True); ws=wb.worksheets[0]
        hit=[]
        for i,row in enumerate(ws.iter_rows(max_row=16,values_only=True)):
            for j,c in enumerate(row):
                if c is not None and re.sub(r"\s+","",str(c))=="うち市町村民税法人分": hit.append((i,j))
        print(u, hit)
    except Exception as e: print(u,"ERR",e)
def xls_rows(data,maxrow=12):
    b=xlrd.open_workbook(file_contents=data)
    for sh in b.sheets()[:2]:
        print("-- sheet",sh.name,sh.nrows,sh.ncols)
        for i in range(min(maxrow,sh.nrows)):
            cells=[str(c).replace("\n","") for c in sh.row_values(i) if str(c).strip()]
            if cells: print(i,cells)
for sid in [f"0000404635{n}" for n in range(84,94)]:
    try:
        sec("SSDS 2026 "+sid); xls_rows(dl(sid), 9)
    except Exception as e: print("ERR",e)
sec("medical list")
try:
    wb=openpyxl.load_workbook(io.BytesIO(dl("000040501275")),read_only=True,data_only=True)
    for row in wb.worksheets[0].iter_rows(values_only=True):
        if row and any(c and "市区町村" in str(c) for c in row): print(row)
except Exception as e: print("ERR",e)
for title,q in [("D3 医療施設 2025 市区町村編", "page=1&layout=dataset&toukei=00450021&query=%E5%B8%82%E5%8C%BA%E7%94%BA%E6%9D%91&year=20250")]:
    sec(title); t=get("https://www.e-stat.go.jp/stat-search/files?"+q).decode("utf-8","replace")
    for m in re.finditer(r'statInfId=(\d{12})&amp;fileKind=(\d)',t):
        print(m.group(1), m.group(2), H.unescape(re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",t[max(0,m.start()-2500):m.start()])))[-260:])
for pg in range(1,8):
    sec(f"housing page {pg}")
    t=get(f"https://www.e-stat.go.jp/stat-search/files?page={pg}&layout=dataset&toukei=00200522&tstat=000001207800&tclass1=000001207808&tclass2=000001207809").decode("utf-8","replace")
    txt=H.unescape(re.sub(r"\s+"," ",re.sub(r"<(?!/?a\b)[^>]+>"," ",t)))
    for m in re.finditer(r'(第[０-９0-9－\-]+表[^<]{5,160}?)\s', txt):
        if re.search("延べ面積|畳数|床面積", m.group(1)): print(m.group(1)[:200])
    for m in re.finditer(r'statInfId=(\d{12})&amp;fileKind=0', t):
        seg=H.unescape(re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",t[max(0,m.start()-3000):m.start()])))
        if re.search("延べ面積|畳数", seg[-900:]): print("ID", m.group(1), seg[-400:])
