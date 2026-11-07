import subprocess, sys, os, re, csv, io, zipfile, collections, json, urllib.parse
UA="Mozilla/5.0 (data-sanpo probe)"
def get(u): return subprocess.run(["curl","-sSL","-A",UA,"--max-time","300",u],capture_output=True).stdout
b=get("https://www.e-stat.go.jp/stat-search/file-download?fileKind=1&statInfId=000040386470")
rows=list(csv.reader(io.StringIO(b.decode("cp932","replace"))))
master={}
for r in rows:
    m=re.match(r"(\d{5})\s*(\S+)", r[0].replace("　"," ")) if r else None
    if m and not m.group(1).endswith("000"): master[m.group(1)]=m.group(2)
codes=sorted(master)
# designated city = code followed by ward rows
designated={c for i,c in enumerate(codes) if i+1<len(codes) and master[c].endswith("市") and master[codes[i+1]].endswith("区") and c[:2]!="13"}
ward_of={}
for c in codes:
    if master[c].endswith("区") and c[:2]!="13":
        city=max(d for d in designated if d<c and d[:2]==c[:2]); ward_of[c]=city
zb=get("https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/9112b58e-556c-429e-906f-45be48b63fd9/db7e75fb/20260703_resources_govdashboard_watersupply_table_02.zip")
zf=zipfile.ZipFile(io.BytesIO(zb))
rd=list(csv.DictReader(io.StringIO(zf.read("2024.csv").decode("utf-8-sig"))))
fee=[r for r in rd if r["item_name"].endswith("1か月20㎥当たり料金__口径20mm")]
own=set(); auth={}
for r in fee:
    c=r["local_public_enterprise_code"]
    if r["cond_2_operating_entity"][0] in "234": own.add(c[:5])
    else: auth[c]=(r["local_public_enterprise_name"], r["cond_2_operating_entity"], r["facility_code"], r["item_value"])
pop={r["local_public_enterprise_code"]:r["item_value"] for r in rd if r["item_name"]=="4.施設__(3)現在給水人口(人)"}
print("own", len(own), "not in master", sorted(own-set(master))[:20])
missing=[c for c in codes if c not in own and c not in designated and not (c in ward_of and ward_of[c] in own)]
print("missing", len(missing))
bypref=collections.defaultdict(list)
for c in missing: bypref[c[:2]].append(f"{c}{master[c]}")
for p,v in sorted(bypref.items()): print(p, " ".join(v))
print("\nAUTH")
for c,v in sorted(auth.items()): print(c, v, pop.get(c))
def wiki(t):
    u="https://ja.wikipedia.org/w/api.php?"+urllib.parse.urlencode(dict(action="query",prop="extracts",explaintext=1,titles=t,format="json",redirects=1))
    try:
        j=json.loads(get(u)); p=next(iter(j["query"]["pages"].values())); return p.get("extract","")
    except Exception as e: return f"ERR {e}"
print("\nWIKI")
for c,v in sorted(auth.items()):
    name=v[0]
    if name=="東京都": name="東京都水道局"
    t=wiki(name)
    if not t and "県" in name: t=wiki(name+"企業局")
    lines=[l for l in t.splitlines() if re.search(r"給水区域|構成|構成団体|構成市町|給水対象|事業区域|給水地域", l)]
    print("####", c, name, len(t)); print(t[:400].replace("\n"," / ")); print(" | ".join(lines)[:1500])
