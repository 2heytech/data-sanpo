"""国土数値情報「地価公示データ」（L01、都道府県別の GeoJSON）を取り込む。

形式（L01-26_13 を 2026-10-03 に GitHub Actions から取得し、製品仕様の属性一覧と照合）:
  1地物が1つの標準地（点）。L01_001 市区町村コード、L01_002 用途区分（000 住宅地、005 商業地、
  009 工業地 など）、L01_003 連番、L01_007 公示年、L01_008 当年の価格（円/㎡）、L01_009 前年からの変動率（%）、
  L01_024 市区町村名（例: 千代田）、L01_025 所在地、L01_026 住居表示、L01_027 地積、L01_028 利用現況、
  L01_048 最寄駅、L01_050 駅までの道路距離（m）、L01_051 用途地域。
  L01_062〜L01_105 は 1983年〜公示年の価格の推移（その年に標準地でなかった年は 0）。

標準地の番号は「千代田-1」（住宅地）・「千代田5-1」（商業地）のように市区町村名・用途・連番で呼ぶ。
0 の年は値なし（標準地でなかった）として扱い、0円にしない。価格は1月1日時点。

「都道府県地価調査データ」（L02、L02-25_13 を 2026-10-10 に GitHub Actions から取得して確認）も同じ形で読む。
  L02_001 用途区分、L02_002 連番、L02_005 調査年、L02_006 当年の価格、L02_007 変動率、L02_020 市区町村コード、
  L02_021 市区町村名、L02_022 所在地、L02_024 地積、L02_025 利用現況、L02_044 最寄駅、L02_045 駅までの距離、
  L02_046 用途地域。L02_055〜L02_097 は 1983年〜2025年の価格の推移（基準地でなかった年は 0）。
  価格は7月1日時点。基準地の番号は「千代田(都)-1」「千代田(都)5-1」。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..db import insert_observation, upsert_entity

FIRST_YEAR = 1983
# 地価公示（L01）と都道府県地価調査（L02）の属性名。first_price は 1983年の価格の欄の番号
FIELDS = {
    "L01": {"code": "L01_001", "use": "L01_002", "seq": "L01_003", "year": "L01_007", "change": "L01_009",
            "name": "L01_024", "address": "L01_025", "residential_address": "L01_026", "area": "L01_027",
            "current_use": "L01_028", "station": "L01_048", "distance": "L01_050", "zoning": "L01_051",
            "first_price": 62, "date": "01-01", "id_prefix": "land"},
    "L02": {"code": "L02_020", "use": "L02_001", "seq": "L02_002", "year": "L02_005", "change": "L02_007",
            "name": "L02_021", "address": "L02_022", "residential_address": None, "area": "L02_024",
            "current_use": "L02_025", "station": "L02_044", "distance": "L02_045", "zoning": "L02_046",
            "first_price": 55, "date": "07-01", "id_prefix": "landsv"},
}
PREF_SUFFIX = {"01": "道", "13": "都", "26": "府", "27": "府"}   # 基準地番号の「(都)」など。ほかは「県」
USE_LABELS = {"000": "住宅地", "003": "宅地見込地", "005": "商業地", "007": "準工業地", "009": "工業地",
              "010": "調整区域内宅地", "013": "林地"}


def _fields(props: dict) -> dict:
    return FIELDS["L02" if "L02_001" in props else "L01"]


def point_name(props: dict) -> str:
    f = _fields(props)
    use = str(props[f["use"]])
    prefix = "" if use == "000" else str(int(use))
    survey = ""
    if f is FIELDS["L02"]:
        survey = f"({PREF_SUFFIX.get(str(props[f['code']])[:2], '県')})"
    return f"{props[f['name']]}{survey}{prefix}-{int(props[f['seq']])}"


def price_history(props: dict) -> dict[int, float]:
    """年 → 価格（円/㎡）。その年に標準地（基準地）でなかった年（0）は含めない。"""
    f = _fields(props)
    tag = f["code"][:3]
    year = int(props[f["year"]])
    out = {}
    for y in range(FIRST_YEAR, year + 1):
        v = props.get(f"{tag}_{f['first_price'] + y - FIRST_YEAR:03d}")
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
    for feature in features:
        p = feature["properties"]
        f = _fields(p)
        code = str(p[f["code"]])
        muni = f"muni-{code}"
        if muni not in munis:
            result["no_municipality"] += 1
            continue
        use = str(p[f["use"]])
        entity_id = f"{f['id_prefix']}-{code}-{use}-{int(p[f['seq']]):03d}"
        upsert_entity(conn, entity_id, "land_point", point_name(p), parent_id=muni)
        lon, lat = feature["geometry"]["coordinates"][:2]
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
                "address": _text(p.get(f["address"])),
                "residential_address": _text(p.get(f["residential_address"])) if f["residential_address"] else None,
                "area_m2": p.get(f["area"]) or None, "current_use": _text(p.get(f["current_use"])),
                "station": _text(p.get(f["station"])), "station_distance_m": p.get(f["distance"]),
                "zoning": _text(p.get(f["zoning"])), "change_rate": p.get(f["change"]),
            }, ensure_ascii=False)))
        for y, price in price_history(p).items():
            insert_observation(
                conn, entity_id=entity_id, indicator_id=indicator_id,
                definition_version=definition["definition_version"],
                period_start=f"{y}-{f['date']}", period_end=f"{y}-{f['date']}", period_kind="point",
                value=price, status="observed", source_id=source_id)
            result["observations"] += 1
        result["points"] += 1
    return result
