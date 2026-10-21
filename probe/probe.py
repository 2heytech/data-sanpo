import sys, urllib.request, tempfile, pathlib
sys.path.insert(0, "pipeline")
from tdm.ingest import estat_census_municipal as m
UA={"User-Agent":"Mozilla/5.0"}
cols={"昼間人口":"人口/1_従業地・通学地による人口（昼間人口）"}
for sid in ("000032217063","000032217186"):
    data=urllib.request.urlopen(urllib.request.Request("https://www.e-stat.go.jp/stat-search/file-download?statInfId=%s&fileKind=0"%sid,headers=UA),timeout=180).read()
    p=pathlib.Path(tempfile.mkdtemp())/"fusho-hokan-1-1.xlsx"; p.write_bytes(data)
    t=m.read_table(p, cols, {"男女":"0_総数"})
    rows={r["KEY_CODE"]:r["昼間人口"] for r in t.rows}
    print(sid,"rows",len(rows),"prefs",sum(1 for k in rows if len(k)==2))
    for k in ("13","27","11","13101","13104","14100","14101","01100","04404","16321","13219"):
        print(" ",k,rows.get(k))
    bad=[(k,v) for k,v in rows.items() if not str(v).replace(".","").isdigit()]
    print("  non-numeric",len(bad),bad[:10])
