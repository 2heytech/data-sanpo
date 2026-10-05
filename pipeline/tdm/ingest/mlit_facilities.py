"""国土数値情報の「学校」（P29）と「福祉施設」（P14）から、東京都以外の公立小中学校と認可保育所の位置を取り込む。

形式（P29-23・P14-23 の都道府県別 GeoJSON、2026-10-05 に GitHub Actions から取得して確認）:
  P29（学校、2023年度）: 1地物が1校（点）。P29_001 市区町村コード、P29_002 学校コード（例: B102210000017）、
    P29_003 学校分類（16001 小学校、16002 中学校、16014 義務教育学校 など）、P29_004 名称、P29_005 所在地
    （都道府県名から）、P29_006 管理者（1 国、2 都道府県、3 市区町村、4 私立）、P29_007 休校区分
    （ほぼすべて 1。青森県では 394校のうち1校が 9）。
  P14（福祉施設、2023年度）: 1地物が1施設（点）。P14_001 都道府県名、P14_002 市区町村名、P14_003 市区町村コード、
    P14_004 所在地（市区町村名より後）、P14_007 小分類（050401 保育所）、P14_008 名称、P14_009 管理者、
    P14_010 位置の精度。定員はない。

どちらも児童・生徒数や定員はないので、東京都以外は位置だけを載せる（値は作らない。0 にもしない）。
東京都は東京都教育委員会・東京都福祉局の一覧（児童・生徒数・定員あり）を使うので、この出典からは取り込まない
（sources.toml の exclude_prefectures）。

福祉施設は自治体ごとに利用条件があり、保育施設を商用利用不可・公開不可とする自治体がある
（国土数値情報「福祉施設データ 利用規約」R5_Terms_of_Use_WelfareInstitution.xlsx）。sources.toml の
exclude_codes（市区町村コードの先頭）に当たる施設は取り込まない。include_codes はその中の例外
（例: 北海道の所管は除くが、自ら所管する函館市・旭川市は含める）（docs/design-changes.md #71）。
"""
from __future__ import annotations

import hashlib
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
NURSERY_CLASS = "050401"     # 保育所


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


def _matches(code: str, prefixes: list[str]) -> bool:
    return any(code.startswith(x) for x in prefixes)


def ingest_nurseries(conn: sqlite3.Connection, files: list[Path], source_id: str, boundary_version: str,
                     prefs: list[str], as_of: str, exclude: list[str], include: list[str]) -> dict:
    munis, index = _context(conn, boundary_version, prefs)
    result = {"nurseries": 0, "excluded_by_terms": 0, "no_municipality": 0}
    for path in files:
        for f in _features(path):
            p = f["properties"]
            if p.get("P14_007") != NURSERY_CLASS:
                continue
            code = str(p.get("P14_003") or "")
            if _matches(code, exclude) and not _matches(code, include):
                result["excluded_by_terms"] += 1
                continue
            lon, lat = f["geometry"]["coordinates"][:2]
            muni = _locate(conn, code, lon, lat, munis, index)
            if muni is None:
                result["no_municipality"] += 1
                continue
            address = f"{p.get('P14_001') or ''}{p.get('P14_002') or ''}{p.get('P14_004') or ''}"
            digest = hashlib.sha1(f"{p['P14_008']}|{address}".encode()).hexdigest()[:10]
            _put(conn, f"nursery-{muni.removeprefix('muni-')}-{digest}", "nursery", p["P14_008"], muni,
                 lon, lat, source_id, {"founder": "", "address": address, "location_only": True,
                                       "as_of": as_of})
            result["nurseries"] += 1
    return result
