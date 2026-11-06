import subprocess, sys, os, re, io
def sh(c): print("$",c,flush=True); subprocess.run(c,shell=True)
sh("git fetch -q origin claude/new-indicators-1106 && git worktree add -q /tmp/nw FETCH_HEAD")
sh(f"{sys.executable} -m pip install -q --user --break-system-packages -e /tmp/nw/pipeline openpyxl")
import site; sys.path.append(site.getusersitepackages()); sys.path.insert(0,"/tmp/nw/pipeline")
from pathlib import Path
UA="Mozilla/5.0 (data-sanpo probe)"
def get(u): return subprocess.run(["curl","-sSL","-A",UA,"--max-time","300",u],capture_output=True).stdout
def dl(sid,kind=0): return get(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind={kind}")
def sec(t): print("\n==========",t,flush=True)
os.makedirs("/tmp/p",exist_ok=True)
try:
    sec("ssds B")
    from tdm.ingest import ssds_municipal
    Path("/tmp/p/b.xls").write_bytes(dl("000040463585"))
    t=ssds_municipal.read_table(Path("/tmp/p/b.xls"),["B1103"])
    print(len(t), {k:t[k] for k in ["01","13","13101","01101","01100","14131","47382"] if k in t})
except Exception as e: import traceback; traceback.print_exc()
try:
    sec("medical")
    from tdm.ingest import mhlw_medical
    Path("/tmp/p/n1.csv").write_bytes(dl("000040501271",1)); Path("/tmp/p/n2.csv").write_bytes(dl("000040501272",1))
    a=mhlw_medical.read_table(Path("/tmp/p/n1.csv"),7,"病床数"); b=mhlw_medical.read_table(Path("/tmp/p/n2.csv"),8,"病床数")
    print(len(a),len(b), {k:(a.get(k),b.get(k)) for k in ["01","13","13101","13104","01101","14131","47382"]})
    print("missing in b:", sorted(set(a)-set(b))[:10], "missing in a:", sorted(set(b)-set(a))[:10])
except Exception as e: import traceback; traceback.print_exc()
try:
    sec("reduce t9-1a")
    from tdm.fetch import reduce_xlsx
    import tomllib
    cfg=tomllib.load(open("/tmp/nw/pipeline/config/sources.toml","rb"))["economic_census2021_municipal_industry"]
    out=reduce_xlsx(dl("000040067884"), cfg["reduce_xlsx"]).decode()
    lines=out.splitlines(); print(len(lines)); print("\n".join(lines[:5])); print([l for l in lines if l.startswith("0,13104") or "13101" in l][:3])
    print("X cells:", [l for l in lines if ",X" in l or ",x" in l][:5])
except Exception as e: import traceback; traceback.print_exc()
try:
    sec("housing floor")
    import openpyxl, xlrd
    Path("/tmp/p/h.xls").write_bytes(dl("000040463591"))
    hh=ssds_municipal.read_table(Path("/tmp/p/h.xls"),["H1101","H2130"])
    wb=openpyxl.load_workbook(io.BytesIO(dl("000040209844")),read_only=True,data_only=True)
    persons={}
    for r in wb.worksheets[0].iter_rows(min_row=10,values_only=True):
        if r[2]=="0_総数":
            persons[str(r[1]).split("_")[0]]=(r[3],r[9],r[10])  # 住宅数, 世帯人員総数, 主世帯人員
    for k in ["01000","13000","13101","13104","01101","14131","11203"]:
        k5=k if not k.endswith("000") else k[:2]
        print(k, hh.get(k5), persons.get(k))
except Exception as e: import traceback; traceback.print_exc()
try:
    sec("osui pdf")
    Path("/tmp/p/o.pdf").write_bytes(get("https://www.env.go.jp/recycle/jokaso/data/population/pdf/osui-r06.pdf"))
    sh("pdftotext -layout /tmp/p/o.pdf /tmp/p/o.txt; wc -l /tmp/p/o.txt; grep -n '市町村' /tmp/p/o.txt | head -20; sed -n '1,40p' /tmp/p/o.txt")
except Exception as e: import traceback; traceback.print_exc()
