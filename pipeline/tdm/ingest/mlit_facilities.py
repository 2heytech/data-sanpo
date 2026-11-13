"""国土数値情報の「学校」（P29）から、東京都以外の公立小中学校の位置を取り込む。

形式（P29-23 の都道府県別 GeoJSON、2026-10-05 に GitHub Actions から取得して確認）:
  P29（学校、2023年度）: 1地物が1校（点）。P29_001 市区町村コード、P29_002 学校コード（例: B102210000017）、
    P29_003 学校分類（16001 小学校、16002 中学校、16014 義務教育学校 など）、P29_004 名称、P29_005 所在地
    （都道府県名から）、P29_006 管理者（1 国、2 都道府県、3 市区町村、4 私立）、P29_007 休校区分
    （ほぼすべて 1。青森県では 394校のうち1校が 9）。

児童・生徒数はないので、位置だけの点として載せる（値は作らない。0 にもしない）。学校ごとの人数を公開している
道県・市の学校は、あとで school_counts.py が人数を付ける（#138）。
東京都は東京都教育委員会の一覧（児童・生徒数あり）を使うので、この出典からは取り込まない
（sources.toml の exclude_prefectures）。
保育所の位置は、以前は国土数値情報「福祉施設データ」（P14）を使っていたが、ここdeサーチの全国の一覧
（kokode_nurseries.py）に置き換えた（#138）。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from shapely.geometry import Point

from ..db import upsert_entity
from .mlit_stations import _municipality_index, _municipality_of

SCHOOL_TYPES = {"16001": ("elementary", "小学校"), "16002": ("junior_high", "中学校"),
                "16014": ("compulsory", "義務教育学校")}
PUBLIC_FOUNDERS = {"2": "都道府県立", "3": "市区町村立"}
SCHOOL_OPEN = {"0", "1"}     # 休校区分。これ以外（9 など）は載せない


def _features(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["features"]


def _locate(conn, code: str | None, lon: float, lat: float, munis: set[str], index) -> str | None:
    """市区町村は元データのコードで決め、境界にない（合併などで変わった）ときは位置から決める。"""
    if code and f"muni-{code}" in munis:
        return f"muni-{code}"
    if index is None:
        return None
    return _municipality_of(Point(lon, lat), *index)


def _put(conn, entity_id: str, entity_type: str, name: str, muni: str, lon: float, lat: float,
         source_id: str, attrs: dict) -> None:
    upsert_entity(conn, entity_id, entity_type, name, parent_id=muni)
    conn.execute(
        """INSERT INTO locations (location_id, entity_id, role, lon, lat, source_id)
           VALUES (?, ?, 'main', ?, ?, ?)
           ON CONFLICT(location_id) DO UPDATE SET lon = excluded.lon, lat = excluded.lat,
             source_id = excluded.source_id""",
        (f"{entity_id}:main", entity_id, round(lon, 6), round(lat, 6), source_id))
    conn.execute(
        """INSERT INTO entity_attributes (entity_id, attributes) VALUES (?, ?)
           ON CONFLICT(entity_id) DO UPDATE SET attributes = excluded.attributes""",
        (entity_id, json.dumps(attrs, ensure_ascii=False)))


def _context(conn, boundary_version: str, prefs: list[str]):
    munis = {r["entity_id"] for r in conn.execute(
        "SELECT entity_id FROM entities WHERE entity_type = 'municipality'")}
    return munis, _municipality_index(conn, boundary_version, prefs)


def ingest_schools(conn: sqlite3.Connection, files: list[Path], source_id: str, boundary_version: str,
                   prefs: list[str], as_of: str) -> dict:
    """公立（都道府県立・市区町村立）の小学校・中学校・義務教育学校。"""
    munis, index = _context(conn, boundary_version, prefs)
    result = {"schools": 0, "closed": 0, "no_municipality": 0}
    for path in files:
        for f in _features(path):
            p = f["properties"]
            kind = SCHOOL_TYPES.get(str(p.get("P29_003")))
            founder = PUBLIC_FOUNDERS.get(str(p.get("P29_006")))
            if not kind or not founder:
                continue
            if str(p.get("P29_007")) not in SCHOOL_OPEN:
                result["closed"] += 1
                continue
            lon, lat = f["geometry"]["coordinates"][:2]
            muni = _locate(conn, p.get("P29_001"), lon, lat, munis, index)
            if muni is None:
                result["no_municipality"] += 1
                continue
            _put(conn, f"school-{p['P29_002']}", "school", p["P29_004"], muni, lon, lat, source_id,
                 {"school_type": kind[0], "type_label": kind[1], "founder": founder,
                  "address": p.get("P29_005"), "location_only": True, "as_of": as_of})
            result["schools"] += 1
    return result
