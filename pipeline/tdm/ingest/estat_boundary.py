"""e-Stat 統計GIS の小地域境界（Shapefile）を取り込む。

同じ KEY_CODE が複数レコードに分かれている場合（飛び地など）は1つの地物にまとめる。
水面調査区（HCODE=8154）は地域として扱わない。市区町村界は小地域の合成で作る。
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import shapefile  # pyshp
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

from ..db import upsert_entity
from ..regions import (PREFECTURES, municipality_entity_id, prefecture_entity_id, region_of,
                       small_area_entity_id)

WATER_HCODE = 8154


def _polygonal(geom):
    geom = make_valid(geom)
    if geom.geom_type == "GeometryCollection":
        geom = unary_union([g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")])
    return geom


SNAP_DEGREES = 5e-6  # 約0.5m。町丁・字等の間のわずかなすき間を閉じる幅


def _without_holes(geom):
    """区市町村の形を町丁・字等から合成するとき、内側に余計な線が出ないようにする。

    境界のわずかなすき間で分かれた部分は、わずかに膨らませて縮め戻すことでつなぐ。
    すき間や除外した水面調査区が残す穴は埋める（docs/design-changes.md #24）。
    """
    geom = _polygonal(geom.buffer(SNAP_DEGREES, join_style=2).buffer(-SNAP_DEGREES, join_style=2))
    polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    # 穴の中にあった飛び地は、穴を埋めた外形に含まれるのでまとめ直す
    return unary_union([Polygon(p.exterior) for p in polys if p.geom_type == "Polygon"])


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def _municipality_name(rec: dict) -> tuple[str, str | None]:
    """市区町村名と、政令指定都市の区なら市の名前。区の CITY_NAME が「中央区」だけの場合は市の名前を前に付ける。"""
    name, city = _clean(rec.get("CITY_NAME")), _clean(rec.get("GST_NAME")) or None
    if city and city != name and not name.startswith(city):
        name = city + name
    return name, (city if city and city != name else None)


def ingest(conn: sqlite3.Connection, shp_path: Path, source_id: str, boundary_version: str,
           reference_date: str, encoding: str = "cp932", pref_code: str = "13") -> dict:
    reader = shapefile.Reader(str(shp_path), encoding=encoding)
    fields = [f[0] for f in reader.fields[1:]]
    grouped: dict[str, dict] = {}
    parts: dict[str, list] = defaultdict(list)
    skipped_water = 0
    for sr in reader.iterShapeRecords():
        rec = dict(zip(fields, sr.record))
        if _clean(rec.get("PREF")) != pref_code:
            continue
        if int(rec.get("HCODE") or 0) == WATER_HCODE:
            skipped_water += 1
            continue
        key = _clean(rec["KEY_CODE"])
        city5 = pref_code + _clean(rec["CITY"]).zfill(3)
        parts[key].append(shape(sr.shape.__geo_interface__))
        city_name, designated = _municipality_name(rec)
        g = grouped.setdefault(key, {
            "city5": city5,
            "city_name": city_name,
            "designated": designated,
            "name": _clean(rec.get("S_NAME")) or city_name,
            "area_m2": 0.0,
        })
        g["area_m2"] += float(rec.get("AREA") or 0)

    pref_entity = prefecture_entity_id(pref_code)
    upsert_entity(conn, pref_entity, "prefecture", PREFECTURES.get(pref_code, pref_code))
    muni_geoms: dict[str, list] = defaultdict(list)
    muni_area: dict[str, float] = defaultdict(float)
    for key, g in grouped.items():
        muni_id = municipality_entity_id(g["city5"])
        upsert_entity(conn, muni_id, "municipality", g["city_name"], pref_entity,
                      region_of(g["city5"], g["designated"]))
        conn.execute("INSERT OR IGNORE INTO source_keys VALUES (?, ?, ?)",
                     (source_id, g["city5"], muni_id))
        entity_id = small_area_entity_id(key)
        upsert_entity(conn, entity_id, "small_area", g["name"], muni_id)
        conn.execute("INSERT OR IGNORE INTO source_keys VALUES (?, ?, ?)",
                     (source_id, key, entity_id))
        geom = _polygonal(unary_union(parts[key]))
        _insert_boundary(conn, boundary_version, entity_id, reference_date, source_id, geom,
                         g["area_m2"] or None, "published")
        muni_geoms[muni_id].append(geom)
        muni_area[muni_id] += g["area_m2"]

    for muni_id, geoms in muni_geoms.items():
        _insert_boundary(conn, boundary_version, muni_id, reference_date, source_id,
                         _without_holes(_polygonal(unary_union(geoms))), muni_area[muni_id] or None,
                         "computed")

    return {"small_areas": len(grouped), "municipalities": len(muni_geoms),
            "skipped_water": skipped_water}


def _insert_boundary(conn, version, entity_id, reference_date, source_id, geom, area_m2,
                     area_source) -> None:
    west, south, east, north = geom.bounds
    conn.execute(
        """INSERT INTO boundaries (boundary_id, boundary_version, entity_id, reference_date,
                                   source_id, geometry, area_m2, area_m2_source,
                                   bbox_west, bbox_south, bbox_east, bbox_north)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(boundary_id) DO UPDATE SET
             geometry = excluded.geometry, area_m2 = excluded.area_m2,
             source_id = excluded.source_id, bbox_west = excluded.bbox_west,
             bbox_south = excluded.bbox_south, bbox_east = excluded.bbox_east,
             bbox_north = excluded.bbox_north""",
        (f"{version}:{entity_id}", version, entity_id, reference_date, source_id,
         json.dumps(mapping(geom)), area_m2, area_source, west, south, east, north),
    )
