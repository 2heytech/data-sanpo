"""東京都「外国人人口」（住民基本台帳による、各年1月1日現在）表3 区市町村、国籍・地域別外国人人口を取り込む。

形式（平成29〜令和8年、2026-10-03 に GitHub Actions から取得して確認）: UTF-8（BOM付き）のCSV。1行目が列名
（地域階層, 地域コード, 国・地域(人), 総数, 男, 女, アジア, …, 中国, 台湾, …, 韓国, 朝鮮, …）。
「地域階層」4 の行が区市町村。島しょの町村は支庁単位（地域階層 3）でしか載っていないので値なしになる。
末尾に注記の行がある。平成28年以前は「韓国・朝鮮」が1列で、台湾が中国に含まれるため使わない。
"""
from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path

from ..db import insert_observation
from ..regions import municipality_entity_id
from .estat_small_area import parse_cell

MUNICIPALITY_LEVEL = "4"


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict,
           period: tuple[str, str, str], encoding: str = "utf-8-sig") -> dict:
    text = path.read_bytes().decode(encoding)
    rows = list(csv.DictReader(io.StringIO(text)))
    header = {c.strip(): c for c in rows[0] if c}
    targets = {i: d for i, d in catalog.items() if d.get("source_kind") == "tokyo_foreign"}
    # 全国の出典がない古い年だけ東京都の表で補う指標（外国人住民の数: 全国の住民基本台帳は2021年から）
    targets.update({i: {**d, "column": d["tokyo_foreign_column"]} for i, d in catalog.items()
                    if d.get("tokyo_foreign_column") and period[0] < d["tokyo_foreign_before"]})
    missing = [d["column"] for d in targets.values() if d["column"] not in header]
    if missing:
        raise KeyError(f"{path.name}: 列 {missing} が見つかりません")
    n, unmatched = 0, []
    for row in rows:
        if (row.get("地域階層") or "").strip() != MUNICIPALITY_LEVEL:
            continue
        code = (row.get("地域コード") or "").strip()
        entity_id = municipality_entity_id(code)
        if not conn.execute("SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)).fetchone():
            unmatched.append(code)
            continue
        for indicator_id, d in targets.items():
            cell = parse_cell(row[header[d["column"]]])
            insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                               definition_version=d["definition_version"],
                               period_start=period[0], period_end=period[1], period_kind=period[2],
                               value=cell.value, status=cell.status, source_id=source_id)
        n += 1
    return {"rows": n, "unmatched": unmatched}
