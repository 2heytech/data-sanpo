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
for sid in ["000040501271","000040501272"]:
    sec("medical csv "+sid)
    t=dl(sid,1).decode("cp932","replace").splitlines()
    print(len(t))
    for l in t[:40]: print(l[:400])
    for l in t[-6:]: print(l[:400])
for title,u,pat in [("env pop","https://www.env.go.jp/recycle/jokaso/data/population/","普及|市町村|xls|csv"),
                    ("park156","https://www.mlit.go.jp/toshi/park/toshi_parkgreen_tk_000156.html","公園|xls|csv|市町村"),
                    ("park081","https://www.mlit.go.jp/toshi/park/toshi_parkgreen_tk_000081.html","公園|xls|csv|市町村")]:
    try:
        sec(title); t=get(u).decode("utf-8","replace")
        for m in re.finditer(r'href="([^"]+)"[^>]*>(.*?)</a>',t,re.S):
            txt=re.sub(r'<[^>]+>|\s+',' ',m.group(2)).strip()
            if re.search(pat,txt+m.group(1)): print(m.group(1), txt[:120])
    except Exception as e: print("ERR",e)
