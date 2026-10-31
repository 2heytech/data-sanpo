"""e-Stat 統計GIS の小地域境界（Shapefile）を取り込む。

同じ KEY_CODE が複数レコードに分かれている場合（飛び地など）は1つの地物にまとめる。
同じ市区町村で同じ名前の町丁・字等が複数の KEY_CODE に分かれている場合（長崎市の大手二丁目など）は、同じ町・大字の
コードか、隣り合っていれば1つの地域にまとめる（docs/design-changes.md #183）。地域IDはいちばん小さい KEY_CODE から作り、
ほかの KEY_CODE は source_keys でその地域に対応付ける（表や集計の行は area_keys で地域に引く）。
水面調査区（HCODE=8154）は地域として扱わない。KEY_CODE が市区町村コードで始まらない地物（名前のない KEY_CODE「42」など）は
町丁・字等にせず、市区町村界にだけ使う。市区町村界は小地域の合成で作る。
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import shapefile  # pyshp
from shapely.geometry import Polygon, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

from ..db import dump_geometry, upsert_entity
from ..regions import (PREFECTURES, municipality_entity_id, prefecture_entity_id, region_of,
                       small_area_entity_id)

WATER_HCODE = 8154


def _polygonal(geom):
    geom = make_valid(geom)
    if geom.geom_type == "GeometryCollection":
        geom = unary_union([g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")])
    return geom


SNAP_DEGREES = 5e-6  # 約0.5m。町丁・字等の間のわずかなすき間を閉じる幅
NEAR_DEGREES = 5e-4  # 約50m。同じ名前の町丁・字等を隣り合うとみなすすき間（細い水路・島の間の橋など）


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


def _same_name_groups(grouped: dict[str, dict], geoms: dict[str, object]) -> dict[str, str]:
    """同じ市区町村・同じ名前の町丁・字等のうち、1つの地域にまとめるもの（KEY_CODE → まとめた地域の KEY_CODE）。

    国勢調査の小地域には、同じ町丁目が複数の KEY_CODE に分かれているものがある（長崎市の大手二丁目は人の住む部分と
    人口0の部分で町のコードが別、夕張市の沼ノ沢は同じ町のコードで名前のない11の区域）。名前では見分けられないので、
    - 同じ町・大字のコード（KEY_CODE の6〜9桁目）なら、離れていても（飛び地・島）まとめる
    - 町・大字のコードが違っても、隣り合っていれば（すき間が約50m以内。長崎市の伊王島と沖之島の伊王島町など）まとめる
    町・大字のコードが違って離れているもの（坂井市の2つの「高柳」など、合併前の別の町の同じ地名）は別の地域のままにする。
    名前のない地域（市区町村名で代用するもの）はまとめない。"""
    by_name: dict[tuple[str, str], list[str]] = defaultdict(list)
    for key, g in grouped.items():
        if g["named"]:
            by_name[(g["city5"], g["name"])].append(key)
    alias: dict[str, str] = {}
    for keys in by_name.values():
        if len(keys) < 2:
            continue
        keys = sorted(keys)
        parent = {k: k for k in keys}

        def find(k: str) -> str:
            while parent[k] != k:
                parent[k] = parent[parent[k]]
                k = parent[k]
            return k

        def join(a: str, b: str) -> None:
            parent[find(b)] = find(a)

        for a, b in zip(keys, keys[1:]):
            if a[5:9] == b[5:9]:   # 並べてあるので、同じ町・大字のコードは続けて並ぶ
                join(a, b)
        for i, a in enumerate(keys):
            aw, as_, ae, an = geoms[a].bounds
            for b in keys[i + 1:]:
                bw, bs, be, bn = geoms[b].bounds
                if find(a) == find(b) or bw - ae > NEAR_DEGREES or aw - be > NEAR_DEGREES \
                        or bs - an > NEAR_DEGREES or as_ - bn > NEAR_DEGREES:
                    continue
                if geoms[a].distance(geoms[b]) <= NEAR_DEGREES:
                    join(a, b)
        for k in keys:
            root = min((m for m in keys if find(m) == find(k)))
            if root != k:
                alias[k] = root
    return alias


@dataclass
class _Records:
    grouped: dict[str, dict]            # KEY_CODE → 市区町村・名前・面積
    geoms: dict[str, object]            # KEY_CODE → 形（飛び地はまとめたもの）
    loose: dict[str, list]              # 町丁・字等にしない地物（市区町村コード5桁 → 形）
    loose_area: dict[str, float]
    skipped_water: int


def _read(shp_path: Path, pref_code: str, encoding: str) -> _Records:
    reader = shapefile.Reader(str(shp_path), encoding=encoding)
    fields = [f[0] for f in reader.fields[1:]]
    grouped: dict[str, dict] = {}
    parts: dict[str, list] = defaultdict(list)
    loose: dict[str, list] = defaultdict(list)
    loose_area: dict[str, float] = defaultdict(float)
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
        if not key.startswith(city5):
            # 名前も町丁・字等のコードもない地物（KEY_CODE が都道府県コードだけ。人口0のわずかな土地や、2010年の
            # 長崎県の所属未定の水面のように市区町村コードが 999 のもの）。いくつもの市区町村にまたがって同じ
            # KEY_CODE なので、1つの町丁・字等にはせず、それぞれの市区町村界にだけ入れる
            loose[city5].append(shape(sr.shape.__geo_interface__))
            loose_area[city5] += float(rec.get("AREA") or 0)
            continue
        parts[key].append(shape(sr.shape.__geo_interface__))
        city_name, designated = _municipality_name(rec)
        g = grouped.setdefault(key, {
            "city5": city5,
            "city_name": city_name,
            "designated": designated,
            "name": _clean(rec.get("S_NAME")) or city_name,
            "named": bool(_clean(rec.get("S_NAME"))),
            "area_m2": 0.0,
        })
        g["area_m2"] += float(rec.get("AREA") or 0)
    geoms = {key: _polygonal(unary_union(ps)) for key, ps in parts.items()}
    return _Records(grouped, geoms, loose, loose_area, skipped_water)


def same_name_alias(shp_path: Path, pref_code: str, encoding: str = "cp932") -> dict[str, str]:
    """境界のファイルで、同じ名前でまとめる町丁・字等（KEY_CODE → まとめた地域の KEY_CODE。_same_name_groups）。"""
    recs = _read(shp_path, pref_code, encoding)
    return _same_name_groups(recs.grouped, recs.geoms)


def ingest(conn: sqlite3.Connection, shp_path: Path, source_id: str, boundary_version: str,
           reference_date: str, encoding: str = "cp932", pref_code: str = "13",
           alias: dict[str, str] | None = None) -> dict:
    """alias: まとめる町丁・字等（same_name_alias）。過去の時点には最新の境界の alias を渡し、最新の地図と同じ
    KEY_CODE をまとめる（過去の時点の名前でまとめると、最新の地図の地域と区域が合わず、過去の値を重ねられなくなる）。
    省くとこのファイルの名前でまとめる。"""
    recs = _read(shp_path, pref_code, encoding)
    grouped, geoms, loose, loose_area = recs.grouped, recs.geoms, recs.loose, recs.loose_area
    if alias is None:
        alias = _same_name_groups(grouped, geoms)
    members: dict[str, list[str]] = defaultdict(list)   # まとめた地域の KEY_CODE → その KEY_CODE（自分を含む）
    for key in sorted(grouped):
        members[alias.get(key, key)].append(key)
    merged = sum(len(keys) - 1 for keys in members.values())

    pref_entity = prefecture_entity_id(pref_code)
    upsert_entity(conn, pref_entity, "prefecture", PREFECTURES.get(pref_code, pref_code))
    muni_geoms: dict[str, list] = defaultdict(list)
    muni_area: dict[str, float] = defaultdict(float)
    for key, keys in members.items():
        g = grouped[keys[0]]   # 過去の時点では、最新の地図でまとめた先の KEY_CODE がないこともある
        muni_id = municipality_entity_id(g["city5"])
        upsert_entity(conn, muni_id, "municipality", g["city_name"], pref_entity,
                      region_of(g["city5"], g["designated"]))
        conn.execute("INSERT OR IGNORE INTO source_keys VALUES (?, ?, ?)",
                     (source_id, g["city5"], muni_id))
        entity_id = small_area_entity_id(key)
        upsert_entity(conn, entity_id, "small_area", g["name"], muni_id)
        for k in keys:
            conn.execute("INSERT OR IGNORE INTO source_keys VALUES (?, ?, ?)",
                         (source_id, k, entity_id))
        geom = geoms[keys[0]] if len(keys) == 1 else _polygonal(unary_union([geoms[k] for k in keys]))
        area = sum(grouped[k]["area_m2"] for k in keys)
        _insert_boundary(conn, boundary_version, entity_id, reference_date, source_id, geom,
                         area or None, "published")
        muni_geoms[muni_id].append(geom)
        muni_area[muni_id] += area

    for city5, shapes in loose.items():
        muni_id = municipality_entity_id(city5)
        if muni_id in muni_geoms:   # 町丁・字等のない市区町村は作らない
            muni_geoms[muni_id].extend(shapes)
            muni_area[muni_id] += loose_area[city5]

    for muni_id, ms in muni_geoms.items():
        _insert_boundary(conn, boundary_version, muni_id, reference_date, source_id,
                         _without_holes(_polygonal(unary_union(ms))), muni_area[muni_id] or None,
                         "computed")

    return {"small_areas": len(members), "merged_same_name": merged,
            "municipalities": len(muni_geoms), "skipped_water": recs.skipped_water}


def area_keys(conn: sqlite3.Connection, boundary_version: str, pref_code: str | None = None) -> dict[str, str]:
    """その時点の境界の KEY_CODE → 町丁・字等の地域ID。同じ名前でまとめた地域（#183）は、まとめた KEY_CODE が
    どれも同じ地域IDになる。国勢調査の表や町丁・字等ごとの集計の行は、これで地域に対応付ける。"""
    row = conn.execute(
        """SELECT source_id FROM boundaries WHERE boundary_version = ? AND entity_id LIKE 'area-%'
           LIMIT 1""", (boundary_version,)).fetchone()
    if row is None:
        return {}
    prefix = f"area-{pref_code or ''}%"
    return {r[0]: r[1] for r in conn.execute(
        "SELECT source_key, entity_id FROM source_keys WHERE source_id = ? AND entity_id LIKE ?",
        (row[0], prefix))}


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
         dump_geometry(geom), area_m2, area_source, west, south, east, north),
    )
