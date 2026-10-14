"""文部科学省「学校基本調査」の市町村別集計（e-Stat の xlsx）から、学級と卒業後の状況の指標を取り込む。

形式は中学校の市町村別学年別生徒数（estat_school_basic.py）と同じ作りとみて読む: シートは「全国」と47都道府県
（シート名は都道府県名）。都道府県のシートは上に見出しの行があり、「計」の行（都道府県の合計）のあとに区市町村が
['101', '千代田区', 値, …] と並ぶ。列は見出しの文字で探す（見出しは複数行で、結合セルは左の値を引き継ぐとみなす）。

- 学級（kind = estat_school_classes）: 小学校・中学校の「市町村別編制方式別学級数 計」と「市町村別学級編制方式別
  児童（生徒）数 計」。列は 計・単式学級・複式学級・特別支援学級 などの区分。
  指標: 通常の学級（特別支援学級を除く）1学級あたりの人数、特別支援学級の児童・生徒の割合。
- 卒業後の状況（kind = estat_school_progress）: 高等学校（全日制・定時制）の「市町村別状況別卒業者数 計 計」。
  列は 計（卒業者数）・A大学等進学者・B専修学校（専門課程）進学者・…・E就職者等（自営業主等・無期雇用労働者・
  有期雇用労働者・臨時労働者）・…・A〜Dのうち就職している者、と表に載っている率（大学等進学率など）。
  指標: 卒業者に占める割合（令和7年度の表を 2026-10-14 に GitHub Actions から取得して確認）。
どちらも学校の所在地で数える（住んでいる市区町村ではない）。都道府県の値はシートの「計」の行から出す。
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from ..db import insert_observation
from ..progress import progress
from ..regions import PREFECTURES, municipality_entity_id, prefecture_entity_id
from ..xlsx import read_sheet, sheet_names


def _clean(v) -> str:
    return re.sub(r"\s+", "", str(v)) if v is not None else ""


def read_table(path: Path, pref: str, expect: str = "") -> tuple[list[str], dict[str, list]]:
    """(列の見出し, 地域ID → 行)。見出しは「計」の行より上の行を列ごとにつないだ文字（例: 特別支援学級/計）。
    expect: 1行目の表題に含むはずの語（取り違えたファイルを読まないため）。"""
    name = PREFECTURES[pref]
    if name not in sheet_names(path):
        return [], {}
    rows = read_sheet(path, name)
    title = "".join(_clean(v) for v in (rows[0] if rows else []))
    if expect and expect not in title:
        raise ValueError(f"{path.name} の表題が「{expect}」の表ではありません: {title}")
    start = next((i for i, r in enumerate(rows) if r and _clean(r[0]) == "計"), None)
    if start is None:
        return [], {}
    width = max(len(r) for r in rows)
    # 見出しの空のセルは、左の列と上の段まで同じ区分にいるときだけ左の値を引き継ぐ（横に結合したセル）。
    # 縦に結合したセルの下の空欄は引き継がない
    paths: list[list[str | None]] = [[] for _ in range(width)]
    for r in rows[2:start]:   # 1〜2行目は表題と都道府県名
        for c in range(2, width):
            v = _clean(r[c]) if c < len(r) else ""
            if not v and c > 2 and paths[c - 1][:-1] == paths[c][:len(paths[c - 1]) - 1]:
                v = paths[c - 1][-1] or ""
            paths[c].append(v or None)
    labels = [[] for _ in range(width)]
    for c, path in enumerate(paths):
        for v in path:
            if v and (not labels[c] or labels[c][-1] != v):
                labels[c].append(v)
    heads = ["/".join(parts) for parts in labels]
    out: dict[str, list] = {}
    for r in rows[start:]:
        code = _clean(r[0]) if r else ""
        if code == "計":
            out[prefecture_entity_id(pref)] = r
        elif re.fullmatch(r"\d{3}", code) and code != "999":
            out[municipality_entity_id(pref + code)] = r
    return heads, out


def find_column(heads: list[str], *words: str, exclude: tuple[str, ...] = ()) -> int:
    """見出しにすべての語を含む一番左の列。見つからなければ見出しを添えて止める（形式が変わったとき用）。"""
    for i, h in enumerate(heads):
        if h and all(w in h for w in words) and not any(x in h for x in exclude):
            return i
    raise ValueError(f"学校基本調査の表に列 {words} がありません。見出し: {[(i, h) for i, h in enumerate(heads) if h]}")


def _num(row: list, col: int) -> float | None:
    v = row[col] if col < len(row) else None
    if isinstance(v, (int, float)):
        return float(v)
    s = _clean(v)
    if s in ("-", "－", "‐", "―", "…"):
        return 0.0   # 学校基本調査の「-」は該当なし（0）
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _put(conn, d: dict, indicator_id: str, entity_id: str, num, den, period, source_id: str,
         what: str) -> None:
    obs = dict(entity_id=entity_id, indicator_id=indicator_id, definition_version=d["definition_version"],
               period_start=period[0], period_end=period[1], period_kind=period[2], source_id=source_id,
               denominator_source_id=source_id, numerator=num, denominator=den)
    if num is None or den is None:
        insert_observation(conn, value=None, status="missing", **obs)
    elif den <= 0:
        insert_observation(conn, value=None, status="not_applicable",
                           method_note=f"{what}がないため算出しない", **obs)
    elif den < d.get("min_denominator", 0):
        insert_observation(conn, value=None, status="withheld",
                           method_note=f"{what}が{d['min_denominator']}未満のため非表示", **obs)
    else:
        insert_observation(conn, value=num / den * d.get("scale", 1), status="derived", **obs)


def ingest_classes(conn: sqlite3.Connection, files: list[Path], source_id: str, catalog: dict,
                   period: tuple[str, str, str], prefs: list[str], school: str) -> dict:
    """school: elementary / junior_high。files は classes.xlsx（学級数）と pupils.xlsx（児童・生徒数）。"""
    by = {f.stem: f for f in files}
    if "classes" not in by or "pupils" not in by:
        raise FileNotFoundError(f"学校基本調査の学級のファイルが足りません: {sorted(by)}")
    targets = {k: d for k, d in catalog.items()
               if d.get("source_kind") == "estat_school_classes" and d.get("school_level") == school}
    known = {r[0] for r in conn.execute(
        "SELECT entity_id FROM entities WHERE entity_type IN ('prefecture', 'municipality')")}
    result = {"municipalities": 0, "prefectures": 0, "unmatched": []}
    shown = False
    for pref in prefs:
        c_heads, classes = read_table(by["classes"], pref, "学級数")
        p_heads, pupils = read_table(by["pupils"], pref, "学級編制方式別")
        if not classes or not pupils:
            continue
        if not shown:
            progress(f"  学級数の見出し: {[(i, h) for i, h in enumerate(c_heads) if h][:12]}")
            progress(f"  人数の見出し: {[(i, h) for i, h in enumerate(p_heads) if h][:12]}")
            shown = True
        c_total, c_special = find_column(c_heads, "計"), find_column(c_heads, "特別支援")
        p_total, p_special = find_column(p_heads, "計"), find_column(p_heads, "特別支援")
        for entity_id, crow in classes.items():
            if entity_id not in known:
                result["unmatched"].append(entity_id)
                continue
            prow = pupils.get(entity_id)
            n_cls, n_sp_cls = _num(crow, c_total), _num(crow, c_special)
            n_pup = _num(prow, p_total) if prow else None
            n_sp_pup = _num(prow, p_special) if prow else None
            for indicator_id, d in targets.items():
                if d["class_value"] == "regular_class_size":
                    num = None if n_pup is None or n_sp_pup is None else n_pup - n_sp_pup
                    den = None if n_cls is None or n_sp_cls is None else n_cls - n_sp_cls
                    _put(conn, d, indicator_id, entity_id, num, den, period, source_id, "通常の学級")
                else:   # special_class_share
                    _put(conn, d, indicator_id, entity_id, n_sp_pup, n_pup, period, source_id,
                         "児童・生徒")
            result["prefectures" if entity_id.startswith("pref-") else "municipalities"] += 1
    result["unmatched"] = result["unmatched"][:30]
    return result


# 卒業後の状況の列（見出しに含む語の組）。値は列の合計。就職者は国の「卒業者に占める就職者の割合」と同じく、
# E 就職者等のうち自営業主等・無期雇用労働者・有期雇用のうち雇用契約期間が1年以上かつフルタイム勤務相当の者と、
# A〜D（進学者など）のうち就職している者の同じ区分の合計（臨時労働者と短い有期雇用は含まない）
PROGRESS_COLUMNS = {
    "university": [(("大学等進学者",), ("うち", "率"))],
    "vocational": [(("専修学校", "専門課程", "進学者"), ("率",))],
    "employment": [(("就職者等", "自営業主等"), ()), (("就職者等", "無期雇用"), ()),
                   (("有期雇用労働者のうち", "一年以上"), ()),
                   (("のうち就職している者", "自営業主等"), ()), (("のうち就職している者", "一年以上"), ())],
}
# 表に載っている率（%）。計算した値と照らして、列の取り違えがないかを確かめる
PUBLISHED_RATES = {"university": ("大学等進学率",), "vocational": ("専修学校（専門課程）進学率",),
                   "employment": ("卒業者に占める就職者の割合",)}


def ingest_progress(conn: sqlite3.Connection, files: list[Path], source_id: str, catalog: dict,
                    period: tuple[str, str, str], prefs: list[str]) -> dict:
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "estat_school_progress"}
    known = {r[0] for r in conn.execute(
        "SELECT entity_id FROM entities WHERE entity_type IN ('prefecture', 'municipality')")}
    result = {"municipalities": 0, "prefectures": 0, "unmatched": [], "rate_mismatch": []}
    shown = False
    for pref in prefs:
        heads, table = read_table(files[0], pref, "卒業者数")
        if not table:
            continue
        if not shown:
            progress(f"  卒業後の状況の見出し: {[(i, h) for i, h in enumerate(heads) if h]}")
            shown = True
        total = find_column(heads, "計")
        cols = {k: [find_column(heads, *words, exclude=ex) for words, ex in specs]
                for k, specs in PROGRESS_COLUMNS.items()}
        rates = {k: find_column(heads, *words) for k, words in PUBLISHED_RATES.items()}
        for entity_id, row in table.items():
            if entity_id not in known:
                result["unmatched"].append(entity_id)
                continue
            den = _num(row, total)
            for indicator_id, d in targets.items():
                key = d["progress_value"]
                parts = [_num(row, c) for c in cols[key]]
                num = None if any(v is None for v in parts) else sum(parts)
                published = _num(row, rates[key])
                if num is not None and den and published is not None and abs(num / den * 100 - published) > 0.15:
                    result["rate_mismatch"].append((entity_id, key, round(num / den * 100, 2), published))
                _put(conn, d, indicator_id, entity_id, num, den, period, source_id, "卒業者")
            result["prefectures" if entity_id.startswith("pref-") else "municipalities"] += 1
    result["unmatched"] = result["unmatched"][:30]
    result["rate_mismatch"] = result["rate_mismatch"][:30]
    return result
