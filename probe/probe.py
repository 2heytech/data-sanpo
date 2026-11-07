import subprocess, sys, os, re, csv, io, zipfile, collections
def sh(c): print("$",c,flush=True); subprocess.run(c,shell=True)
sh("sudo apt-get install -y -q poppler-utils >/dev/null 2>&1; which pdftotext")
sh("git fetch -q origin claude/new-indicators-1106 && git worktree add -q /tmp/nw FETCH_HEAD")
sys.path.insert(0,"/tmp/nw/pipeline")
UA="Mozilla/5.0 (data-sanpo probe)"
def get(u): return subprocess.run(["curl","-sSL","-A",UA,"--max-time","300",u],capture_output=True).stdout
os.makedirs("/tmp/p",exist_ok=True)
def links(page, pat):
    h=get(page).decode("utf-8","replace")
    print("--- links", page)
    for m in re.finditer(r'href="([^"]+)"[^>]*>(.{0,120}?)</a>', h, re.S):
        if re.search(pat, m.group(1)+m.group(2)): print(" ", m.group(1), re.sub(r"\s+"," ",re.sub("<[^>]+>","",m.group(2)))[:100])
# 1 kaigo
print("\n===== KAIGO", flush=True)
b=get("https://www.e-stat.go.jp/stat-search/file-download?fileKind=1&statInfId=000040386470")
t=b.decode("cp932","replace"); rows=list(csv.reader(io.StringIO(t)))
print(len(rows))
for r in rows[:8]: print(r)
for r in rows:
    if r and re.match(r"(00000|13000|13100|13101|13102|13360|13364|14100|14101|01100|01101|47382|01000|43100|43101|26100|26101)", r[0]): print(r)
print(collections.Counter(len(r) for r in rows))
print("codes", sum(1 for r in rows if r and re.match(r"\d{5}",r[0])))
vals=collections.Counter(v for r in rows[4:] for v in r[1:] if not re.fullmatch(r"[\d,]+",v)); print(vals.most_common(10))
# 2 park
print("\n===== PARK", flush=True)
links("https://www.mlit.go.jp/toshi/park/toshi_parkgreen_tk_000156.html", r"xlsx|xls|一覧表")
p="/tmp/p/park.xlsx"; open(p,"wb").write(get("https://www.mlit.go.jp/toshi/park/content/05_R06.xlsx"))
from tdm import xlsx
try:
    import zipfile as z; print(z.ZipFile(p).namelist()[:20])
    print([n for n in dir(xlsx) if not n.startswith("_")])
except Exception as e: print(e)
sh(f"{sys.executable} -m pip install -q --user --break-system-packages openpyxl")
import site; sys.path.append(site.getusersitepackages())
import openpyxl
wb=openpyxl.load_workbook(p, data_only=True, read_only=True); print(wb.sheetnames)
ws=wb["市町村別"]; R=list(ws.iter_rows(values_only=True)); print(len(R))
from openpyxl.utils import get_column_letter as L
for i in range(4):
    print(i+1, [(L(j+1),v) for j,v in enumerate(R[i]) if v is not None])
for r in R[4:]:
    if r[0] and str(r[0])[:5] in ("01100","01202","13101","13104","13201","14100","14131","47382","13362","01101","13999"): print([(L(j+1),v) for j,v in enumerate(r) if v is not None and j in (0,1,2,38,40,46,47,48,49,50,55,56)])
codes=[str(r[0]) for r in R[4:] if r[0]]
print("n",len(codes), "ward-like", [c for c in codes if c[:2]!="13" and c[2]=="1" and c[3:]!="00"][:20])
print("zeroAV", sum(1 for r in R[4:] if r[0] and not r[47]), [ (r[0],r[2],r[40],r[47]) for r in R[4:] if r[0] and not r[47]][:10])
# 3 sewer
print("\n===== SEWER", flush=True)
links("https://www.mlit.go.jp/mizukokudo/sewerage/crd_sewerage_tk_000104.html", r"pdf|xls|市町村")
open("/tmp/p/sewer.pdf","wb").write(get("https://www.mlit.go.jp/mizukokudo/sewerage/content/002026897.pdf"))
sh("pdfinfo /tmp/p/sewer.pdf | head -20; pdftotext -layout /tmp/p/sewer.pdf /tmp/p/sewer.txt; wc -l /tmp/p/sewer.txt; sed -n 1,90p /tmp/p/sewer.txt; echo ...; grep -n '東京\\|千代田\\|八王子\\|大島\\|横浜\\|檜原\\|奥多摩' /tmp/p/sewer.txt | head -20; tail -30 /tmp/p/sewer.txt")
# 4 water
print("\n===== WATER", flush=True)
links("https://www.digital.go.jp/resources/govdashboard/watersupply", r"zip|csv")
zb=get("https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/9112b58e-556c-429e-906f-45be48b63fd9/db7e75fb/20260703_resources_govdashboard_watersupply_table_02.zip")
zf=zipfile.ZipFile(io.BytesIO(zb)); print(zf.namelist())
name=[n for n in zf.namelist() if n.endswith("2024.csv")][0]
t=zf.read(name).decode("utf-8-sig"); rd=list(csv.DictReader(io.StringIO(t))); print(len(rd), list(rd[0].keys())); print(rd[0])
fee=[r for r in rd if "料金(家庭用)" in r["item_name"] and "20㎥" in r["item_name"]]
print(len(fee), collections.Counter(r["item_name"] for r in fee))
print(collections.Counter((r["facility_code_name"],r["cond_1_business_type"],r["cond_2_operating_entity"]) for r in fee).most_common(20))
ents=collections.defaultdict(list)
for r in fee: ents[r["local_public_enterprise_code"]].append(r)
print("enterprises", len(ents))
for k,v in list(ents.items())[:5]: print(k, [(x["local_public_enterprise_name"],x["facility_code"],x["item_name"][-6:],x["item_value"]) for x in v])
for r in fee:
    if re.search("東京都|横浜市|千代田|大阪市|企業団|札幌市|八王子|川崎市", r["local_public_enterprise_name"]): print(r["local_public_enterprise_code"], r["local_public_enterprise_name"], r["facility_code"], r["cond_2_operating_entity"], r["item_name"][-6:], r["item_value"], r["item_unit"])
codes=collections.Counter(len(r["local_public_enterprise_code"]) for r in fee); print(codes)
other=collections.Counter(r["item_name"] for r in rd if "料金" in r["item_name"]); print(other.most_common(30))
print(collections.Counter(r["statistical_table_name"] for r in rd).most_common(10))
print(collections.Counter(r["item_value"] for r in fee if not re.fullmatch(r"[\d.]+", r["item_value"] or "")).most_common(5))
# 5 kodomo
print("\n===== KODOMO", flush=True)
links("https://www.cfa.go.jp/policies/boshihoken/kodomoiryouhityousa-r7", r"pdf|xls|csv")
open("/tmp/p/k.pdf","wb").write(get("https://www.cfa.go.jp/assets/contents/node/basic_page/field_ref_resources/6a9b8926-411c-4044-81aa-d8c26b21aaf5/12ae0d40/20251224policies-boshihoken-kodomoiryouhityousa-r7-03.pdf"))
sh("pdfinfo /tmp/p/k.pdf | head; pdftotext -layout /tmp/p/k.pdf /tmp/p/k.txt; wc -l /tmp/p/k.txt; sed -n 1,80p /tmp/p/k.txt; grep -n '千代田\\|八王子\\|横浜\\|大阪市\\|札幌' /tmp/p/k.txt | head; awk 'length>0' /tmp/p/k.txt | cut -c1-200 | sed -n 1500,1530p")
