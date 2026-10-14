"""経済構造実態調査（製造業事業所調査）「地域別」統計表データの参考表（市区町村別）を取り込む。

形式（2022・2023・2024年［参考値］・2025年調査の xlsx を 2026-10-14 に GitHub Actions から取得して確認）:
  シート「参考表」（市区町村別統計表、産業中分類別）。10行目が見出し「時間軸コード, 年次, 市区町村コード,
  市区町村名, 産業中分類コード, 産業中分類名, …」、8行目に項目名（事業所数・従業者数・…・製造品出荷額等・
  粗付加価値額。事業所数は合計・従業者30〜299人・300人以上の3列）、10行目に単位（人・万円）。1列目は空。産業中分類コード「00」が製造業計。
  市区町村コードは2桁が全国（00）と都道府県、5桁が市区町村。政令指定都市は市全体（01100 など）と区の両方、
  東京都は「東京特別区」（13100）と各区の両方がある。年次は経理事項の年（2025年調査なら2024年の1年間）。
  値は数値か「X」（事業所が1・2の秘匿）「***」（該当なし）。

市区町村は区の行を使い、市全体・特別区全体の行は使わない（地図の単位は区）。都道府県は都道府県の行を使う。
「X」は秘匿（0にしない）、「***」は製造業の事業所がないので0。対象は個人経営を除く事業所。
指標は definition の meti_item（8行目の項目名）で選ぶ。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..db import insert_observation
from ..regions import prefecture_entity_id
from ..xlsx import read_sheet

KIND = "meti_manufacturing"
SHEET = "参考表"
TOTAL = "00"


def _text(c) -> str:
    if c is None:
        return ""
    if isinstance(c, float) and c.is_integer():
        return str(int(c))
    return str(c).strip()


def read_table(path: Path) -> tuple[int, dict[str, dict[str, float | None]]]:
    """(年, 地域コード → 項目名 → 値（秘匿は None）)。"""
    rows = read_sheet(path, SHEET)
    at = next(i for i, r in enumerate(rows) if "市区町村コード" in [_text(c) for c in r])
    head = [_text(c) for c in rows[at]]
    code_col, ind_col, year_col = (head.index("市区町村コード"), head.index("産業中分類コード"), head.index("年次"))
    items: dict[str, int] = {}
    for i, c in enumerate(rows[at - 2]):   # 項目名の行。事業所数は「合計」の列（最初の列）を使う
        if _text(c):
            items.setdefault(_text(c), i)
    out: dict[str, dict[str, float | None]] = {}
    year = None
    for r in rows[at + 1:]:
        if len(r) <= ind_col or _text(r[ind_col]).zfill(2) != TOTAL:
            continue
        code = _text(r[code_col])
        if not code:
            continue
        year = year or int(_text(r[year_col]))
        vals = {}
        for name, j in items.items():
            v = r[j] if j < len(r) else None
            if isinstance(v, float):
                vals[name] = v
            elif _text(v) == "***":
                vals[name] = 0.0
            else:
                vals[name] = None   # X（秘匿）
        out[code.zfill(2) if len(code) <= 2 else code.zfill(5)] = vals
    return year, out


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict) -> dict:
    year, table = read_table(path)
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == KIND}
    known = {r[0] for r in conn.execute(
        "SELECT entity_id FROM entities WHERE entity_type IN ('municipality', 'prefecture')")}
    result = {"year": year, "rows": len(table), "matched": 0, "suppressed": 0, "unmatched": []}
    for code, vals in table.items():
        entity_id = prefecture_entity_id(code) if len(code) == 2 else f"muni-{code}"
        if entity_id not in known:
            if len(code) == 5 and not code.endswith("100"):
                result["unmatched"].append(code)
            continue   # 全国・政令指定都市の市全体・東京特別区全体・この公開版で扱っていない地域
        result["matched"] += 1
        for indicator_id, d in targets.items():
            v = vals.get(d["meti_item"])
            base = dict(entity_id=entity_id, indicator_id=indicator_id, definition_version=d["definition_version"],
                        period_start=f"{year}-01-01", period_end=f"{year}-12-31", period_kind="calendar_year",
                        source_id=source_id)
            if v is None:
                result["suppressed"] += 1
                insert_observation(conn, value=None, status="suppressed",
                                   method_note="製造業の事業所が1・2のため秘匿", **base)
            else:
                insert_observation(conn, value=v * float(d.get("scale", 1)), status="observed", **base)
    result["unmatched"] = result["unmatched"][:30]
    return result
