import sys, re, urllib.request, urllib.parse, collections, csv, io
UA = {"User-Agent": "Mozilla/5.0 data-sanpo probe"}
def getb(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
TAG = re.compile(r"<[^>]+>")
def text(h): return re.sub(r"\s+", " ", TAG.sub(" ", h))
def listing(url, n=6):
    print("==== LIST", url)
    out = []
    for page in range(1, n + 1):
        h = getb(url.replace("page=1", f"page={page}")).decode("utf-8", "replace")
        prev = 0; found = 0
        for m in re.finditer(r"statInfId=(\d+)(?:&amp;|&)fileKind=(\d)", h):
            t = text(h[prev:m.start()])
            prev = m.end(); found += 1
            mm = re.findall(r"(\d\d-\d\d-[0-9a-z]+ [^ ]{0,60}(?: [^ ]{0,40})?)", t)
            print(f"  {m.group(1)} k{m.group(2)} :: {(mm[-1] if mm else t[-110:])}")
        if not found:
            print("  (none)", text(h)[:300]); break
for q in ["テーブルデータ 市区町村別", "市区町村別 国籍・地域別 在留外国人"]:
    try: listing(f"https://www.e-stat.go.jp/stat-search/files?page=1&layout=datalist&toukei=00250012&query={urllib.parse.quote(q)}", 6)
    except Exception as e: print("ERR", e)
d = getb("https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040186957&fileKind=0")
print("t2 bytes", len(d), d[:4])
s = None
for enc in ("utf-8-sig", "cp932"):
    try: s = d.decode(enc); print("enc", enc); break
    except Exception: pass
rows = list(csv.reader(io.StringIO(s)))
print("rows", len(rows))
for r in rows[:8]: print("  ", r)
print("ncols", collections.Counter(len(r) for r in rows).most_common(3))
hdr = rows[0]
print("codes sample", collections.Counter(r[0][:2] for r in rows[1:]).most_common(5))
print("n muni", len({r[0] for r in rows[1:]}))
nat = collections.Counter(r[3] for r in rows[1:]); print("nat top", nat.most_common(15))
st = collections.Counter(r[4] for r in rows[1:]); print("status", list(st)[:60])
chi = [r for r in rows[1:] if r[0] == "13101"]
tot = collections.Counter()
for r in chi:
    try: tot[r[3]] += float(r[5])
    except: print("bad", r)
print("chiyoda total", sum(tot.values()), tot.most_common(10))
odd = [r for r in rows[1:] if not re.fullmatch(r"\d{5}", r[0])][:10]; print("odd codes", odd)
print("wards", [r for r in rows[1:] if r[0] in ("01100","01101","14100","27100","27102")][:6])
print("vals", collections.Counter(r[5] for r in rows[1:] if not re.fullmatch(r"[\d.]+", r[5])).most_common(5))
