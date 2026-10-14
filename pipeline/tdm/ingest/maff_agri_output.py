"""農林水産省「市町村別農業産出額（推計）」の詳細品目別データ（xlsx、1年1ファイル）を取り込む。

形式（令和6年 index-25.xlsx・平成29年 index-14.xlsx を 2026-10-14 に GitHub Actions から取得して確認）:
  1シート（「R6」「平成29年」など）。1行目が見出し「年次, 都道府県コード, 市町村コード, 全国農業地域, 都道府県,
  市町村, 種別, 部門, 品目, 産出額（千万円）, 全国順位, 県内順位」、2行目から1行に1市町村×1品目（約12万行）。
  都道府県コードは "01" のような文字列のことも数値のこともある。市町村コードは3桁の数値（100 は政令指定都市の
  市全体、東京都の 100 は「特別区」＝23区の合計）。値は数値（千万円）か「-」（該当なし）「x」（秘匿）「…」（不詳）。
  都道府県の合計の行はない。

政令指定都市と東京23区は市全体（区部全体）の値しかなく、区に割り振ると元データより細かくなるので、区には値を
入れない（都道府県の合計には含める）。「-」は産出がないので0、「x」は秘匿、「…」は値なし（0にしない）。
都道府県の値は県内の全市町村の合計で、1つでも秘匿・不詳があれば値なしにする。
指標は definition の agri_item（「品目」の欄の値。例: 農業産出額・米・野菜計・果実計・畜産計）で選ぶ。
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path

from ..db import insert_observation
from ..regions import prefecture_entity_id
from ..xlsx import read_sheet

KIND = "maff_agri_output"
SUPPRESSED = "x"
ZERO = "-"


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
        for pref, total in totals.items():
            if pref not in prefs:
                continue
            if total is None:
                insert_observation(conn, entity_id=pref, value=None, status="missing",
                                   method_note="県内に秘匿・不詳の市町村があり合計できないため値なし", **base)
            else:
                insert_observation(conn, entity_id=pref, value=total * scale, status="estimated",
                                   method_note="県内の市町村の合計", **base)
                result["prefectures"] += 1
    return result
