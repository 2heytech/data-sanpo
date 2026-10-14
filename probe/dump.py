import urllib.request, sys, io, zipfile
UA = {"User-Agent": "Mozilla/5.0"}
for sid in sys.argv[1:]:
    b = urllib.request.urlopen(urllib.request.Request(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind=1", headers=UA) if sid.startswith(("0000315", "0000131")) else urllib.request.Request(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind=0", headers=UA), timeout=120).read()
    print("==", sid, len(b), b[:4], flush=True)
    if b[:2] == b"PK" and b"xl/" in b[:2000] or b[:2] == b"PK":
        try:
            import openpyxl
        except ImportError:
            import subprocess; subprocess.run([sys.executable, "-m", "pip", "install", "-q", "openpyxl"]); import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True)
        for ws in wb.worksheets[:1]:
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i < 14:
                    print(i, [c for c in row[:40]], flush=True)
                elif any(str(c or "").startswith("0_") for c in row[2:5]) and any(str(c or "").startswith("00_") for c in row[3:6]):
                    n = globals().setdefault("n", 0); globals()["n"] = n + 1
                    if n < 6 or str(row[2] or "").startswith(("13101", "13")) and n < 60: print(i, row[:30], flush=True)
            print("rows", i)
    else:
        for enc in ("cp932", "utf-8"):
            try: t = b.decode(enc); break
            except Exception: pass
        for i, line in enumerate(t.splitlines()):
            if i < 22 or (",13101," in line or ",13000," in line or ",13100," in line) and i < 3000: print(i, line[:700])
        print("lines", i)
