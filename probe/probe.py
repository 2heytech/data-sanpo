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
def xls_rows(data,rows):
    b=xlrd.open_workbook(file_contents=data)
    sh=b.sheets()[0]
    print("-- sheet",sh.name,sh.nrows,sh.ncols)
    for i in rows:
        if i<sh.nrows: print(i,[str(c) for c in sh.row_values(i)])
for sid in ["000040463585","000040463591"]:
    sec("SSDS rows "+sid)
    try: xls_rows(dl(sid), list(range(0,4))+list(range(9,16))+list(range(1960,1970)))
    except Exception as e: print("ERR",e)
for sid in ["000040501271","000040501272"]:
    for k in (0,1,2,3,4):
        d=dl(sid,k); print(sid,k,len(d),d[:8])
        if d[:2]==b"PK" or d[:4]==b"\xd0\xcf\x11\xe0":
            try:
                if d[:2]==b"PK":
                    wb=openpyxl.load_workbook(io.BytesIO(d),read_only=True,data_only=True)
                    for i,row in enumerate(wb.worksheets[0].iter_rows(max_row=16,values_only=True)):
                        c=[str(x).replace("\n","") for x in row[:40] if x is not None]
                        if c: print(i,c)
                else: xls_rows(d, range(0,16))
            except Exception as e: print("ERR",e)
            break
for pg in (1,2,3,4,5,6):
    sec(f"housing page {pg}")
    t=get(f"https://www.e-stat.go.jp/stat-search/files?page={pg}&layout=dataset&toukei=00200522&tstat=000001207800&tclass1=000001207808&tclass2=000001207809").decode("utf-8","replace")
    txt=H.unescape(re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",t)))
    for m in re.finditer(r"第[０-９0-9]+(?:[－\-][０-９0-9]+)?表.{0,170}", txt):
        x=m.group(0)
        if "延べ" in x or "畳" in x or "面積" in x: print(x[:200])
    ids=re.findall(r"statInfId=(\d{12})&amp;fileKind=0", t)
    print("ids", len(ids), ids[:3], ids[-3:])
