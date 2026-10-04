"""国土数値情報「地価公示データ」（L01、都道府県別の GeoJSON）を取り込む。

形式（L01-26_13 を 2026-10-03 に GitHub Actions から取得し、製品仕様の属性一覧と照合）:
  1地物が1つの標準地（点）。L01_001 市区町村コード、L01_002 用途区分（000 住宅地、005 商業地、
  009 工業地 など）、L01_003 連番、L01_007 公示年、L01_008 当年の価格（円/㎡）、L01_009 前年からの変動率（%）、
  L01_024 市区町村名（例: 千代田）、L01_025 所在地、L01_026 住居表示、L01_027 地積、L01_028 利用現況、
  L01_048 最寄駅、L01_050 駅までの道路距離（m）、L01_051 用途地域。
  L01_062〜L01_105 は 1983年〜公示年の価格の推移（その年に標準地でなかった年は 0）。

標準地の番号は「千代田-1」（住宅地）・「千代田5-1」（商業地）のように市区町村名・用途・連番で呼ぶ。
0 の年は値なし（標準地でなかった）として扱い、0円にしない。価格は1月1日時点。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..db import insert_observation, upsert_entity

FIRST_PRICE_FIELD = 62      # L01_062 = 1983年
FIRST_YEAR = 1983
USE_LABELS = {"000": "住宅地", "003": "宅地見込地", "005": "商業地", "007": "準工業地", "009": "工業地",
              "010": "調整区域内宅地", "013": "林地"}


def point_name(props: dict) -> str:
    use = str(props["L01_002"])
    prefix = "" if use == "000" else str(int(use))
    return f"{props['L01_024']}{prefix}-{int(props['L01_003'])}"


def price_history(props: dict) -> dict[int, float]:
    """年 → 価格（円/㎡）。その年に標準地でなかった年（0）は含めない。"""
    year = int(props["L01_007"])
    out = {}
    for y in range(FIRST_YEAR, year + 1):
        v = props.get(f"L01_{FIRST_PRICE_FIELD + y - FIRST_YEAR:03d}")
        if isinstance(v, (int, float)) and v > 0:
            out[y] = float(v)
    return out


def _text(v) -> str | None:
    return None if v in (None, "", "_") else str(v).replace("　", " ").strip()


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, indicator_id: str,
           definition: dict) -> dict:
    features = json.loads(path.read_text(encoding="utf-8"))["features"]
    munis = {r["entity_id"] for r in conn.execute(
        "SELECT entity_id FROM entities WHERE entity_type = 'municipality'")}
    result = {"points": 0, "no_municipality": 0, "observations": 0}
    for f in features:
        p = f["properties"]
        muni = f"muni-{p['L01_001']}"
        if muni not in munis:
            result["no_municipality"] += 1
            continue
        use = str(p["L01_002"])
        entity_id = f"land-{p['L01_001']}-{use}-{int(p['L01_003']):03d}"
        upsert_entity(conn, entity_id, "land_point", point_name(p), parent_id=muni)
        lon, lat = f["geometry"]["coordinates"][:2]
        conn.execute(
            """INSERT INTO locations (location_id, entity_id, role, lon, lat, source_id)
               VALUES (?, ?, 'main', ?, ?, ?)
               ON CONFLICT(location_id) DO UPDATE SET lon = excluded.lon, lat = excluded.lat,
                 source_id = excluded.source_id""",
            (f"{entity_id}:main", entity_id, round(lon, 6), round(lat, 6), source_id))
        conn.execute(
            """INSERT INTO entity_attributes (entity_id, attributes) VALUES (?, ?)
               ON CONFLICT(entity_id) DO UPDATE SET attributes = excluded.attributes""",
            (entity_id, json.dumps({
                "use": use, "use_label": USE_LABELS.get(use, "その他"),
                "address": _text(p.get("L01_025")), "residential_address": _text(p.get("L01_026")),
                "area_m2": p.get("L01_027") or None, "current_use": _text(p.get("L01_028")),
                "station": _text(p.get("L01_048")), "station_distance_m": p.get("L01_050"),
                "zoning": _text(p.get("L01_051")), "change_rate": p.get("L01_009"),
            }, ensure_ascii=False)))
        for y, price in price_history(p).items():
            insert_observation(
                conn, entity_id=entity_id, indicator_id=indicator_id,
                definition_version=definition["definition_version"],
                period_start=f"{y}-01-01", period_end=f"{y}-01-01", period_kind="point",
                value=price, status="observed", source_id=source_id)
            result["observations"] += 1
        result["points"] += 1
    return result
