"""農林水産省「市町村別農業産出額（推計）」の詳細品目別データ（xlsx、1年1ファイル）を取り込む。

形式（令和6年 index-25.xlsx・平成29年 index-14.xlsx を 2026-10-14 に GitHub Actions から取得して確認）:
  1シート（「R6」「平成29年」など）。1行目が見出し「年次, 都道府県コード, 市町村コード, 全国農業地域, 都道府県,
  市町村, 種別, 部門, 品目, 産出額（千万円）, 全国順位, 県内順位」、2行目から1行に1市町村×1品目（約12万行）。
  都道府県コードは "01" のような文字列のことも数値のこともある。市町村コードは3桁の数値（100 は政令指定都市の
  市全体、東京都の 100 は「特別区」＝23区の合計）。値は数値（千万円）か「-」（該当なし）「x」（秘匿）「…」（不詳）。
  都道府県の合計の行はない。

政令指定都市と東京23区は市全体（区部全体）の値しかなく、区に割り振ると元データより細かくなるので、区には値を
入れない（都道府県の合計には含める）。「-」は産出がないので0、「x」は秘匿、「…」は値なし（0にしない）。
都道府県の値は、農林水産省「生産農業所得統計」の都道府県別農業産出額（公表値）を使う（#155。kind
maff_agri_prefecture、ingest_prefectures）。市町村別の推計は都道府県の値を市町村に割り振ったもので、加工農産物などを
含まないため、市町村の合計は公表の都道府県の値と一致しない。都道府県の表がない年だけ、県内の全市町村の合計
（1つでも秘匿・不詳があれば値なし）にする。
指標は definition の agri_item（「品目」の欄の値。例: 農業産出額・米・野菜計・果実計・畜産計）で選ぶ。

生産農業所得統計の都道府県別の表（「都道府県別農業産出額及び生産農業所得 ア 実額」、e-Stat。2017〜2024年の表を
2026-10-22 に取得して確認。2021年以前は旧形式の .xls）:
  1シート。6〜9行目あたりが見出し（「計」「耕種」「畜産」の行、その下に「小計」「米」「野菜」「果実」などの行。
  2021年以前は「耕　　種」「野　菜」のように全角空白が入り、2017年は「耕種（続き）」「畜産（続き）」もある）。
  1列目が都道府県名（「北海道」「青森」…「沖縄」、2021年以前は「北　　海　　道」）、値は億円の整数で、
  産出額と順位の列が交互に並ぶ。「x」は秘匿、「-」は該当なし（0）。年は表の中にないので sources.toml の year を使う。
"""
from __future__ import annotations

import re
import sqlite3
import zipfile
from collections import defaultdict
from pathlib import Path

from ..db import delete_area_observations, insert_observation
from ..regions import PREFECTURES, prefecture_entity_id
from ..xlsx import read_sheet

KIND = "maff_agri_output"
SUPPRESSED = "x"
ZERO = "-"
# 都道府県別の表の列（見出しの文字）→ 市町村別の表の品目（agri_item）
PREFECTURE_ITEMS = {"計": "農業産出額", "米": "米", "野菜": "野菜計", "果実": "果実計", "畜産": "畜産計"}


def _code(pref, muni) -> str:
    return f"{int(float(pref)):02d}{int(float(muni)):03d}"


def read_table(path: Path) -> tuple[int, dict[str, dict[str, float | str]]]:
    """(年, 市町村コード5桁 → 品目 → 千万円 の数値か「x」「…」)。"""
    rows = read_sheet(path)
    head = [str(c).strip() if c is not None else "" for c in rows[0]]
    col = {name: head.index(name) for name in ("年次", "都道府県コード", "市町村コード", "品目")}
    value_col = next(i for i, h in enumerate(head) if h.startswith("産出額"))
    out: dict[str, dict[str, float | str]] = defaultdict(dict)
    year = None
    for r in rows[1:]:
        if len(r) <= value_col or r[col["市町村コード"]] in (None, ""):
            continue
        year = year or int(float(r[col["年次"]]))
        v = r[value_col]
        if isinstance(v, str):
            v = v.strip()
            v = 0.0 if v == ZERO else (SUPPRESSED if v.lower() == SUPPRESSED else "…")
        out[_code(r[col["都道府県コード"]], r[col["市町村コード"]])][str(r[col["品目"]]).strip()] = v
    return year, out


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict) -> dict:
    year, table = read_table(path)
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == KIND}
    munis = {r[0] for r in conn.execute("SELECT entity_id FROM entities WHERE entity_type = 'municipality'")}
    prefs = {r[0] for r in conn.execute("SELECT entity_id FROM entities WHERE entity_type = 'prefecture'")}
    period = dict(period_start=f"{year}-01-01", period_end=f"{year}-12-31", period_kind="calendar_year",
                  source_id=source_id)
    result = {"year": year, "rows": len(table), "prefectures": 0,
              "matched": sum(1 for c in table if f"muni-{c}" in munis),
              "city_only": sorted(c for c in table if f"muni-{c}" not in munis)[:30]}   # 政令指定都市・23区の全体
    for indicator_id, d in targets.items():
        item, scale = d["agri_item"], float(d.get("scale", 1))
        base = dict(indicator_id=indicator_id, definition_version=d["definition_version"], **period)
        totals: dict[str, float | None] = {}
        for code, items in table.items():
            v = items.get(item, "…")
            pref = prefecture_entity_id(code[:2])
            if isinstance(v, float):
                if totals.get(pref, 0.0) is not None:
                    totals[pref] = totals.get(pref, 0.0) + v
            else:
                totals[pref] = None
            entity_id = f"muni-{code}"
            if entity_id not in munis:
                continue   # 政令指定都市・東京23区の全体（区には割り振らない）
            if isinstance(v, float):
                insert_observation(conn, entity_id=entity_id, value=v * scale, status="estimated", **base)
            else:
                insert_observation(conn, entity_id=entity_id, value=None,
                                   status="suppressed" if v == SUPPRESSED else "missing",
                                   method_note="秘匿" if v == SUPPRESSED else None, **base)
        official = _prefectures_from_other_sources(conn, indicator_id, period["period_start"], source_id)
        for pref, total in totals.items():
            if pref not in prefs or pref in official:
                continue   # 生産農業所得統計の都道府県の値があるときは、市町村の合計を作らない
            if total is None:
                insert_observation(conn, entity_id=pref, value=None, status="missing",
                                   method_note="県内に秘匿・不詳の市町村があり合計できないため値なし", **base)
            else:
                insert_observation(conn, entity_id=pref, value=total * scale, status="estimated",
                                   method_note="県内の市町村の合計", **base)
                result["prefectures"] += 1
    return result


