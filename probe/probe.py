import sys, re, io, ssl, urllib.request, html
from pathlib import Path
sys.path.insert(0, "pipeline")
from tdm import xlsx
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def get(u, ctx=None): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300, context=ctx).read()
def text(h): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style).*?</\1>", " ", h))))
ctx = ssl.create_default_context(); ctx.options |= 0x4  # OP_LEGACY_SERVER_CONNECT
try:
    t = text(get("https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html", ctx).decode("utf-8", "replace"))
    i = t.find("利用規約"); print("TERMS-LEN", len(t))
    for kw in ["商用", "営利", "出典の記載", "政府標準利用規約", "互換", "申請"]:
        for m in list(re.finditer(kw, t))[:2]: print("TERMS", kw, "|", t[max(0, m.start()-200):m.start()+250])
except Exception as e: print("ERR terms", e)
def s(r): return [str(c)[:14] for c in r][:18]
for sid in ("000040174881", "000031976396", "000040052725", "000031693271"):
    try:
        d = get(f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind=0")
        print("##", sid, d[:4])
        if d[:2] != b"PK": print("  not xlsx"); continue
        p = Path(f"{sid}.xlsx"); p.write_bytes(d)
        names = xlsx.sheet_names(p); print("  sheets", names)
        for n in names[:3]:
            rows = xlsx.read_sheet(p, n); print("  --", n, len(rows))
            for r in rows[:14]: print("   ", s(r))
            hits = [r for r in rows if any(str(c).strip() in ("13101", "131016", "千代田区") for c in r[:4] if c is not None)]
            for r in hits[:2]: print("   HIT", s(r))
            pref = [r for r in rows if any(str(c).strip() in ("東京都", "13000") for c in r[:4] if c is not None)]
            for r in pref[:2]: print("   PREF", s(r))
    except Exception as e: print("ERR", sid, e)
