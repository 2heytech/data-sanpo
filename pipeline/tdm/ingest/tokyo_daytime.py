"""東京都「東京都の昼間人口（令和2年国勢調査）」表1（区市町村別の昼間人口）を取り込む。

形式（2026-10-03 に GitHub Actions から取得して確認）: UTF-8（BOM付き）のCSV。1行目が列名で、
「階層」2 の行が区市町村、「地域コード」は団体コード5桁、「昼間人口／総数（人）」が昼間人口。
末尾に注記の行がある。
平成27年（tj15zv0100.csv）は列名が「地域階層」、平成22年（tj10zv0100.csv）は階層の列がなく、
区部・市部などの行も同じ並びにある（区市町村の地域だけを使う）。昼間人口の列名は3回とも同じ。
"""
from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path

from ..db import insert_observation
from ..regions import municipality_entity_id
from .estat_small_area import parse_cell

MUNICIPALITY_LEVEL = "2"


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, indicator_id: str,
           definition: dict, period: tuple[str, str, str], encoding: str = "utf-8-sig") -> dict:
    text = path.read_bytes().decode(encoding)
    rows = list(csv.DictReader(io.StringIO(text)))
    column = next(c for c in rows[0] if c and c.strip() == definition["column"])
    level_col = next((c for c in ("階層", "地域階層") if c in rows[0]), None)
    n, unmatched = 0, []
    for row in rows:
        if level_col and (row.get(level_col) or "").strip() != MUNICIPALITY_LEVEL:
            continue
        code = (row.get("地域コード") or "").strip()
        entity_id = municipality_entity_id(code)
        if not conn.execute("SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)).fetchone():
            if level_col:
                unmatched.append(code)
            continue   # 階層の列がない表では、総数・区部・市部などの行
        cell = parse_cell(row[column])
        insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                           definition_version=definition["definition_version"],
                           period_start=period[0], period_end=period[1], period_kind=period[2],
                           value=cell.value, status=cell.status, source_id=source_id)
        n += 1
    return {"rows": n, "unmatched": unmatched}
