import subprocess, sys, os, re, csv, io, zipfile, collections
def sh(c): print("$",c,flush=True); subprocess.run(c,shell=True)
sh("sudo apt-get install -y -q poppler-utils >/dev/null 2>&1; which pdftotext")
UA="Mozilla/5.0 (data-sanpo probe)"
def get(u): return subprocess.run(["curl","-sSL","-A",UA,"--max-time","300",u],capture_output=True).stdout
os.makedirs("/tmp/p",exist_ok=True)
print("\n===== WATER1", flush=True)
zb=get("https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/9112b58e-556c-429e-906f-45be48b63fd9/ce527c83/20260703_resources_govdashboard_watersupply_table_01.zip")
zf=zipfile.ZipFile(io.BytesIO(zb)); print(zf.namelist())
for n in zf.namelist():
    b=zf.read(n); print("--",n,len(b))
    if n.endswith(".csv"):
        t=b.decode("utf-8-sig","replace"); print("\n".join(t.splitlines()[:3])[:1500])
    elif n.endswith(".xlsx"):
        sh(f"true")
        open("/tmp/p/x.xlsx","wb").write(b)
        sh(f"{sys.executable} -m pip install -q --user --break-system-packages openpyxl")
        import site; sys.path.append(site.getusersitepackages()); import openpyxl
        wb=openpyxl.load_workbook("/tmp/p/x.xlsx", read_only=True)
        for ws in wb.worksheets:
            print("sheet", ws.title)
            for i,r in enumerate(ws.iter_rows(values_only=True)):
                if i>3: break
                print(r[:30])
print("\n===== WATER2", flush=True)
zb=get("https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/9112b58e-556c-429e-906f-45be48b63fd9/db7e75fb/20260703_resources_govdashboard_watersupply_table_02.zip")
zf=zipfile.ZipFile(io.BytesIO(zb))
for y in (2014, 2019, 2024):
    t=zf.read(f"{y}.csv").decode("utf-8-sig"); rd=list(csv.DictReader(io.StringIO(t)))
    fee=[r for r in rd if r["item_name"].endswith("1か月20㎥当たり料金__口径20mm")]
    print(y, len(fee), collections.Counter(r["facility_code"] for r in fee), collections.Counter(r["cond_2_operating_entity"] for r in fee))
    if y==2024:
        for r in fee:
            if r["local_public_enterprise_code"].startswith("13") or r["local_public_enterprise_code"].startswith("27") and "企業団" in r["local_public_enterprise_name"]: print(r["local_public_enterprise_code"], r["local_public_enterprise_name"], r["facility_code"], r["item_value"])
        items=collections.Counter(r["item_name"] for r in rd if r["statistical_table_number"].startswith("01"))
        print([k for k in items if re.search("区域|人口|市町村|構成", k)][:40])
        ex=[r for r in rd if r["local_public_enterprise_code"]=="278688" and re.search("区域|人口|市町村|構成", r["item_name"])]
        for r in ex[:20]: print(r["item_name"], r["item_value"])
        vals=collections.Counter(r["item_value"] for r in fee if not re.fullmatch(r"\d+", r["item_value"])); print(vals)
        dup=collections.Counter((r["local_public_enterprise_code"],r["facility_code"]) for r in fee); print([k for k,v in dup.items() if v>1][:5])
print("\n===== SEWER", flush=True)
open("/tmp/p/sewer.pdf","wb").write(get("https://www.mlit.go.jp/mizukokudo/sewerage/content/002026897.pdf"))
sh("pdftotext -layout /tmp/p/sewer.pdf /tmp/p/sewer.txt; sed -n 185,200p /tmp/p/sewer.txt; grep -o '[^ ]*区[^ ]*' /tmp/p/sewer.txt | sort | uniq -c | head -40; grep -oE '(＊|－|-|…|―)' /tmp/p/sewer.txt | sort | uniq -c")
sh("pdftotext -bbox /tmp/p/sewer.pdf /tmp/p/sewer.html; grep -c '<word' /tmp/p/sewer.html; grep '<word' /tmp/p/sewer.html | sed -n 1,25p; grep '<page' /tmp/p/sewer.html")
print("\n===== KODOMO", flush=True)
open("/tmp/p/k.pdf","wb").write(get("https://www.cfa.go.jp/assets/contents/node/basic_page/field_ref_resources/6a9b8926-411c-4044-81aa-d8c26b21aaf5/12ae0d40/20251224policies-boshihoken-kodomoiryouhityousa-r7-03.pdf"))
sh("pdftotext -layout /tmp/p/k.pdf /tmp/p/k.txt")
t=open("/tmp/p/k.txt").read()
rows=[l.split() for l in t.splitlines() if re.match(r"\s*\S+[都道府県]\s+\d+\s", l)]
print(len(rows), collections.Counter(len(r) for r in rows))
print(collections.Counter(r[3] for r in rows).most_common(30)); print(collections.Counter(r[4] for r in rows).most_common(30))
print(collections.Counter(tuple(r[5:]) for r in rows).most_common(20))
for r in rows:
    if len(r)!=9: print(r)
print(collections.Counter(r[0] for r in rows))
for r in rows:
    if re.search("区$", r[2]) and r[0]!="東京都": print(r)
odd=[l for l in t.splitlines() if l.strip() and not re.match(r"\s*\S+[都道府県]\s+\d+\s", l)]
print(collections.Counter(odd).most_common(12)); print([l for l in odd if "注" in l or "※" in l][:20])
