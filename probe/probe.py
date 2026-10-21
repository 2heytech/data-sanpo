import re, urllib.request, html, io
import openpyxl
UA={"User-Agent":"Mozilla/5.0"}
def getb(u): return urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=180).read()
def get(u): return getb(u).decode("utf-8","ignore")
B="https://www.e-stat.go.jp"
base=B+"/stat-search/files?toukei=00200521&tstat=000001136464&tclass1=000001154387&tclass2=000001159626&tclass3val=0&layout=datalist&cycle=0"
cands=[]
for p in range(1,40):
    t=get(base+"&page=%d"%p)
    blks=re.findall(r'<article class="stat-dataset_list-item.*?</article>', t, re.S)
    if not blks: print("no rows at page",p); break
    for blk in blks:
        tx=re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]+>',' ',blk))).strip()
        ids=sorted(set(re.findall(r'statInfId=(\d+)&(?:amp;)?fileKind=(\d)',blk)))
        if re.search(r'昼夜間|昼間人口|従業地',tx):
            print("ROW",tx[:300],ids); cands.append((tx,ids))
print("cands",len(cands))
for tx,ids in cands:
    if "昼夜間" not in tx: continue
    for sid,k in ids:
        if k!="0": continue
        u=B+"/stat-search/file-download?statInfId=%s&fileKind=0"%sid
        try: data=getb(u)
        except Exception as e: print("DL fail",sid,e); continue
        print("=== FILE",sid,len(data),tx[:120])
        try: wb=openpyxl.load_workbook(io.BytesIO(data),read_only=True,data_only=True)
        except Exception as e: print("not xlsx",e,data[:80]); continue
        for ws in wb.worksheets[:2]:
            print("SHEET",ws.title)
            n=0
            for i,row in enumerate(ws.iter_rows(values_only=True)):
                n+=1
                cells=[str(c) for c in row if c is not None]
                s=" | ".join(cells)
                if i<14 or re.search(r'(^|\D)(00000|13000|27000|11000|26000|12000|14000|13101|13104)(\D|$)',s) and ('総数' in s or '総' in s or i<200000):
                    if i<14 or n<400000: print(i,s[:400])
            print("rows",n)
