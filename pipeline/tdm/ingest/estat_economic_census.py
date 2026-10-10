"""経済センサス‐活動調査（令和3年6月1日現在）の町丁・大字別の民営事業所数・従業者数を取り込む。

e-Stat 統計GIS の小地域の表 T001167「産業（大分類）別民営事業所数及び男女別従業者数」（都道府県ごとの zip の中の
tblT001167Cxx.txt、cp932 の CSV。2026-10-10 に GitHub Actions から取得して確認）。
  1行目が列コード（KEY_CODE, CITY_NAME, AZA_CODE, AZA_NAME, T001167001, …）、2行目が列名
  （T001167001「AR_全産業（S_公務を除く）」の事業所数、T001167019 が同じ区分の従業者数）。
  KEY_CODE は市区町村コード5桁＋町丁・大字コード12桁。各市区町村の最後に「その他」（町丁・大字が分からない
  事業所）の行がある。「-」は該当なし（0）。2021年の表には秘匿（X）の値はない。

町丁・大字のコードは国勢調査の小地域のコードと体系が違うため、町丁・大字の名前で国勢調査の小地域（地図の境界）に
対応付ける（表記ゆれは犯罪の表と同じ正規化で吸収）。対応できない行（「その他」や名前の違う大字など）は
市区町村の合計にだけ入る。対応できない小地域は値なしにする（0にしない）。市区町村の値は全行の合計。
"""
from __future__ import annotations

import csv
import io
import sqlite3
from collections import defaultdict
from pathlib import Path

from ..db import insert_observation
from .estat_small_area import parse_cell
from .keishicho_crime import normalize_name

KIND = "estat_economic_census"
NO_MATCH_NOTE = "経済センサスの町丁・大字と地図の小地域を名前で対応付けられないため値なし"


def read_rows(path: Path, encoding: str = "cp932") -> tuple[list[str], list[list[str]]]:
    records = list(csv.reader(io.StringIO(path.read_bytes().decode(encoding))))
    return [c.strip() for c in records[0]], [r for r in records[2:] if r and r[0].strip()]


def ingest(conn: sqlite3.Connection, files: list[Path], source_id: str, catalog: dict,
           period: tuple[str, str, str], boundary_version: str, encoding: str = "cp932") -> dict:
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == KIND}
    munis = {r[0] for r in conn.execute("SELECT entity_id FROM entities WHERE entity_type = 'municipality'")}
    areas: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    # 地図に使う最新の境界にある小地域だけ（過去の国勢調査にしかない同じ名前の小地域と取り違えない）
    for r in conn.execute("""SELECT e.entity_id, e.name, e.parent_id FROM entities e
                             JOIN boundaries b ON b.entity_id = e.entity_id AND b.boundary_version = ?
                             WHERE e.entity_type = 'small_area'""", (boundary_version,)):
        areas[r["parent_id"]][normalize_name(r["name"])].append(r["entity_id"])
    result = {"municipalities": 0, "areas": 0, "rows": 0, "unmatched_rows": 0, "unmatched_areas": 0,
              "unmatched_examples": []}
    for path in files:
        labels, rows = read_rows(path, encoding)
        cols = {d["column"]: labels.index(d["column"]) for d in targets.values()}
        name_col = labels.index("AZA_NAME")
        muni_sum: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        area_sum: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for r in rows:
            muni = f"muni-{r[0].strip()[:5]}"
            if muni not in munis:
                continue   # 対象外の都道府県・政令指定都市の市全体など
            result["rows"] += 1
            values = {c: parse_cell(r[j]).value or 0.0 for c, j in cols.items()}   # 秘匿のない表（「-」は0）
            for c, v in values.items():
                muni_sum[muni][c] += v
            ids = areas.get(muni, {}).get(normalize_name(r[name_col]), [])
            if len(ids) != 1:   # 対応なし・同じ名前の小地域が複数（どちらか決められない）
                result["unmatched_rows"] += 1
                if len(result["unmatched_examples"]) < 30 and r[name_col].strip() not in ("", "その他"):
                    result["unmatched_examples"].append(r[1].strip() + r[name_col].strip())
                continue
            for c, v in values.items():
                area_sum[ids[0]][c] += v
        for muni, sums in muni_sum.items():
            for indicator_id, d in targets.items():
                base = dict(indicator_id=indicator_id, definition_version=d["definition_version"],
                            period_start=period[0], period_end=period[1], period_kind=period[2],
                            source_id=source_id)
                insert_observation(conn, entity_id=muni, value=sums[d["column"]], status="observed", **base)
                for ids in areas.get(muni, {}).values():
                    for entity_id in ids:
                        got = area_sum.get(entity_id)
                        if got is not None:
                            insert_observation(conn, entity_id=entity_id, value=got[d["column"]],
                                               status="observed", **base)
                        else:
                            insert_observation(conn, entity_id=entity_id, value=None, status="missing",
                                               method_note=NO_MATCH_NOTE, **base)
            result["municipalities"] += 1
            result["areas"] += sum(1 for ids in areas.get(muni, {}).values() for e in ids if e in area_sum)
            result["unmatched_areas"] += sum(1 for ids in areas.get(muni, {}).values() for e in ids
                                             if e not in area_sum)
    return result