def _prefectures_from_other_sources(conn: sqlite3.Connection, indicator_id: str, period_start: str,
                                    source_id: str) -> set[str]:
    return {r[0] for r in conn.execute(
        """SELECT entity_id FROM observations WHERE indicator_id = ? AND period_start = ? AND source_id != ?
           AND entity_id LIKE 'pref-%'""", (indicator_id, period_start, source_id))}


def _norm(v) -> str:
    return re.sub(r"\s", "", str(v)) if v is not None else ""


def _workbook_rows(path: Path) -> list[list]:
    if zipfile.is_zipfile(path) and "xl/workbook.xml" in zipfile.ZipFile(path).namelist():
        return read_sheet(path)
    import xlrd   # 旧形式の Excel（.xls。2021年以前の表）
    sheet = xlrd.open_workbook(str(path)).sheet_by_index(0)
    return [[None if v == "" else v for v in sheet.row_values(i)] for i in range(sheet.nrows)]


def read_prefecture_table(path: Path) -> dict[str, dict[str, float | str]]:
    """生産農業所得統計の都道府県別の表。都道府県コード2桁 → 品目（agri_item）→ 億円 の数値か「x」「…」。"""
    rows = _workbook_rows(path)
    names = {re.sub(r"[都府県]$", "", n) if n != "北海道" else n: c for c, n in PREFECTURES.items()}
    first = next(i for i, r in enumerate(rows) if r and _norm(r[0]) in names)
    head = [[_norm(c) for c in r] for r in rows[:first]]
    cols: dict[str, int] = {}
    for label in PREFECTURE_ITEMS:
        if label == "畜産":
            # 畜産の小計の列（見出しの行に「畜産」、その下の行に「小計」）
            hit = next((j for r_i, r in enumerate(head[:-1]) for j, c in enumerate(r)
                        if c == "畜産" and j < len(head[r_i + 1]) and head[r_i + 1][j] == "小計"), None)
        else:
            hit = next((j for r in head for j, c in enumerate(r) if c == label), None)
        if hit is None:
            raise KeyError(f"{path.name}: 列「{label}」が見つかりません")
        cols[label] = hit
    out: dict[str, dict[str, float | str]] = {}
    for r in rows[first:]:
        code = names.get(_norm(r[0]) if r else "")
        if code is None:
            continue
        items: dict[str, float | str] = {}
        for label, j in cols.items():
            v = r[j] if j < len(r) else None
            if isinstance(v, (int, float)):
                items[PREFECTURE_ITEMS[label]] = float(v)
            else:
                s = _norm(v)
                items[PREFECTURE_ITEMS[label]] = 0.0 if s == ZERO else (SUPPRESSED if s.lower() == SUPPRESSED else "…")
        out[code] = items
    return out


def ingest_prefectures(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict, year: int) -> dict:
    """生産農業所得統計の都道府県別農業産出額（億円）を都道府県の値にする。市町村の推計の合計で作った値は消す。"""
    table = read_prefecture_table(path)
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == KIND}
    prefs = {r[0] for r in conn.execute("SELECT entity_id FROM entities WHERE entity_type = 'prefecture'")}
    period = dict(period_start=f"{year}-01-01", period_end=f"{year}-12-31", period_kind="calendar_year",
                  source_id=source_id)
    result = {"year": year, "prefectures": len(table), "suppressed": 0}
    for indicator_id, d in targets.items():
        delete_area_observations(conn, indicator_id, period["period_start"], keep_source=source_id, levels=("pref",))
        base = dict(indicator_id=indicator_id, definition_version=d["definition_version"], **period)
        for code, items in table.items():
            entity_id = prefecture_entity_id(code)
            if entity_id not in prefs:
                continue
            v = items[d["agri_item"]]
            if isinstance(v, float):
                insert_observation(conn, entity_id=entity_id, value=v, status="observed", **base)
            else:
                result["suppressed"] += 1
                insert_observation(conn, entity_id=entity_id, value=None,
                                   status="suppressed" if v == SUPPRESSED else "missing",
                                   method_note="秘匿" if v == SUPPRESSED else None, **base)
    return result
