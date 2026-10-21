import sys, urllib.request, tempfile, pathlib, json
sys.path.insert(0, "pipeline")
from tdm.ingest import estat_census_municipal as m
UA={"User-Agent":"Mozilla/5.0"}
cols={"昼間人口":"人口/1_従業地・通学地による人口（昼間人口）"}
areas=json.load(open("probe/data/areas.json"))
name={a["id"]:a["name"] for a in areas["municipalities"]}
pname={p["id"]:p["name"] for p in areas["prefectures"]}
for sid,y in (("000032217063","2020"),("000032217186","2015")):
    data=urllib.request.urlopen(urllib.request.Request("https://www.e-stat.go.jp/stat-search/file-download?statInfId=%s&fileKind=0"%sid,headers=UA),timeout=180).read()
    p=pathlib.Path(tempfile.mkdtemp())/"x.xlsx"; p.write_bytes(data)
    day={r["KEY_CODE"]:float(r["昼間人口"]) for r in m.read_table(p, cols, {"男女":"0_総数"}).rows}
    pop={r["entity_id"]:r["value"] for r in json.load(open(f"probe/data/pop{y}.json"))["rows"] if r["value"] is not None}
    old={r["entity_id"]:r for r in json.load(open(f"probe/data/ratio{y}.json"))["rows"]}
    new={}
    for e,r in old.items():
        c=e[5:]
        if c in day and e in pop and pop[e]>=100: new[e]=(day[c]/pop[e]*100, day[c], pop[e])
    print("==",y,"old rows",len(old),"new rows",len(new),"missing",[e for e in old if e not in new and old[e]["value"] is not None][:20])
    diffs=sorted(((abs(new[e][0]-(old[e]["value"] or 0)),e) for e in new if old[e]["value"] is not None),reverse=True)
    print(" changed>0.05:",sum(1 for d,_ in diffs if d>0.05),"max",[(name.get(e),round(d,1)) for d,e in diffs[:8]])
    hi=sorted(new,key=lambda e:-new[e][0]); lo=sorted(new,key=lambda e:new[e][0])
    print(" HIGH",[(e[5:],name.get(e),round(new[e][0],1),old[e]["value"]) for e in hi[:12]])
    print(" LOW",[(e[5:],name.get(e),round(new[e][0],1),old[e]["value"]) for e in lo[:12]])
    pd={};pp={}
    for e,(v,d,q) in new.items():
        k=e[5:7]; pd[k]=pd.get(k,0)+d; pp[k]=pp.get(k,0)+q
    pr={k:pd[k]/pp[k]*100 for k in pd}
    s=sorted(pr,key=lambda k:-pr[k])
    print(" PREF HIGH",[(pname.get("pref-"+k,k),round(pr[k],2)) for k in s[:6]])
    print(" PREF LOW",[(pname.get("pref-"+k,k),round(pr[k],2)) for k in s[-6:]])
