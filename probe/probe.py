import subprocess, sys, tomllib, types, importlib.util, csv, io, zipfile
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
cfg = tomllib.load(open("probe/sources.toml", "rb"))["digital_water_2024"]
r = subprocess.run(["curl", "-sSL", "-A", UA, "--max-time", "300", "-o", "/tmp/w.zip", "-w", "%{http_code} %{size_download}", cfg["download_url"]], capture_output=True, text=True)
print("####", r.stdout)
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", "pipeline"])
sys.path.insert(0, "pipeline")
import tdm.ingest  # noqa
spec = importlib.util.spec_from_file_location("tdm.ingest.digital_water_new", "probe/digital_water_new.py")
dw = importlib.util.module_from_spec(spec); spec.loader.exec_module(dw)
from pathlib import Path
p = Path("/tmp/w.zip")
u = dw.read_table(p, 2024)
prev = dw.read_table(p, 2023, required=False)
hist = {y: dw.read_table(p, y, required=False) for y in range(2014, 2024)}
res = {"missing_fixes": []}
dw._apply_fixes(u, cfg, res)
print("missing_fixes", res["missing_fixes"])
codes = sorted({c for c, _ in u})
sup = set(cfg.get("suppliers", {})) | set(cfg.get("area_tariffs", {}))
floor = float(cfg["low_fee_floor"]); step = float(cfg["min_step"]); checked = cfg.get("low_fees_checked", {})
n = 0
for code in codes:
    m = dw._main(u, code)
    if m is None or "fix" in m:
        continue
    if not (m["entity"] in dw.MUNICIPAL or code in sup):
        continue
    fee, f10 = m["fee"], m.get("fee10")
    stable = prev.get((code, m["facility"]), {}).get("fee") == fee
    sus = fee < floor or (f10 is not None and 0 < fee - f10 < step and not stable)
    if sus or code in checked:
        n += 1
        h = [(y, hist[y].get((code, m["facility"]), {}).get("fee")) for y in range(2014, 2024) if hist[y].get((code, m["facility"]), {}).get("fee")]
        print("FLAG" if code not in checked else "CHECKED", code, m["facility"], m["name"], m["entity"], "f20", fee, "f10", f10, "pop", m.get("population"), "stable", stable, "hist", h[-4:])
print("total", n)
try:
    used = {c: dw._main(u, c) for c in codes if dw._main(u, c) and (dw._main(u, c)["entity"] in dw.MUNICIPAL or c in sup)}
    dw._check_low_fees(used, prev, cfg)
    print("GUARD OK")
except ValueError as e:
    print("GUARD", e)
