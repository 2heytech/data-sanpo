"""都道府県警察の「犯罪発生情報」（犯罪オープンデータ、窃盗7手口）を取り込む。

警察庁の「犯罪オープンデータ リンク集」（https://www.npa.go.jp/toukei/seianki/hanzaiopendatalink.html）から
たどれる各都道府県警察の公開ファイル。7手口（ひったくり・車上ねらい・部品ねらい・自動販売機ねらい・自動車盗・
オートバイ盗・自転車盗）の年計を、手口ごと・年ごとに1件1行の CSV で公開している（警察庁が示した共通の様式）。
  列の例（警視庁 tokyo_2024zitensyatou.csv）: 罪名, 手口, 管轄警察署（発生地）, 管轄交番・駐在所（発生地）,
  市区町村コード（発生地）, 都道府県（発生地）, 市区町村（発生地）, 町丁目（発生地）, 発生年月日（始期）, …
  文字コードは cp932 が多く、UTF-8（BOM つき）の県もある。列名は県・年で少し違うので「市区町村コード」
  「市区町村」「町丁目」を含む列を探す。

元ファイルは sources.toml の download_files で「<年>_<手口>.csv」の名前にそろえて保存する（手口はファイル名の
ローマ字: hittakuri, syazyounerai, buhinnerai, zidouhanbaikinerai, zidousyatou, ootobaitou, zitensyatou）。

数え方（docs/design-changes.md #93）:
- 市区町村: 年ごとに件数を数える（市区町村コード、なければ名前で対応付け）。その年・その手口のファイルがあれば、
  行のない市区町村は0件。7手口の合計は、その年の7つのファイルがそろった都道府県だけ。
- 町丁目: 全国の町丁目まで年ごとに出すとファイル数が多すぎるので、直近5年の合計だけを作る（5年分のファイルが
  そろった都道府県だけ）。町丁目の名前で地図の小地域に対応付ける（経済センサスと同じ正規化。「大字」「字」は除く）。
  元データが丁目まで分けていて地図が分けていない町は町にまとめる。地図のほうが細かい町（元データ「本町」、
  地図「本町１丁目」…）は割り振らずに値なしにする。町丁目が空の行・対応できない行は市区町村の値にだけ入る。
  地図に省かれた旧町村名（甲賀市「水口町本町」→地図「本町」など）は末尾の一致で対応付ける。
  行のない町丁目は0件。ただし対応できない行と町丁目が空の行が市区町村の件数の5%を超える市区町村は、行のない
  町丁目を値なしにする（0件なのか名前が合わないだけなのか決められないため）。この判断は7手口の合計で行い、
  手口別の指標にも同じ判断を使う。
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from ..db import insert_observation
from ..xlsx import read_sheet
from .estat_economic_census import CHOME, town_key as _town_key

KIND = "police_crime_opendata"
# 手口（ファイル名のローマ字）→ 表示名。順番は画面の並び
TECHNIQUES = {
    "zitensyatou": "自転車盗", "ootobaitou": "オートバイ盗", "zidousyatou": "自動車盗",
    "syazyounerai": "車上ねらい", "buhinnerai": "部品ねらい", "zidouhanbaikinerai": "自動販売機ねらい",
    "hittakuri": "ひったくり",
}
TOTAL = "total"
FILE_NAME = re.compile(r"(\d{4})_([a-z]+)\.(csv|zip|xlsx)$")
UNMATCHED_LIMIT = 0.05
UNCERTAIN_NOTE = "警察の公開データの町丁目名と地図の町丁目を対応付けられない件数が多いため値なし"
FINER_NOTE = "警察の公開データは地図より大きな単位（町・大字）で、この町丁目に割り振れないため値なし"
NO_FILE_NOTE = "警察の公開データにこの年・この手口のファイルがないため値なし"
ZERO_NOTE = "警察の公開データに発生の記録がないため0件"


# 地図（国勢調査の町丁・字名）と警察の公開データで字体が違う字
VARIANTS = str.maketrans({"濤": "涛", "檜": "桧", "籠": "篭", "舘": "館", "槇": "槙", "藪": "薮"})
# 地図の町名から省かれている旧町村名・地区名（甲賀市「水口町本町」→地図「本町」、千代田区「神田猿楽町」→地図「猿楽町」）
OLD_PREFIX = re.compile(r"(町|村|神田)$")


def town_key(name: str) -> str:
    s = _town_key(name).translate(VARIANTS)
    s = re.sub(r"(丁目)+", "丁目", s)   # 「中町4丁目丁目」のような重なり
    return re.sub(r"^(大字|字)", "", s)


def _rows(data: bytes) -> list[list[str]]:
    """CSV を行に分ける。タブ区切りの県・年（大阪府など）もあるので、最初の行で区切り文字を決める。"""
    text = _decode(data)
    first = text.split("\n", 1)[0]
    return list(csv.reader(io.StringIO(text), delimiter="\t" if first.count("\t") > first.count(",") else ","))


def _area_ids(areas: dict[str, list[str]], key: str) -> list[str]:
    """町丁目の照合キーから地図の小地域を探す。完全一致→丁目を除いた町→旧町村名を除いた名前の順。"""
    ids = areas.get(key, [])
    if not ids and CHOME.search(key):
        ids = areas.get(CHOME.sub("", key), [])   # 地図では丁目に分かれていない町
    if ids:
        return ids
    # 地図の名前が警察の名前の末尾と一致し、前に残る部分が旧町村名に見えるとき（いちばん長い一致を使う）
    best = [k for k in areas if len(k) >= 2 and key.endswith(k) and OLD_PREFIX.search(key[:-len(k)])]
    if best:
        longest = max(len(k) for k in best)
        found = [k for k in best if len(k) == longest]
        if len(found) == 1:
            return areas[found[0]]
    return []


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp932"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("cp932", errors="replace")


def _norm(cell: str) -> str:
    return re.sub(r"\s", "", unicodedata.normalize("NFKC", cell or ""))


def read_incidents(data: bytes) -> list[tuple[str, str, str, int]]:
    """CSV の各行を (市区町村コード5桁, 市区町村名, 町丁目名, 件数) にする。件数の列がなければ1行1件。"""
    if not data.strip():
        return []   # 発生なし
    rows = _rows(data)
    at = next((i for i, r in enumerate(rows[:10]) if any("市区町村" in _norm(c) for c in r)), None)
    if at is None:
        raise ValueError("市区町村の列が見つかりません")
    head = [_norm(c) for c in rows[at]]

    def col(test) -> int | None:
        return next((j for j, h in enumerate(head) if test(h)), None)

    c_code = col(lambda h: "市区町村コード" in h)
    c_muni = col(lambda h: "市区町村" in h and "コード" not in h)
    c_town = col(lambda h: "町丁目" in h)
    c_count = col(lambda h: h in ("件数", "認知件数"))
    out = []
    for r in rows[at + 1:]:
        if not any(c.strip() for c in r):
            continue
        get = (lambda j: r[j].strip() if j is not None and j < len(r) else "")
        code = re.sub(r"\D", "", unicodedata.normalize("NFKC", get(c_code)))
        n = int(re.sub(r"\D", "", get(c_count)) or 0) if c_count is not None else 1
        out.append((code[:5] if len(code) >= 5 else "", _norm(get(c_muni)), get(c_town), n))
    return out


def detect_technique(data: bytes) -> str | None:
    """「手口」の列でいちばん多い手口（ファイル名の手口と中身が違う県があるため、中身を優先する）。"""
    if not data.strip():
        return None
    rows = _rows(data)
    at = next((i for i, r in enumerate(rows[:10]) if any(_norm(c) == "手口" for c in r)), None)
    if at is None:
        return None
    j = next(k for k, c in enumerate(rows[at]) if _norm(c) == "手口")
    seen = Counter(_norm(r[j]) for r in rows[at + 1:] if j < len(r) and r[j].strip())
    for label, _ in seen.most_common():
        for key, ja in TECHNIQUES.items():
            if label == ja or label.replace("ねらい", "狙い") == ja.replace("ねらい", "狙い"):
                return key
    return None


def _files_by_year(files: list[Path]) -> dict[int, dict[str, bytes]]:
    """{年: {手口: CSV の中身}}。ZIP は中の CSV を手口ごとに読む（ファイル名に手口のローマ字か日本語がある前提）。"""
    out: dict[int, dict[str, bytes]] = defaultdict(dict)
    for f in files:
        m = FILE_NAME.search(f.name)
        if not m:
            continue
        year, tech = int(m.group(1)), m.group(2)
        data = f.read_bytes()
        if f.suffix == ".xlsx":
            # Excel で公開している年（秋田県の2024年など）は、1枚目のシートを CSV と同じ形にして読む
            buf = io.StringIO()
            csv.writer(buf).writerows([["" if c is None else str(c) for c in r] for r in read_sheet(f)])
            out[year][tech] = buf.getvalue().encode("utf-8")
        elif data[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for name in z.namelist():
                    if not name.lower().endswith(".csv"):
                        continue
                    label = unicodedata.normalize("NFKC", name)
                    for key, ja in TECHNIQUES.items():
                        if (key in label.lower() or ja in label) and (tech == "all" or tech == key):
                            out[year][key] = z.read(name)
        elif tech in TECHNIQUES:
            found = detect_technique(data) or tech
            if found in out[year]:
                print(f"{f.name}: {year}年の{TECHNIQUES[found]}のファイルが2つあるため、後のファイルは使いません",
                      file=sys.stderr)
                continue
            out[year][found] = data
    return out


def ingest(conn: sqlite3.Connection, files: list[Path], source_id: str, catalog: dict, pref: str,
           years: list[int], boundary_version: str, no_incident: list[str] | None = None) -> dict:
    """no_incident: 発生がなくファイルを公開していない年・手口（「2023_hittakuri」の形。ページに「発生なし」と
    書かれているものだけ）。その年・手口は全市区町村0件とする。"""
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == KIND}
    munis = {r["entity_id"]: r["name"] for r in conn.execute(
        "SELECT entity_id, name FROM entities WHERE entity_type = 'municipality' AND entity_id LIKE ?",
        (f"muni-{pref}%",))}
    if not munis:
        return {"municipalities": 0}
    by_name = {_norm(n): e for e, n in munis.items()}
    areas: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for r in conn.execute("""SELECT e.entity_id, e.name, e.parent_id FROM entities e
                             JOIN boundaries b ON b.entity_id = e.entity_id AND b.boundary_version = ?
                             WHERE e.entity_type = 'small_area' AND e.entity_id LIKE ?""",
                          (boundary_version, f"area-{pref}%")):
        areas[r["parent_id"]][town_key(r["name"])].append(r["entity_id"])

    raw = _files_by_year(files)
    for item in no_incident or []:
        y, _, t = item.partition("_")
        raw[int(y)].setdefault(t, b"")
    # counts[(年, 手口)][市区町村ID][町丁目の照合キー] = 件数
    counts: dict[tuple[int, str], dict[str, Counter]] = {}
    result = {"municipalities": len(munis), "years": {}, "skipped_rows": 0, "unmatched_rows": 0,
              "located_rows": 0, "blank_rows": 0, "uncertain_municipalities": 0, "areas": 0, "unmatched_examples": []}
    for year in years:
        got = raw.get(year, {})
        result["years"][year] = sorted(got)
        for tech, data in got.items():
            per_muni: dict[str, Counter] = defaultdict(Counter)
            try:
                incidents = read_incidents(data)
            except (ValueError, UnicodeError) as e:
                result.setdefault("errors", []).append(f"{year}_{tech}: {e}")   # そのファイルは値なし
                continue
            for code, muni_name, town, n in incidents:
                muni = f"muni-{code}" if f"muni-{code}" in munis else by_name.get(muni_name)
                if muni is None:
                    result["skipped_rows"] += n   # 他県・市区町村が分からない行（政令指定都市の市全体のコードなど）
                    continue
                per_muni[muni][town_key(town) if town else ""] += n
            counts[(year, tech)] = per_muni

    def merged(year: int, tech: str) -> dict[str, Counter] | None:
        if tech != TOTAL:
            return counts.get((year, tech))
        if not all((year, t) in counts for t in TECHNIQUES):
            return None
        out: dict[str, Counter] = defaultdict(Counter)
        for t in TECHNIQUES:
            for muni, c in counts[(year, t)].items():
                out[muni].update(c)
        return out

    # 町丁目を値なしにするかは7手口の合計で市区町村ごとに決め、手口別の指標にも同じ判断を使う
    # （件数の少ない手口で1件合わないだけで値なしになり、手口ごとに地図の塗りがばらつかないように）
    muni_too_many: dict[str, bool] = {}
    for indicator_id, d in sorted(targets.items(), key=lambda kv: kv[1]["technique"] != TOTAL):
        tech = d["technique"]
        five: dict[str, Counter] | None = defaultdict(Counter)
        for year in years:
            per_muni = merged(year, tech)
            base = dict(indicator_id=indicator_id, definition_version=d["definition_version"],
                        period_start=f"{year}-01-01", period_end=f"{year}-12-31",
                        period_kind="calendar_year", source_id=source_id)
            for muni in munis:
                if per_muni is None:
                    insert_observation(conn, entity_id=muni, value=None, status="missing",
                                       method_note=NO_FILE_NOTE, **base)
                    continue
                total = sum(per_muni.get(muni, Counter()).values())
                insert_observation(conn, entity_id=muni, value=float(total), status="observed",
                                   coverage_note=None if total else ZERO_NOTE, **base)
            if per_muni is None:
                five = None
            elif five is not None:
                for muni, c in per_muni.items():
                    five[muni].update(c)
        if five is None:
            continue   # 5年分がそろわない都道府県は町丁目の値を作らない
        base = dict(indicator_id=indicator_id, definition_version=d["definition_version"],
                    period_start=f"{years[0]}-01-01", period_end=f"{years[-1]}-12-31",
                    period_kind="multi_year", source_id=source_id,
                    method_note=f"{years[0]}〜{years[-1]}年の{len(years)}年分の合計")
        count_stats = tech == TOTAL or len(targets) == 1
        unmatched_names: Counter = Counter()
        uncertain_munis: list[str] = []
        for muni in munis:
            c = five.get(muni, Counter())
            sums: Counter = Counter()
            uncertain: set[str] = set()
            unmatched = 0
            for key, n in c.items():
                if not key:
                    continue   # 町丁目が空（市区町村の値にだけ入る）
                ids = _area_ids(areas[muni], key)
                if len(ids) == 1:
                    sums[ids[0]] += n
                    continue
                unmatched += n
                # 地図のほうが細かい町（「本町」に対して地図の「本町1丁目」…）は割り振らずに値なしにする
                finer = ids or [e for k, es in areas[muni].items() if k.startswith(key) for e in es]
                uncertain.update(finer)
                if count_stats and not finer:
                    unmatched_names[munis[muni] + key] += n
            located = sum(n for k, n in c.items() if k)
            blank = c.get("", 0)
            # 町丁目が空の行も、どの町丁目か分からない件数なので対応できない行と合わせて数える
            too_many = unmatched + blank > (located + blank) * UNMATCHED_LIMIT
            if tech == TOTAL:
                muni_too_many[muni] = too_many
            elif muni in muni_too_many:
                too_many = muni_too_many[muni]
            if count_stats:
                result["located_rows"] += located
                result["unmatched_rows"] += unmatched
                result["blank_rows"] += blank
                result["uncertain_municipalities"] += bool(too_many)
                if too_many:
                    uncertain_munis.append(f"{munis[muni]}（対応できない{unmatched}・空{blank}／{located + blank}）")
            for ids in areas[muni].values():
                for entity_id in ids:
                    if entity_id in uncertain:
                        insert_observation(conn, entity_id=entity_id, value=None, status="missing",
                                           **{**base, "method_note": FINER_NOTE})
                    elif entity_id in sums:
                        insert_observation(conn, entity_id=entity_id, value=float(sums[entity_id]),
                                           status="observed", **base)
                    elif too_many:
                        insert_observation(conn, entity_id=entity_id, value=None, status="missing",
                                           **{**base, "method_note": UNCERTAIN_NOTE})
                    else:
                        insert_observation(conn, entity_id=entity_id, value=0.0, status="observed",
                                           coverage_note=ZERO_NOTE, **base)
                        continue
                    if count_stats and entity_id in sums:
                        result["areas"] += 1
        if count_stats:
            # 照合の改善に使う手がかり（件数の多い順）
            result["unmatched_examples"] = [f"{k}:{n}" for k, n in unmatched_names.most_common(30)]
            result["uncertain_examples"] = uncertain_munis[:30]
    return result
