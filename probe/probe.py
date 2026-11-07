import subprocess, sys, os
def sh(c): print("$",c,flush=True); subprocess.run(c,shell=True)
sh("git fetch -q origin claude/new-indicators-1106 && git worktree add -q /tmp/nw FETCH_HEAD")
sh(f"{sys.executable} -m pip install -q --user --break-system-packages -e /tmp/nw/pipeline")
import site; sys.path.append(site.getusersitepackages()); sys.path.insert(0,"/tmp/nw/pipeline")
from pathlib import Path
UA="Mozilla/5.0 (data-sanpo probe)"
def get(u): return subprocess.run(["curl","-sSL","-A",UA,"--max-time","300",u],capture_output=True).stdout
os.makedirs("/tmp/p",exist_ok=True)
import traceback
from tdm.db import connect, init_schema, upsert_entity, upsert_indicators
from tdm.config import load_sources, load_indicators
from tdm.sources import register_source
from tdm.ingest import ssds_municipal, estat_housing, mhlw_medical
conn=connect("/tmp/p/t.db"); init_schema(conn)
cat=load_indicators(); upsert_indicators(conn,cat); src=load_sources()
for e,t in [("pref-13","prefecture"),("pref-01","prefecture"),("muni-13101","municipality"),("muni-13104","municipality"),("muni-01101","municipality"),("muni-14131","municipality"),("muni-47382","municipality"),("muni-13364","municipality")]:
    upsert_entity(conn,e,t,e)
for key,fn in [("ssds_municipal_2026_b","b.xls"),("ssds_municipal_2026_h","h.xls"),("housing_members_2023","m.xlsx")]:
    try:
        print("\n==",key,flush=True)
        p=Path("/tmp/p")/fn; p.write_bytes(get(src[key]["download_url"]))
        sid=register_source(conn,key,src[key],[p])
        per=(src[key]["period"],src[key]["period"],"point")
        r=(ssds_municipal.ingest if "ssds" in key else estat_housing.ingest_members)(conn,p,sid,cat,per)
        print(r)
    except Exception: traceback.print_exc()
try:
    print("\n== medical",flush=True)
    fs=[]
    for n,u in src["mhlw_medical_2025"]["download_files"].items():
        p=Path("/tmp/p")/n; p.write_bytes(get(u)); fs.append(p)
    sid=register_source(conn,"mhlw_medical_2025",src["mhlw_medical_2025"],fs)
    print(mhlw_medical.ingest(conn,fs,sid,cat,("2025-10-01","2025-10-01","point")))
except Exception: traceback.print_exc()
for r in conn.execute("select indicator_id, entity_id, value, status from observations order by indicator_id, entity_id"):
    print(tuple(r))
