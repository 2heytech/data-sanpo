import subprocess, sys, os, re, csv, io, zipfile, collections
sh=lambda c: subprocess.run(c,shell=True)
sh("git fetch -q origin claude/new-indicators-1106 && git worktree add -q /tmp/nw FETCH_HEAD")
sys.path.insert(0,"/tmp/nw/pipeline")
from tdm.xlsx import read_sheet
UA="Mozilla/5.0 (data-sanpo probe)"
def get(u): return subprocess.run(["curl","-sSL","-A",UA,"--max-time","300",u],capture_output=True).stdout
open("/tmp/j.xlsx","wb").write(get("https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040479049&fileKind=0"))
rows=read_sheet("/tmp/j.xlsx",0)
head=next(i for i,r in enumerate(rows) if r and str(r[0]).strip()=="団体コード")
lab={f"{rows[head-2][j]}/{rows[head-1][j]}":j for j in range(3,len(rows[head-1])) if rows[head-1][j] is not None}
cj=lab["人口/計"]; pop={}; name={}
for r in rows[head+1:]:
    c=str(r[0] or "").strip()
    if re.fullmatch(r"\d{6}",c): pop[c[:5]]=r[cj]; name[c[:5]]=f"{r[1] or ''}{r[2] or ''}"
print("juki", len(pop))
zb=get("https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/9112b58e-556c-429e-906f-45be48b63fd9/db7e75fb/20260703_resources_govdashboard_watersupply_table_02.zip")
rd=list(csv.DictReader(io.StringIO(zipfile.ZipFile(io.BytesIO(zb)).read("2024.csv").decode("utf-8-sig"))))
fee={}; wp={}; ent={}
for r in rd:
    k=(r["local_public_enterprise_code"], r["facility_code"])
    if r["item_name"].endswith("1か月20㎥当たり料金__口径20mm"): fee[k]=r["item_value"]; ent[k]=(r["local_public_enterprise_name"], r["cond_2_operating_entity"])
    if r["item_name"]=="4.施設__(3)現在給水人口(人)": wp[k]=r["item_value"]
def num(v):
    try: return float(v)
    except: return None
print("\nOWN coverage (own served pop / juki pop)")
by=collections.defaultdict(list)
for (c,f),v in fee.items():
    if ent[(c,f)][1][0] in "234": by[c[:5]].append((f, num(wp.get((c,f))), v))
for m,lst in sorted(by.items()):
    main=[x for x in lst if x[0]=="001"] or [x for x in lst if x[0]=="005"]
    served=sum(x[1] or 0 for x in lst if x[0] in ("001","005"))
    p=pop.get(m)
    ratio = served/p if p else None
    if ratio is None or ratio<0.6 or ratio>1.15: print(m, name.get(m), p, lst, None if ratio is None else round(ratio,2))
CAND={"018457":["01428","01423"],"019097":["01432","01436","01431"],"019623":["01430","01304"],"019895":["01225","01226","01227","01424"],
"028711":["02203","02405","02412","02445","02446","02443","02442"],"038873":["03205","03206","03321"],"049646":["04202","04214"],
"069027":["06302","06305"],"069663":["06212","06341"],"078883":["07541","07542","07543","07544","07545","07546"],"078891":["07209","07561"],
"088412":["08208","08217","08219","08564"],"098329":["09342","09344","09345"],"109193":["10205","10207","10521","10522","10523","10524","10525","10212"],
"118362":["11222","11465"],"118389":["11231","11233"],"118532":["11239","11241"],"119059":["11207","11361","11362","11363","11365"],
"120006":["12203","12204","12227","12224"],"128015":["12205"],"128023":["12329"],"128791":["12235"],"128805":["12213","12239","12403","12409","12410"],
"128821":["12210","12421","12422","12423","12424","12426","12427"],"128911":["12206","12225","12226","12229"],
"140007":["14203","14204","14205","14207","14208","14212","14213","14214","14215","14218","14301","14321","14341","14342","14150"],
"159000":["15213","15342"],"200000":["20521","20218"],"208400":["20217","20323"],"238325":["23235","23427","23425"],"238635":["23234","23342"],
"238732":["23361","23362"],"238902":["23229","23230","23236","23238","23302"],"258211":["25203"],"258601":["25425"],"289086":["28208","28481"],
"289272":["28205","28224","28226"],"298581":["29361","29362","29363"],"358321":["35343","35344"],"409260":["40216","40503"],"409286":["40218","40231"],
"409481":["40206","40604","40605","40610"],"418374":["41210","41327","41341","41345","41346"],"418480":["41204","41206","41209","41423","41424","41425","41211"],
"438715":["43403","43404"],"439754":["43468"],"478016":["47350","47362"],"278688":["27226","27228","27229","27231","27232","27321","27322","27341","27361","27362","27366","27381","27382","27383"],
"378887":["37201","37202","37203","37204","37205","37206","37207","37208","37322","37324","37341","37386","37387","37403","37404","37406"],
"349194":["34203","34204","34208","34209","34210","34212","34213","34214","34215","34307","34369","34431","34462","34545"]}
tok=[c for c in pop if c.startswith("13") and (c<"13200" or c in ("13201","13202","13204","13205","13206","13208","13209","13210","13211","13212","13213","13214","13215","13218","13219","13220","13221","13222","13223","13224","13225","13228","13229","13303","13305","13308"))]
CAND["130001"]=tok
print("\nCAND pop check (authority served / sum juki)")
for a,ms in CAND.items():
    k=(a,"001") if (a,"001") in fee else (a,"005")
    s=sum(pop.get(m,0) or 0 for m in ms)
    print(a, ent[k][0], fee[k], wp.get(k), int(s), round(num(wp.get(k))/s,2) if s else None, [f"{m}{name.get(m,'?')}" for m in ms])
print("\nOWN serving others? (>1.15 above). Specific:")
for m in ["31202","34100","40100","15205","19201","23100","06203","22203","27100"]:
    print(m, name.get(m), pop.get(m), by.get(m))
for m in ["31204","31384","34302","34309","34304","40381","40382","40384","15504","19384","06426","22341","23424","16343"]:
    print("missing", m, name.get(m), pop.get(m))
