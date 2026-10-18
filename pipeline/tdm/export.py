"""SQLite から公開用の JSON・GeoJSON を生成する（設計書 第9章）。

出力先: <data>/releases/<release_id>/ 。版付きのパスで配信し、manifest.json に
全ファイルの hash を記録する。再配布できない出典（redistributable=0）の値・境界は出力しない。
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
import subprocess
from collections import defaultdict
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.ops import unary_union
from shapely.strtree import STRtree

from . import SCHEMA_VERSION
from .breaks import FINE_CLASSES, diverging_breaks, national_breaks, nice_breaks, quantile_breaks
from .db import load_geometry, now_iso
from .progress import progress
from .regions import PREFECTURES, prefecture_entity_id, prefecture_of

# 容量の目安（設計書 第9章）。超えたら分割の見直しや PMTiles 化を検討する（design-changes P2）
WORKERS_FILE_LIMIT = 25 * 1024 * 1024        # Workers Static Assets の1ファイル上限（超過は公開不可）
INITIAL_LOAD_TARGET = 1 * 1024 * 1024        # 初回表示に読むファイルの圧縮後合計
AREA_LOAD_TARGET = 3 * 1024 * 1024           # 1区市町村の町丁目を開くときの圧縮後合計
# Workers 無料枠は1版2万ファイル。ページ（区市町村・指標ごと、約2千）の分を残して公開版のファイル数を抑える（#52）
FILE_COUNT_WARN = 16_000
FILE_COUNT_LIMIT = 18_000

MUNI_TOLERANCE = 0.0003   # 約30m。都道府県ごとの区市町村界（拡大したとき）
NATION_TOLERANCE = 0.002  # 約200m。全国の区市町村界（初回表示・広域表示用、design-changes #52）
NATION_DIGITS = 3         # 約100m
PREF_TOLERANCE = 0.004    # 約400m。都道府県界（全国を見渡すときだけ表示する）
PREF_MIN_PART_AREA = 1e-5  # 約0.1km²。都道府県界では、これより小さな島は描かない
AREA_TOLERANCE = 0.00002  # 約2m。町丁・字等の表示用
COORD_DIGITS = 5          # 約1m

# 値のファイル名: 都道府県・区市町村は全国で1つずつ、町丁・字等は都道府県ごと（<都道府県2桁>.json）
LEVELS = {"prefecture": "prefectures", "municipality": "municipalities"}
LEVEL_ORDER = ("prefecture", "municipality", "small_area")


def _round_coords(obj, digits=COORD_DIGITS):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(float(x), digits) for x in obj]
        return [_round_coords(o, digits) for o in obj]
    return obj


def _simplified(geom, tolerance: float, digits: int = COORD_DIGITS) -> dict:
    simple = geom.simplify(tolerance, preserve_topology=True)
    if simple.is_empty:
        simple = geom
    g = mapping(simple)
    return {"type": g["type"], "coordinates": _round_coords(g["coordinates"], digits)}


def _prefecture_outline(geom) -> MultiPolygon:
    """全国を見渡すとき用の都道府県の形。区市町村の形を合わせると、境の細いすき間や水面が数千の穴になり
    （全国で14MB）、そのままでは初回表示が重いので、穴と小さな島を除いてから簡略化する。"""
    polygons = [Polygon(p.exterior) for p in getattr(geom, "geoms", [geom]) if p.geom_type == "Polygon"]
    kept = [p for p in polygons if p.area >= PREF_MIN_PART_AREA] or polygons
    return MultiPolygon(kept).simplify(PREF_TOLERANCE, preserve_topology=True)


def _neighbors(shapes: dict[str, object]) -> dict[str, list[str]]:
    """境界が接する区市町村（全国で約1,900あるので空間索引で候補を絞る）。"""
    ids = list(shapes)
    geoms = [shapes[i] for i in ids]
    tree = STRtree(geoms)
    out: dict[str, list[str]] = defaultdict(list)
    for i, a in enumerate(ids):
        grown = geoms[i].buffer(0.0002)
        for j in tree.query(grown):
            j = int(j)
            if j > i and grown.intersects(geoms[j]):
                out[a].append(ids[j])
                out[ids[j]].append(a)
    return out


def _code(entity_id: str) -> str:
    return entity_id.split("-", 1)[1]


def _write(out: Path, rel: str, data) -> None:
    path = out / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _location_only(info: dict, ok_sources: set[str]) -> list:
    """値がなく位置だけを載せる点（東京都以外の学校・保育所。国土数値情報には人数・定員がない）。"""
    return [e for e in info.values()
            if e["lon"] is not None and e["loc_source"] in ok_sources
            and json.loads(e["attributes"] or "{}").get("location_only")]


def _write_places(out: Path, indicator_id: str, meta: dict, key: str, items: list[dict]) -> None:
    """点の一覧を都道府県ごとのファイル（places/<指標>/<都道府県>.json）に分けて書き、places/<指標>.json には
    共通の情報（名前・時点・出典など）と、都道府県ごとの件数と範囲（bbox: 西・南・東・北）を書く。
    全国では1ファイルが大きくなるので、地図は表示している範囲の都道府県のファイルだけを読む（docs/design-changes.md #71）。"""
    by_pref: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_pref[prefecture_of(it["municipality_id"])].append(it)
    prefs = {}
    for pref, lst in sorted(by_pref.items()):
        coords = [it["coord"] for it in lst if it.get("coord")]
        bbox = ([min(c[0] for c in coords), min(c[1] for c in coords),
                 max(c[0] for c in coords), max(c[1] for c in coords)] if coords else None)
        prefs[pref] = {"count": len(lst), "bbox": bbox}
        located_only = sum(1 for it in lst if it.get("location_only"))
        if located_only:
            prefs[pref]["location_only"] = located_only   # 値がなく位置だけの点の数
        _write(out, f"places/{indicator_id}/{pref}.json", {
            "schema_version": meta["schema_version"], "release_id": meta["release_id"],
            "indicator_id": indicator_id, "prefecture": pref, key: lst})
    _write(out, f"places/{indicator_id}.json", {**meta, "prefectures": prefs})


def _coord(e) -> list[float]:
    """位置（経度・緯度）を公開用の桁に丸める。"""
    return [round(e["lon"], COORD_DIGITS), round(e["lat"], COORD_DIGITS)]


def _places_meta(release_id: str, indicator_id: str, d: dict, periods: list[tuple], source_ids: set[str]) -> dict:
    """点の一覧（駅・学校・地価・保育所・空港・港）のファイルに共通の情報: 指標の名前・説明・時点・出典。"""
    return {"schema_version": SCHEMA_VERSION, "release_id": release_id,
            "indicator_id": indicator_id, "name": d["name"], "unit": d["unit"],
            "description": d["description"], "method": d["method"], "caveats": d.get("caveats", []),
            "periods": [{"period": p[0], "period_end": p[1], "period_kind": p[2],
                         "label": _period_label(*p)} for p in periods],
            "source_ids": sorted(source_ids)}


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _fine_classes(classes: int, count: int) -> int:
    """市区町村・町丁目の区分の数（#145）。全時点の値が少ない指標（東京都だけの街路樹など）は、
    1区分に平均20個ほどの値が入るまで減らす（indicators.toml の classes より少なくはしない）。"""
    return max(classes, min(FINE_CLASSES, count // 20))


def _period_id(start: str, end: str, kind: str) -> str:
    """公開データでの時点のID。複数年の合計は「2021-2025」（同じ開始日の年計と区別する）。"""
    return f"{start[:4]}-{end[:4]}" if kind == "multi_year" else start


def _period_label(start: str, end: str, kind: str) -> str:
    y, m, d = (int(x) for x in start.split("-"))
    if kind == "multi_year":
        return f"{y}〜{end[:4]}年の合計"
    if kind == "point":
        return f"{y}年{m}月{d}日現在"
    if kind == "fiscal_year":
        return f"{y}年度"
    if kind == "calendar_year":
        return f"{y}年"
    ey, em, _ = (int(x) for x in end.split("-"))
    return f"{y}年{m}月〜{ey}年{em}月"


COMPARABLE_AREA_DIFF = 0.05  # 過去の境界と面積の差がこれ以内なら同じ地域として重ねる


def comparable_areas(conn: sqlite3.Connection, old_version: str, new_version: str) -> set[str]:
    """過去の境界（old_version）と最新の境界で、同じ地域IDかつ面積がほぼ同じ町丁・字等。"""
    rows = conn.execute(
        """SELECT n.entity_id, o.area_m2 AS old_area, n.area_m2 AS new_area
           FROM boundaries n
           JOIN boundaries o ON o.entity_id = n.entity_id AND o.boundary_version = ?
           JOIN entities e ON e.entity_id = n.entity_id AND e.entity_type = 'small_area'
           WHERE n.boundary_version = ?""", (old_version, new_version)).fetchall()
    return {r["entity_id"] for r in rows
            if r["old_area"] and r["new_area"]
            and abs(r["old_area"] - r["new_area"]) / r["new_area"] <= COMPARABLE_AREA_DIFF}


def export_release(conn: sqlite3.Connection, catalog: dict[str, dict], out_root: Path,
                   release_id: str, censuses: list[dict], note: str | None = None,
                   raw: Path | None = None) -> Path:
    """censuses は古い順。最後の時点の境界で地図を作り、過去の時点の値はそこへ重ねる。
    raw は元ファイルの場所（土地利用図のタイルをそのまま公開版に入れるため）。"""
    boundary_version = censuses[-1]["boundary_version"]
    past = {c["period"]: c for c in censuses[:-1]}
    comparable = {period: comparable_areas(conn, c["boundary_version"], boundary_version)
                  for period, c in past.items()}
    out = out_root / release_id
    if out.exists():
        raise FileExistsError(f"{out} は既にあります。公開版は上書きしません")
    out.mkdir(parents=True)
    ok_sources = {r["source_id"] for r in conn.execute(
        "SELECT source_id FROM sources WHERE redistributable = 1")}

    muni_rows = conn.execute(
        """SELECT e.entity_id, e.name, e.region, b.geometry, b.source_id,
                  b.bbox_west, b.bbox_south, b.bbox_east, b.bbox_north
           FROM entities e JOIN boundaries b ON b.entity_id = e.entity_id
           WHERE e.entity_type = 'municipality' AND b.boundary_version = ?
           ORDER BY e.entity_id""", (boundary_version,)).fetchall()
    muni_rows = [r for r in muni_rows if r["source_id"] in ok_sources]
    # 町丁・字等の形は全国で大きいので、ここでは読まず区市町村ごとに読む
    area_rows = conn.execute(
        """SELECT e.entity_id, e.name, e.parent_id, b.source_id,
                  b.bbox_west, b.bbox_south, b.bbox_east, b.bbox_north
           FROM entities e JOIN boundaries b ON b.entity_id = e.entity_id
           WHERE e.entity_type = 'small_area' AND b.boundary_version = ?
           ORDER BY e.entity_id""", (boundary_version,)).fetchall()
    area_rows = [r for r in area_rows if r["source_id"] in ok_sources]
    muni_names = {r["entity_id"]: r["name"] for r in muni_rows}

    # --- 境界 ---------------------------------------------------------------
    muni_shapes = {r["entity_id"]: load_geometry(r["geometry"]) for r in muni_rows}
    neighbors = _neighbors(muni_shapes)
    pref_names = {r["entity_id"]: r["name"] for r in conn.execute(
        "SELECT entity_id, name FROM entities WHERE entity_type = 'prefecture'")}

    # 区市町村界: 全国を粗く1ファイル（最初に読む）と、都道府県ごとに細かく（拡大したときに読む）
    bdir = f"boundaries/{boundary_version}"
    _write(out, f"{bdir}/municipalities.geojson", {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {"id": r["entity_id"], "name": r["name"]},
                      "geometry": _simplified(muni_shapes[r["entity_id"]], NATION_TOLERANCE, NATION_DIGITS)}
                     for r in muni_rows]})
    munis_by_pref: dict[str, list] = defaultdict(list)
    for r in muni_rows:
        munis_by_pref[prefecture_of(r["entity_id"])].append(r)
    for pref, rows in munis_by_pref.items():
        _write(out, f"{bdir}/municipalities/{pref}.geojson", {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {"id": r["entity_id"], "name": r["name"]},
                          "geometry": _simplified(muni_shapes[r["entity_id"]], MUNI_TOLERANCE)} for r in rows]})
    # 都道府県界: 区市町村の形を合わせて作る（縮小したときに都道府県の値で色分けする。#52）
    pref_shapes = {pref: unary_union([muni_shapes[r["entity_id"]] for r in rows])
                   for pref, rows in munis_by_pref.items()}
    _write(out, f"{bdir}/prefectures.geojson", {
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"id": prefecture_entity_id(pref),
                                     "name": pref_names.get(prefecture_entity_id(pref), PREFECTURES.get(pref, pref))},
                      "geometry": _round_coords(mapping(_prefecture_outline(g)), NATION_DIGITS)}
                     for pref, g in sorted(pref_shapes.items())]})
    by_muni: dict[str, list] = defaultdict(list)
    for r in area_rows:
        by_muni[r["parent_id"]].append(r)
    # 町丁・字等は区市町村ごとに1ファイル。名前・範囲・代表点も各地物の properties に入れ、
    # 地図・ページはこの1ファイルだけを読む（以前は areas/<区市町村>.json に分けていた。ファイル数の節約、#112）
    def bbox(r):
        return [round(r["bbox_west"], 5), round(r["bbox_south"], 5),
                round(r["bbox_east"], 5), round(r["bbox_north"], 5)]

    for muni_id, rows in by_muni.items():
        geoms = {eid: load_geometry(g) for eid, g in conn.execute(
            """SELECT b.entity_id, b.geometry FROM boundaries b
               JOIN entities e ON e.entity_id = b.entity_id
               WHERE e.parent_id = ? AND e.entity_type = 'small_area' AND b.boundary_version = ?""",
            (muni_id, boundary_version))}
        features = []
        for r in rows:
            g = geoms[r["entity_id"]]
            p = g.representative_point()
            features.append({"type": "Feature",
                             "properties": {"id": r["entity_id"], "name": r["name"], "bbox": bbox(r),
                                            "center": [round(p.x, 5), round(p.y, 5)]},
                             "geometry": _simplified(g, AREA_TOLERANCE)})
        _write(out, f"{bdir}/{_code(muni_id)}.geojson", {
            "type": "FeatureCollection", "municipality_id": muni_id, "features": features})

    # --- 地域一覧・検索索引 ----------------------------------------------------

    def pref_bbox(rows):
        return [min(r["bbox_west"] for r in rows), min(r["bbox_south"] for r in rows),
                max(r["bbox_east"] for r in rows), max(r["bbox_north"] for r in rows)]

    _write(out, "areas.json", {
        "schema_version": SCHEMA_VERSION, "release_id": release_id,
        "boundary_version": boundary_version,
        "prefectures": [{
            "id": prefecture_entity_id(pref), "code": pref,
            "name": pref_names.get(prefecture_entity_id(pref), PREFECTURES.get(pref, pref)),
            "bbox": [round(v, 5) for v in pref_bbox(rows)],
            "center": [round(c, 5) for c in pref_shapes[pref].representative_point().coords[0]],
            "municipality_count": len(rows),
        } for pref, rows in sorted(munis_by_pref.items())],
        "municipalities": [{
            "id": r["entity_id"], "name": r["name"], "prefecture": prefecture_of(r["entity_id"]),
            "region": r["region"], "bbox": bbox(r),
            "center": [round(c, 5) for c in muni_shapes[r["entity_id"]].representative_point().coords[0]],
            "neighbors": sorted(neighbors.get(r["entity_id"], [])),
            "small_area_count": len(by_muni.get(r["entity_id"], [])),
        } for r in muni_rows]})
    # 検索索引: 区市町村は全国を1ファイル、町丁・字等は都道府県ごと（全国で約22万あるため）
    def muni_context(r):
        pref = pref_names.get(prefecture_entity_id(prefecture_of(r["entity_id"])), "")
        return pref if not r["region"] or r["region"] in pref else f"{pref} {r['region']}"

    _write(out, "search-index.json", {
        "schema_version": SCHEMA_VERSION,
        "fields": ["id", "name", "context", "level"],
        "entries": [[prefecture_entity_id(pref), pref_names.get(prefecture_entity_id(pref), PREFECTURES.get(pref, pref)),
                     "", "prefecture"] for pref in sorted(munis_by_pref)]
                   + [[r["entity_id"], r["name"], muni_context(r), "municipality"] for r in muni_rows]})
    areas_by_pref: dict[str, list] = defaultdict(list)
    for r in area_rows:
        areas_by_pref[prefecture_of(r["entity_id"])].append(r)
    for pref, rows in areas_by_pref.items():
        _write(out, f"search-index/{pref}.json", {
            "schema_version": SCHEMA_VERSION,
            "fields": ["id", "name", "context", "level"],
            "entries": [[r["entity_id"], r["name"], muni_names.get(r["parent_id"], ""), "small_area"]
                        for r in rows]})

    # --- 指標値 ---------------------------------------------------------------
    exported_entities = {r["entity_id"]: "municipality" for r in muni_rows}
    exported_entities.update({r["entity_id"]: "small_area" for r in area_rows})
    exported_entities.update({prefecture_entity_id(p): "prefecture" for p in munis_by_pref})
    indicator_out = []
    used_sources: set[str] = set()
    progress("境界・地域一覧を書き出した")
    for indicator_id, d in catalog.items():
        if d.get("publish") is False:
            continue   # 率の分母に使うだけの指標（画面には出さない）
        progress(f"書き出し: {indicator_id}")
        obs = conn.execute(
            """SELECT entity_id, period_start, period_end, period_kind, value, numerator,
                      denominator, status, source_id, denominator_source_id, coverage_note,
                      method_note
               FROM observations
               WHERE indicator_id = ? AND definition_version = ? AND dimension_key = 'all'""",
            (indicator_id, d["definition_version"])).fetchall()
        periods: dict[tuple, dict] = {}
        covered: set[str] = set()  # 値のある都道府県（東京都だけの指標を画面で示すため）
        # annual_levels: 年ごとの時点で書き出す単位（全国の町丁目まで年ごとに出すとファイル数が多すぎる指標は、
        # 町丁目を複数年の合計だけにする。#98）
        annual_levels = set(d.get("annual_levels", LEVEL_ORDER))
        for o in obs:
            level = exported_entities.get(o["entity_id"])
            if level is None or o["source_id"] not in ok_sources:
                continue
            if o["period_kind"] != "multi_year" and level not in annual_levels:
                continue
            if o["denominator_source_id"] and o["denominator_source_id"] not in ok_sources:
                continue
            key = (o["period_start"], o["period_end"], o["period_kind"])
            p = periods.setdefault(key, {"rows": defaultdict(list), "sources": set()})
            row = {"entity_id": o["entity_id"],
                   "value": None if o["value"] is None else round(o["value"], d["digits"] + 2),
                   "status": o["status"]}
            note = "。".join(n for n in (o["coverage_note"], o["method_note"]) if n)
            if (level == "small_area" and o["period_start"] in past
                    and o["entity_id"] not in comparable[o["period_start"]]):
                # 境界が変わった地域は、過去の値を最新の形に重ねると誤解を招くため出さない
                row.update(value=None, status="not_applicable")
                note = f"{past[o['period_start']]['label']}から境界が変わったため比較できません"
            elif o["value"] is not None and o["numerator"] is not None:
                row["numerator"] = round(o["numerator"], 4)
                row["denominator"] = round(o["denominator"], 4)
            elif o["status"] in ("withheld", "not_applicable") and o["numerator"] is not None:
                # 分母が小さくて出さない値も、都道府県の分子・分母の合計には入れる（公開ファイルには書かない）
                row["_parts"] = (o["numerator"], o["denominator"])
            if note:
                row["note"] = note
            # 町丁・字等の値は都道府県ごとに1ファイル（区市町村ごとだと全国でファイル数が多すぎる。#52）
            chunk = LEVELS.get(level) or prefecture_of(o["entity_id"])
            p["rows"][(level, chunk)].append(row)
            if row["value"] is not None:
                covered.add(prefecture_of(o["entity_id"]))
            p["sources"].update(s for s in (o["source_id"], o["denominator_source_id"]) if s)
        for p in periods.values():
            _add_prefecture_rows(p["rows"], d, munis_by_pref)
        # 凡例の区切りは全時点の値をまとめて決め、時点を切り替えても色の意味が変わらないようにする。
        # 複数年の合計は値の大きさが違うので、年ごとの値とは別にまとめる。
        # zero_blank の指標は0を塗らないので、区切りは0より大きい値で決める（#35）
        zero_blank = bool(d["legend"].get("zero_blank"))
        pooled: dict[tuple[str, bool], list[float]] = defaultdict(list)
        for (_, _, kind), p in periods.items():
            for (lv, _), rows in p["rows"].items():
                pooled[(lv, kind == "multi_year")].extend(
                    r["value"] for r in rows
                    if r["value"] is not None and not (zero_blank and r["value"] == 0))
        method = d["legend"]["method"]
        breaks_fn = (diverging_breaks if method == "diverging" else
                     nice_breaks if method == "nice" else quantile_breaks)
        if method == "bands":
            # 区分で公表された値（就学援助率の「10%未満」など、値は区分の上の端）。区分ごとに1色にし、
            # 都道府県・時点が違っても同じ区分は同じ色にする（区切りは全国・全時点の最大値まで同じ）
            band = float(d["legend"]["band"])
            top = max((v for vals in pooled.values() for v in vals), default=0.0)
            fixed = [round(band * k, d["digits"]) for k in range(1, int(top // band) + 1)]
            breaks_fn = lambda vals, classes, digits: list(fixed)  # noqa: E731
        # 市区町村・町丁目は、全国で共通の区切りを最大 FINE_CLASSES 区分で決める（#145。東京都と山梨県のように
        # 水準の違う県どうしでも、同じ色は同じ値の範囲。区分を増やして、県の中の差も見えるようにする）。
        # 都道府県（47）は indicators.toml の classes のまま
        fine_fn = (diverging_breaks if method == "diverging" else
                   breaks_fn if method == "bands" else national_breaks)
        breaks_by_level = {
            (lv, multi): (breaks_fn(vals, d["legend"]["classes"], d["digits"]) if lv == "prefecture" else
                          fine_fn(vals, _fine_classes(d["legend"]["classes"], len(vals)), d["digits"]))
            for (lv, multi), vals in pooled.items()}
        period_meta = []
        # 年ごとの時点を古い順に並べ、複数年の合計は最後に置く
        for (start, end, kind), p in sorted(periods.items(), key=lambda kv: (kv[0][2] == "multi_year", kv[0])):
            pid = _period_id(start, end, kind)
            vdir = f"values/{indicator_id}/{pid}"
            legend = {}
            levels = sorted({lv for lv, _ in p["rows"]})
            for level in levels:
                vals = [r["value"] for (lv, _), rows in p["rows"].items() if lv == level
                        for r in rows if r["value"] is not None]
                legend[level] = {
                    "breaks": breaks_by_level.get((level, kind == "multi_year"), []),
                    "min": min(vals, default=None), "max": max(vals, default=None),
                    "count": len(vals)}
            national = _national_small_area_ranks(p["rows"])
            for (level, chunk), rows in p["rows"].items():
                if level == "small_area" and national:
                    for r in rows:
                        if r["entity_id"] in national:
                            r["national_rank"] = national[r["entity_id"]]
                # fraction = false: 分子・分母を公開ファイルに書かない（平均標高の「標高の合計」のように、
                # 内訳として見せても意味のない数。都道府県の値の計算には使う）
                hidden = {"_parts"} | ({"numerator", "denominator"} if d.get("fraction") is False else set())
                _write(out, f"{vdir}/{chunk}.json", {
                    "schema_version": SCHEMA_VERSION, "release_id": release_id,
                    "indicator_id": indicator_id, "period": pid, "level": level,
                    "unit": d["unit"], "boundary_version": boundary_version,
                    "rows": [{k: v for k, v in r.items() if k not in hidden}
                             for r in sorted(rows, key=lambda r: r["entity_id"])]})
            _write(out, f"{vdir}/legend.json", {
                "indicator_id": indicator_id, "period": pid, "method": method,
                "scheme": d["legend"]["scheme"], "zero_blank": zero_blank,
                "pooled_periods": sum(1 for k in periods if (k[2] == "multi_year") == (kind == "multi_year")),
                "levels": legend})
            used_sources |= p["sources"]
            period_meta.append({"period": pid, "period_end": end, "period_kind": kind,
                                "aggregate": kind == "multi_year",
                                "label": d.get("period_labels", {}).get(start) or _period_label(start, end, kind),
                                "levels": levels,
                                "boundary_version": boundary_version,
                                "source_ids": sorted(p["sources"])})
        if not period_meta:
            continue
        indicator_out.append({
            "id": indicator_id, "name": d["name"], "category": d["category"],
            "unit": d["unit"], "kind": d["kind"], "digits": d["digits"],
            "definition_version": d["definition_version"], "description": d["description"],
            "method": d["method"], "caveats": d.get("caveats", []),
            "min_denominator": d.get("min_denominator"), "scale": d.get("scale", 1), "legend": d["legend"],
            "fraction_units": d.get("fraction_units"), "compare_with": d.get("compare_with"),
            "family": d.get("family"), "facets": d.get("facets"),
            "prefectures": sorted(covered),
            "periods": period_meta,
            "default_period": _default_period(period_meta, d.get("levels", []))})
    _write(out, "indicators.json", {"schema_version": SCHEMA_VERSION, "release_id": release_id,
                                    "indicators": indicator_out})
    used_sources |= export_stations(conn, catalog, out, release_id, ok_sources)
    used_sources |= export_schools(conn, catalog, out, release_id, ok_sources)
    used_sources |= export_land_prices(conn, catalog, out, release_id, ok_sources)
    used_sources |= export_nurseries(conn, catalog, out, release_id, ok_sources)
    used_sources |= export_weather(conn, catalog, out, release_id, ok_sources)
    used_sources |= export_transport(conn, catalog, out, release_id, ok_sources)
    used_sources |= export_facilities(conn, catalog, out, release_id, ok_sources)
    used_sources |= export_land_use_tiles(conn, out, raw, ok_sources)

    used_sources |= {r["source_id"] for r in muni_rows} | {r["source_id"] for r in area_rows}
    src = conn.execute(
        f"""SELECT source_id, dataset_key, title, provider, url, license, license_url, attribution,
                   modification_note, published_at, retrieved_at, file_sha256
            FROM sources WHERE source_id IN ({",".join("?" * len(used_sources))})
            ORDER BY source_id""", sorted(used_sources)).fetchall()
    _write(out, "sources.json", {"schema_version": SCHEMA_VERSION, "release_id": release_id,
                                 "sources": [dict(r) for r in src]})

    # --- manifest ---------------------------------------------------------------
    files = []
    for f in sorted(out.rglob("*")):
        if f.is_file():
            data = f.read_bytes()
            files.append({"path": f.relative_to(out).as_posix(), "bytes": len(data),
                          "gzip_bytes": len(gzip.compress(data, 6)),
                          "sha256": hashlib.sha256(data).hexdigest()})
    default = indicator_out[0] if indicator_out else None
    manifest = {"schema_version": SCHEMA_VERSION, "release_id": release_id,
                "created_at": now_iso(), "git_commit": _git_commit(),
                "boundary_versions": [c["boundary_version"] for c in censuses], "note": note,
                "size": size_report(files, boundary_version,
                                    default and (default["id"], default["default_period"])),
                "files": files}
    _write(out, "manifest.json", manifest)
    manifest_sha = hashlib.sha256((out / "manifest.json").read_bytes()).hexdigest()
    conn.execute("INSERT INTO releases VALUES (?, ?, ?, ?, ?)",
                 (release_id, manifest["created_at"], manifest["git_commit"], manifest_sha, note))
    return out


def export_stations(conn: sqlite3.Connection, catalog: dict[str, dict], out: Path,
                    release_id: str, ok_sources: set[str]) -> set[str]:
    """駅の点（places/stations.json）。年度ごとの値を periods の順に並べる（設計書 第9章）。"""
    used: set[str] = set()
    for indicator_id, d in catalog.items():
        if "station" not in d.get("levels", []):
            continue
        rows = conn.execute(
            """SELECT o.entity_id, o.period_start, o.period_end, o.period_kind, o.dimension_key,
                      o.value, o.status, o.source_id, o.coverage_note, o.method_note
               FROM observations o JOIN entities e ON e.entity_id = o.entity_id
               WHERE e.entity_type = 'station' AND o.indicator_id = ? AND o.definition_version = ?""",
            (indicator_id, d["definition_version"])).fetchall()
        rows = [r for r in rows if r["source_id"] in ok_sources]
        if not rows:
            continue
        periods = sorted({(r["period_start"], r["period_end"], r["period_kind"]) for r in rows})
        index = {p[0]: i for i, p in enumerate(periods)}
        stations: dict[str, dict] = {}
        srcs: set[str] = set()   # この指標の出典（同じ種類の点のほかの指標と混ぜない）
        info = {r["entity_id"]: r for r in conn.execute(
            """SELECT e.entity_id, e.name, e.parent_id, l.lon, l.lat, a.attributes
               FROM entities e JOIN locations l ON l.entity_id = e.entity_id AND l.role = 'main'
               LEFT JOIN entity_attributes a ON a.entity_id = e.entity_id
               WHERE e.entity_type = 'station'""")}
        for r in rows:
            e = info.get(r["entity_id"])
            if e is None:
                continue
            st = stations.get(r["entity_id"])
            if st is None:
                attrs = json.loads(e["attributes"] or "{}")
                st = stations[r["entity_id"]] = {
                    "id": r["entity_id"], "name": e["name"], "operator": attrs.get("operator", ""),
                    "group": attrs.get("group", ""), "lines": attrs.get("lines", []),
                    "municipality_id": e["parent_id"],
                    "coord": _coord(e),
                    "values": [None] * len(periods), "status": [None] * len(periods)}
            i = index[r["period_start"]]
            if r["dimension_key"] != "all":
                st.setdefault("by_line", {}).setdefault(r["dimension_key"], [None] * len(periods))[i] = r["value"]
                continue
            st["values"][i] = None if r["value"] is None else round(r["value"])
            st["status"][i] = r["status"]
            note = "。".join(n for n in (r["coverage_note"], r["method_note"]) if n)
            if note:
                st.setdefault("notes", {})[str(i)] = note
            srcs.add(r["source_id"])
        _write_places(out, indicator_id, _places_meta(release_id, indicator_id, d, periods, srcs),
            "stations", sorted(stations.values(), key=lambda s: s["id"]))
        used |= srcs
    return used


def export_schools(conn: sqlite3.Connection, catalog: dict[str, dict], out: Path,
                   release_id: str, ok_sources: set[str]) -> set[str]:
    """学校の点（places/<指標>.json）。位置のない学校も一覧には含め、coord を null にする。
    年度は出典ごとに違う（東京都は2023年度まで、ほかの道県・市は2024〜2026年度。#138）ので、学校ごとに出典の
    最新の年度に値がない学校（閉校・統合など）を closed にし、学校ごとの出典（sources）を書く。"""
    used: set[str] = set()
    for indicator_id, d in catalog.items():
        if "school" not in d.get("levels", []):
            continue
        rows = conn.execute(
            """SELECT o.entity_id, o.period_start, o.period_end, o.period_kind, o.dimension_key,
                      o.value, o.status, o.source_id
               FROM observations o JOIN entities e ON e.entity_id = o.entity_id
               WHERE e.entity_type = 'school' AND o.indicator_id = ? AND o.definition_version = ?""",
            (indicator_id, d["definition_version"])).fetchall()
        rows = [r for r in rows if r["source_id"] in ok_sources]
        info = {r["entity_id"]: r for r in conn.execute(
            """SELECT e.entity_id, e.name, e.parent_id, l.lon, l.lat, l.source_id AS loc_source,
                      a.attributes
               FROM entities e LEFT JOIN locations l ON l.entity_id = e.entity_id AND l.role = 'main'
               LEFT JOIN entity_attributes a ON a.entity_id = e.entity_id
               WHERE e.entity_type = 'school'""")}
        if not rows and not _location_only(info, ok_sources):
            continue
        periods = sorted({(r["period_start"], r["period_end"], r["period_kind"]) for r in rows})
        index = {p[0]: i for i, p in enumerate(periods)}
        source_latest: dict[str, str] = {}   # 出典ごとの最新の年度
        for r in rows:
            source_latest[r["source_id"]] = max(source_latest.get(r["source_id"], ""), r["period_start"])
        schools: dict[str, dict] = {}
        last: dict[str, tuple[str, str]] = {}   # 学校ごとの最後の年度と、その出典
        srcs: set[str] = set()   # この指標の出典（同じ種類の点のほかの指標と混ぜない）
        for r in rows:
            e = info.get(r["entity_id"])
            if e is None:
                continue
            sc = schools.get(r["entity_id"])
            if sc is None:
                attrs = json.loads(e["attributes"] or "{}")
                located = e["lon"] is not None and e["loc_source"] in ok_sources
                sc = schools[r["entity_id"]] = {
                    "id": r["entity_id"], "name": e["name"],
                    "school_type": attrs.get("school_type", ""), "type_label": attrs.get("type_label", ""),
                    "founder": attrs.get("founder", ""), "address": attrs.get("address"),
                    "municipality_id": e["parent_id"],
                    "coord": _coord(e) if located else None,
                    "precision": attrs.get("precision") if located else None,
                    "values": [None] * len(periods), "status": [None] * len(periods), "sources": []}
                if located:
                    srcs.add(e["loc_source"])
                    sc["sources"].append(e["loc_source"])
            i = index[r["period_start"]]
            if r["dimension_key"] != "all":
                sc.setdefault("by_grade", {}).setdefault(r["dimension_key"], [None] * len(periods))[i] = r["value"]
                continue
            sc["values"][i] = None if r["value"] is None else round(r["value"])
            sc["status"][i] = r["status"]
            if r["period_start"] >= last.get(r["entity_id"], ("", ""))[0]:
                last[r["entity_id"]] = (r["period_start"], r["source_id"])
            srcs.add(r["source_id"])
        for entity_id, (period, source_id) in last.items():
            sc = schools[entity_id]
            sc["sources"].insert(0, source_id)   # 人数の出典を先に
            if period < source_latest[source_id]:
                sc["closed"] = True   # 出典の最新の年度の一覧にない（閉校・統合など）
        for e in _location_only(info, ok_sources):
            attrs = json.loads(e["attributes"] or "{}")
            schools[e["entity_id"]] = {
                "id": e["entity_id"], "name": e["name"],
                "school_type": attrs.get("school_type", ""), "type_label": attrs.get("type_label", ""),
                "founder": attrs.get("founder", ""), "address": attrs.get("address"),
                "municipality_id": e["parent_id"],
                "coord": _coord(e), "precision": None,
                "values": [None] * len(periods), "status": [None] * len(periods),
                "location_only": True, "as_of": attrs.get("as_of"), "sources": [e["loc_source"]]}
            unlisted = attrs.get("unlisted")
            if unlisted and unlisted["source_id"] in ok_sources:
                # 人数の一覧がある市区町村なのに、その一覧に見つからなかった学校（休校・閉校など）
                schools[e["entity_id"]]["unlisted"] = unlisted
                schools[e["entity_id"]]["sources"].insert(0, unlisted["source_id"])
                srcs.add(unlisted["source_id"])
            srcs.add(e["loc_source"])
        for sc in schools.values():
            if "by_grade" in sc:
                sc["by_grade"] = {g: [None if v is None else round(v) for v in vals]
                                  for g, vals in sorted(sc["by_grade"].items())}
        _write_places(out, indicator_id, _places_meta(release_id, indicator_id, d, periods, srcs),
            "schools", sorted(schools.values(), key=lambda s: s["id"]))
        used |= srcs
    return used


def export_land_prices(conn: sqlite3.Connection, catalog: dict[str, dict], out: Path,
                       release_id: str, ok_sources: set[str]) -> set[str]:
    """地価公示の標準地の点（places/<指標>.json）。年ごとの価格を periods の順に並べる。"""
    used: set[str] = set()
    for indicator_id, d in catalog.items():
        if "land_point" not in d.get("levels", []):
            continue
        rows = conn.execute(
            """SELECT o.entity_id, o.period_start, o.period_end, o.period_kind, o.value, o.source_id
               FROM observations o JOIN entities e ON e.entity_id = o.entity_id
               WHERE e.entity_type = 'land_point' AND o.indicator_id = ? AND o.definition_version = ?
                 AND o.dimension_key = 'all'""",
            (indicator_id, d["definition_version"])).fetchall()
        rows = [r for r in rows if r["source_id"] in ok_sources]
        if not rows:
            continue
        periods = sorted({(r["period_start"], r["period_end"], r["period_kind"]) for r in rows})
        index = {p[0]: i for i, p in enumerate(periods)}
        info = {r["entity_id"]: r for r in conn.execute(
            """SELECT e.entity_id, e.name, e.parent_id, l.lon, l.lat, l.source_id AS loc_source,
                      a.attributes
               FROM entities e JOIN locations l ON l.entity_id = e.entity_id AND l.role = 'main'
               LEFT JOIN entity_attributes a ON a.entity_id = e.entity_id
               WHERE e.entity_type = 'land_point'""")}
        points: dict[str, dict] = {}
        srcs: set[str] = set()   # この指標の出典（地価公示・地価調査で混ぜない）
        for r in rows:
            e = info.get(r["entity_id"])
            if e is None or e["loc_source"] not in ok_sources:
                continue
            pt = points.get(r["entity_id"])
            if pt is None:
                attrs = json.loads(e["attributes"] or "{}")
                pt = points[r["entity_id"]] = {
                    "id": r["entity_id"], "name": e["name"], "municipality_id": e["parent_id"],
                    "coord": _coord(e),
                    **{k: attrs.get(k) for k in ("use", "use_label", "address", "residential_address",
                                                 "area_m2", "current_use", "station", "station_distance_m",
                                                 "zoning", "change_rate")},
                    "values": [None] * len(periods)}
                srcs.add(e["loc_source"])
            pt["values"][index[r["period_start"]]] = None if r["value"] is None else round(r["value"])
            srcs.add(r["source_id"])
        _write_places(out, indicator_id, _places_meta(release_id, indicator_id, d, periods, srcs),
            "points", sorted(points.values(), key=lambda s: s["id"]))
        used |= srcs
    return used


WEATHER_FILE = "weather_normals"   # places/weather_normals.json（天気の指標をまとめた1ファイル）


def export_weather(conn: sqlite3.Connection, catalog: dict[str, dict], out: Path,
                   release_id: str, ok_sources: set[str]) -> set[str]:
    """気象庁の平年値の観測所（places/weather_normals.json）。全国で約1,300地点と少ないので、都道府県に分けず
    1ファイルにし、日照時間・降水量・最深積雪・降雪量をまとめて持つ（観測所を選ぶと4つとも見せる。docs/design-changes.md #94）。"""
    ids = [i for i, d in catalog.items() if "weather_station" in d.get("levels", [])]
    rows = [r for r in conn.execute(
        f"""SELECT o.entity_id, o.indicator_id, o.definition_version, o.value, o.source_id FROM observations o
            JOIN entities e ON e.entity_id = o.entity_id
            WHERE e.entity_type = 'weather_station' AND o.dimension_key = 'all'
              AND o.indicator_id IN ({",".join("?" * len(ids))})""", ids).fetchall()
            if r["source_id"] in ok_sources and r["value"] is not None
            and r["definition_version"] == catalog[r["indicator_id"]]["definition_version"]]
    if not rows:
        return set()
    info = {r["entity_id"]: r for r in conn.execute(
        """SELECT e.entity_id, e.name, e.name_kana, e.parent_id, l.lon, l.lat, l.source_id AS loc_source,
                  a.attributes
           FROM entities e JOIN locations l ON l.entity_id = e.entity_id AND l.role = 'main'
           LEFT JOIN entity_attributes a ON a.entity_id = e.entity_id
           WHERE e.entity_type = 'weather_station'""")}
    points: dict[str, dict] = {}
    used: set[str] = set()
    values: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        e = info.get(r["entity_id"])
        if e is None or e["loc_source"] not in ok_sources:
            continue
        attrs = json.loads(e["attributes"] or "{}")
        pt = points.setdefault(r["entity_id"], {
            "id": r["entity_id"], "name": e["name"], "kana": e["name_kana"],
            "municipality_id": e["parent_id"],
            "coord": _coord(e),
            "altitude_m": attrs.get("altitude_m"), "values": {}, "monthly": {}, "years": {}})
        d = catalog[r["indicator_id"]]
        el = attrs.get("elements", {}).get(r["indicator_id"], {})
        pt["values"][r["indicator_id"]] = round(r["value"], d["digits"]) if d["digits"] else round(r["value"])
        # 月の値は表で見せるだけなので整数にする（全国で1ファイルにするため小さくする）
        pt["monthly"][r["indicator_id"]] = [None if m is None else round(m) for m in el.get("monthly") or []]
        pt["years"][r["indicator_id"]] = [el.get("start"), el.get("end"), el.get("years")]
        values[r["indicator_id"]].append(r["value"])
        used |= {r["source_id"], e["loc_source"]}
    elements = []
    for i in ids:
        if not values[i]:
            continue
        d = catalog[i]
        elements.append({
            "id": i, "name": d["name"], "unit": d["unit"], "digits": d["digits"],
            "description": d["description"], "method": d["method"], "caveats": d.get("caveats", []),
            "scheme": d["legend"]["scheme"], "count": len(values[i]),
            "breaks": nice_breaks(values[i], d["legend"]["classes"], d["digits"]),
            "min": min(values[i]), "max": max(values[i])})
    _write(out, f"places/{WEATHER_FILE}.json", {
        "schema_version": SCHEMA_VERSION, "release_id": release_id,
        "name": "天気（平年値）", "unit": "", "description": "気象庁の観測所ごとの、1991〜2020年の平年値"
        "（日照時間・降水量・最深積雪・降雪量）。",
        "periods": [{"period": "1991-2020", "label": "1991〜2020年の平年値"}],
        "elements": elements, "source_ids": sorted(used),
        "stations": sorted(points.values(), key=lambda p: p["id"])})
    return used


FACILITY_LEVELS = ("roadside_station", "cultural_property")
# 施設の属性のうち、点の一覧に載せないもの（取込で使う情報）
FACILITY_PRIVATE = {"source_id", "prefecture", "as_of", "municipalities"}


def export_facilities(conn: sqlite3.Connection, catalog: dict[str, dict], out: Path,
                      release_id: str, ok_sources: set[str]) -> set[str]:
    """値のない施設の点（道の駅・国指定文化財）。places/<指標>.json に、名前・市区町村・位置と属性（住所など）を書く。
    位置の分からない施設も一覧には含め、coord を null にする。split_by_prefecture の指標（件数の多い文化財）は
    都道府県ごとのファイルに分ける（_write_places）。"""
    used: set[str] = set()
    for indicator_id, d in catalog.items():
        level = next((lv for lv in FACILITY_LEVELS if lv in d.get("levels", [])), None)
        if level is None:
            continue
        rows = conn.execute(
            """SELECT e.entity_id, e.name, e.parent_id, l.lon, l.lat, l.source_id AS loc_source, a.attributes
               FROM entities e LEFT JOIN locations l ON l.entity_id = e.entity_id AND l.role = 'main'
               LEFT JOIN entity_attributes a ON a.entity_id = e.entity_id
               WHERE e.entity_type = ? ORDER BY e.entity_id""", (level,)).fetchall()
        points, srcs, dates = [], set(), set()
        for r in rows:
            attrs = json.loads(r["attributes"] or "{}")
            if attrs.get("source_id") not in ok_sources:
                continue
            located = r["lon"] is not None and r["loc_source"] in ok_sources
            munis = attrs.get("municipalities") or []
            points.append({"id": r["entity_id"], "name": r["name"], "municipality_id": r["parent_id"],
                           "coord": _coord(r) if located else None,
                           # 2つ以上の市区町村にまたがる施設（道の駅「宇津ノ谷峠」など）はすべての市区町村
                           **({"municipality_ids": munis} if len(munis) > 1 else {}),
                           **{k: v for k, v in attrs.items() if k not in FACILITY_PRIVATE and v is not None}})
            srcs.add(attrs["source_id"])
            if located:
                srcs.add(r["loc_source"])
            if attrs.get("as_of"):
                dates.add(attrs["as_of"])
        if not points:
            continue
        periods = [(t, t, "point") for t in sorted(dates)]
        meta = _places_meta(release_id, indicator_id, d, periods, srcs)
        if d.get("split_by_prefecture"):
            _write_places(out, indicator_id, meta, "points", points)
        else:
            _write(out, f"places/{indicator_id}.json", {**meta, "points": points})
        used |= srcs
    return used


TRANSPORT_LEVELS = ("airport", "port")


def export_transport(conn: sqlite3.Connection, catalog: dict[str, dict], out: Path,
                     release_id: str, ok_sources: set[str]) -> set[str]:
    """空港・港の点（places/<指標>.json）。全国で空港は約100、港は数百と少ないので都道府県に分けず1ファイルにし、
    年ごとの合計・国内・国際の値を periods の順に並べる。"""
    used: set[str] = set()
    for indicator_id, d in catalog.items():
        level = next((lv for lv in TRANSPORT_LEVELS if lv in d.get("levels", [])), None)
        if level is None:
            continue
        rows = [r for r in conn.execute(
            """SELECT o.entity_id, o.period_start, o.period_end, o.period_kind, o.dimension_key, o.value, o.source_id
               FROM observations o JOIN entities e ON e.entity_id = o.entity_id
               WHERE e.entity_type = ? AND o.indicator_id = ? AND o.definition_version = ?""",
            (level, indicator_id, d["definition_version"])).fetchall() if r["source_id"] in ok_sources]
        if not rows:
            continue
        periods = sorted({(r["period_start"], r["period_end"], r["period_kind"]) for r in rows})
        index = {p[0]: i for i, p in enumerate(periods)}
        info = {r["entity_id"]: r for r in conn.execute(
            """SELECT e.entity_id, e.name, e.parent_id, l.lon, l.lat, l.source_id AS loc_source
               FROM entities e JOIN locations l ON l.entity_id = e.entity_id AND l.role = 'main'
               WHERE e.entity_type = ?""", (level,))}
        points: dict[str, dict] = {}
        srcs: set[str] = set()
        for r in rows:
            e = info.get(r["entity_id"])
            if e is None or e["loc_source"] not in ok_sources:
                continue
            pt = points.setdefault(r["entity_id"], {
                "id": r["entity_id"], "name": e["name"], "municipality_id": e["parent_id"],
                "coord": _coord(e),
                "values": [None] * len(periods), "domestic": [None] * len(periods),
                "international": [None] * len(periods)})
            key = {"all": "values"}.get(r["dimension_key"], r["dimension_key"])
            if key in pt and r["value"] is not None:
                pt[key][index[r["period_start"]]] = round(r["value"])
            srcs |= {r["source_id"], e["loc_source"]}
        _write(out, f"places/{indicator_id}.json", {
            **_places_meta(release_id, indicator_id, d, periods, srcs),
            "points": sorted(points.values(), key=lambda p: p["id"])})
        used |= srcs
    return used


def export_nurseries(conn: sqlite3.Connection, catalog: dict[str, dict], out: Path,
                     release_id: str, ok_sources: set[str]) -> set[str]:
    """保育所などの点（places/<指標>.json）。位置のない施設も一覧には含め、coord を null にする。
    東京都の認可保育所（都の一覧、認可定員）と、ここdeサーチの施設（利用定員・利用者数、#138）で時点が違うので、
    施設ごとに値のある時点（status）と出典（sources）を書く。利用者数は users、年齢別は by_age（各時点の配列）。"""
    used: set[str] = set()
    for indicator_id, d in catalog.items():
        if "nursery" not in d.get("levels", []):
            continue
        rows = conn.execute(
            """SELECT o.entity_id, o.period_start, o.period_end, o.period_kind, o.dimension_key, o.value,
                      o.status, o.source_id
               FROM observations o JOIN entities e ON e.entity_id = o.entity_id
               WHERE e.entity_type = 'nursery' AND o.indicator_id = ? AND o.definition_version = ?""",
            (indicator_id, d["definition_version"])).fetchall()
        rows = [r for r in rows if r["source_id"] in ok_sources]
        info = {r["entity_id"]: r for r in conn.execute(
            """SELECT e.entity_id, e.name, e.parent_id, l.lon, l.lat, l.source_id AS loc_source,
                      a.attributes
               FROM entities e LEFT JOIN locations l ON l.entity_id = e.entity_id AND l.role = 'main'
               LEFT JOIN entity_attributes a ON a.entity_id = e.entity_id
               WHERE e.entity_type = 'nursery'""")}
        if not rows and not _location_only(info, ok_sources):
            continue
        periods = sorted({(r["period_start"], r["period_end"], r["period_kind"]) for r in rows})
        index = {p[0]: i for i, p in enumerate(periods)}
        points: dict[str, dict] = {}
        srcs: set[str] = set()   # この指標の出典（同じ種類の点のほかの指標と混ぜない）
        for r in rows:
            e = info.get(r["entity_id"])
            if e is None:
                continue
            pt = points.get(r["entity_id"])
            if pt is None:
                attrs = json.loads(e["attributes"] or "{}")
                located = e["lon"] is not None and e["loc_source"] in ok_sources
                pt = points[r["entity_id"]] = {
                    "id": r["entity_id"], "name": e["name"], "municipality_id": e["parent_id"],
                    "facility_type": attrs.get("facility_type", "認可保育所"),
                    "capacity_kind": attrs.get("capacity_kind", "認可定員"),
                    "founder": attrs.get("founder", ""), "address": attrs.get("address"),
                    "coord": _coord(e) if located else None,
                    "precision": attrs.get("precision") if located else None,
                    "values": [None] * len(periods), "status": [None] * len(periods), "sources": []}
                if located:
                    srcs.add(e["loc_source"])
                    pt["sources"].append(e["loc_source"])
            i = index[r["period_start"]]
            value = None if r["value"] is None else round(r["value"])
            if r["dimension_key"] == "users":
                pt.setdefault("users", [None] * len(periods))[i] = value
            elif r["dimension_key"].startswith("users:"):
                age = r["dimension_key"].removeprefix("users:")
                pt.setdefault("by_age", {}).setdefault(age, [None] * len(periods))[i] = value
            else:
                pt["values"][i] = value
                pt["status"][i] = r["status"]
            if r["source_id"] not in pt["sources"]:
                pt["sources"].insert(0, r["source_id"])
            srcs.add(r["source_id"])
        for e in _location_only(info, ok_sources):
            attrs = json.loads(e["attributes"] or "{}")
            points[e["entity_id"]] = {
                "id": e["entity_id"], "name": e["name"], "municipality_id": e["parent_id"],
                "facility_type": attrs.get("facility_type", "認可保育所"),
                "founder": attrs.get("founder", ""), "address": attrs.get("address"),
                "coord": _coord(e), "precision": None,
                "values": [None] * len(periods), "status": [None] * len(periods),
                "location_only": True, "as_of": attrs.get("as_of"), "sources": [e["loc_source"]]}
            srcs.add(e["loc_source"])
        _write_places(out, indicator_id, _places_meta(release_id, indicator_id, d, periods, srcs),
            "points", sorted(points.values(), key=lambda s: s["id"]))
        used |= srcs
    return used


def _default_period(period_meta: list[dict], levels: list[str]) -> str:
    """最初に表示する時点。町丁・字等まである指標は、町丁・字等の値がある最新の時点にする
    （国勢調査の速報のように区市町村だけの新しい時点は、スライドバーで選べるようにするだけ）。"""
    annual = [p for p in period_meta if not p["aggregate"]]
    if "small_area" in levels:
        fine = [p for p in annual if "small_area" in p["levels"]]
        if fine:
            return fine[-1]["period"]
        # 町丁・字等の値が複数年の合計にだけある指標（全国の犯罪オープンデータ、#98）は合計を最初に出す
        fine = [p for p in period_meta if p["aggregate"] and "small_area" in p["levels"]]
        if fine:
            return fine[-1]["period"]
    return annual[-1]["period"]


LAND_USE_TILES = "land_use_tiles"


def export_land_use_tiles(conn: sqlite3.Connection, out: Path, raw: Path | None, ok_sources: set[str]) -> set[str]:
    """地図に重ねる土地利用図のタイル（tdm/prepare で作ったもの、#123）を land_use/ にそのまま入れる。
    land_use/tiles.json に年度・タイルの一覧・凡例と出典を書く。取り込んでいなければ何もしない。"""
    row = conn.execute("SELECT source_id FROM sources WHERE dataset_key = ? ORDER BY retrieved_at DESC LIMIT 1",
                       (LAND_USE_TILES,)).fetchone()
    src = raw / LAND_USE_TILES if raw else None
    if row is None or row["source_id"] not in ok_sources or src is None or not (src / "tiles.json").exists():
        return set()
    index = json.loads((src / "tiles.json").read_text(encoding="utf-8"))
    count = 0
    for y in index["years"]:
        for zoom, tiles in y["tiles"].items():
            for t in tiles:
                rel = f"{y['year']}/{zoom}/{t}.png"
                target = out / "land_use" / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((src / rel).read_bytes())
                count += 1
    _write(out, "land_use/tiles.json", {**index, "source_ids": [row["source_id"]]})
    progress(f"土地利用図のタイル {count} 枚")
    return {row["source_id"]}


def _national_small_area_ranks(rows: dict) -> dict[str, int]:
    """町丁・字等の全国での順位（値の大きい順、同値は同順位、値のない地域は数えない）。

    町丁・字等の値は都道府県ごとのファイルに分かれていて、画面で全国の順位を数えるには全都道府県の
    ファイルを読む必要がある。そこで書き出し時に数えて各行に入れる。母数は legend.json の
    levels.small_area.count。値が1つの都道府県だけにある指標（東京都だけの指標など）や、
    全国ですべて同じ値のときは入れない（都道府県内の順位と同じか、意味がないため）。
    """
    values = [(r["entity_id"], r["value"]) for (lv, _), rs in rows.items() if lv == "small_area"
              for r in rs if r["value"] is not None]
    if len({prefecture_of(e) for e, _ in values}) < 2 or len({v for _, v in values}) < 2:
        return {}
    ordered = sorted((v for _, v in values), reverse=True)
    first: dict[float, int] = {}
    for i, v in enumerate(ordered):
        first.setdefault(v, i + 1)
    return {e: first[v] for e, v in values}


def _add_prefecture_rows(rows: dict, d: dict, munis_by_pref: dict[str, list]) -> None:
    """区市町村の値を都道府県ごとに合計して、都道府県の値を作る（出典に都道府県の値があればそちらを使う）。

    割合などは分子・分母をそれぞれ合計して計算し、人数・件数は値を合計する。1つでも値のない区市町村が
    ある都道府県は、欠けた分を0とみなすことになるので値なしにする。合計できない指標（平均など分子・分母の
    ない値）は作らない。"""
    munis = {r["entity_id"]: r for r in rows.get(("municipality", "municipalities"), [])}
    if not munis or d["legend"]["method"] == "bands":
        return  # 区分で公表された値（就学援助率など）は合計も平均もできない
    have = {r["entity_id"] for r in rows.get(("prefecture", "prefectures"), [])}
    scale = d.get("scale", 1)
    out = []
    for pref, members in sorted(munis_by_pref.items()):
        pid = prefecture_entity_id(pref)
        if pid in have:
            continue
        got = [munis.get(m["entity_id"]) for m in members]
        if not any(r and r["value"] is not None for r in got):
            continue  # この指標の値がない都道府県（東京都だけの指標など）
        # 分母が小さくて値を出さない市区町村（_parts に分子・分母がある）も、合計には入れる
        if any(r is None or (r["value"] is None and "_parts" not in r) for r in got):
            out.append({"entity_id": pid, "value": None, "status": "missing",
                        "note": "値のない市区町村があるため、都道府県の値は出していません"})
            continue
        parts = [(r["numerator"], r["denominator"]) if "numerator" in r else r.get("_parts") for r in got]
        if all(parts):
            num = sum(n for n, _ in parts)
            den = sum(x for _, x in parts)
            if not den:
                out.append({"entity_id": pid, "value": None, "status": "missing"})
                continue
            out.append({"entity_id": pid, "value": round(num / den * scale, d["digits"] + 2),
                        "status": "derived", "numerator": round(num, 4), "denominator": round(den, 4),
                        "note": "市区町村の分子・分母を合計して計算"})
        elif d["kind"] == "count" and all(r["value"] is not None for r in got):
            out.append({"entity_id": pid, "value": round(sum(r["value"] for r in got), d["digits"] + 2),
                        "status": "derived", "note": "市区町村の値の合計"})
    if out:
        rows[("prefecture", "prefectures")].extend(out)


def size_report(files: list[dict], boundary_version: str,
                default: tuple[str, str] | None) -> dict:
    """配信容量を集計し、目安を超えた項目を warnings / errors に入れる。"""
    by_path = {f["path"]: f["gzip_bytes"] for f in files}
    raw = {f["path"]: f["bytes"] for f in files}
    errors = [f"{p}: {b:,} bytes（Workers の1ファイル上限 25MiB 超過）"
              for p, b in raw.items() if b > WORKERS_FILE_LIMIT]
    if len(files) > FILE_COUNT_LIMIT:
        errors.append(f"ファイル数 {len(files):,}（Workers 無料枠の1版2万ファイルにページ分を残した上限 {FILE_COUNT_LIMIT:,} 超過）")
    initial_files = ["indicators.json", "areas.json", "sources.json",
                     f"boundaries/{boundary_version}/municipalities.geojson",
                     f"boundaries/{boundary_version}/prefectures.geojson"]
    if default:
        initial_files += [f"values/{default[0]}/{default[1]}/{name}.json"
                          for name in ("prefectures", "municipalities", "legend")]
    initial = sum(by_path.get(p, 0) for p in initial_files)
    per_area = {}
    prefix = f"boundaries/{boundary_version}/"
    for p, b in by_path.items():
        rest = p[len(prefix):] if p.startswith(prefix) else ""
        if not rest or rest.startswith(("municipalities", "prefectures")):
            continue
        code = rest.split(".")[0]
        # 町丁目を開くとき: その区市町村の境界（名前・範囲を含む）と、都道府県の値・区市町村界（細かい版）
        pref = code[:2]
        values = by_path.get(f"values/{default[0]}/{default[1]}/{pref}.json", 0) if default else 0
        per_area[code] = (b + values
                          + by_path.get(f"{prefix}municipalities/{pref}.geojson", 0))
    warnings = []
    if FILE_COUNT_WARN < len(files) <= FILE_COUNT_LIMIT:
        warnings.append(f"ファイル数 {len(files):,}（目安 {FILE_COUNT_WARN:,}）")
    if initial > INITIAL_LOAD_TARGET:
        warnings.append(f"初回表示の読み込みが圧縮後 {initial:,} bytes（目安 {INITIAL_LOAD_TARGET:,}）")
    for code, b in sorted(per_area.items(), key=lambda kv: -kv[1]):
        if b > AREA_LOAD_TARGET:
            warnings.append(f"{code} の町丁目読み込みが圧縮後 {b:,} bytes（目安 {AREA_LOAD_TARGET:,}）")
    largest = max(per_area.items(), key=lambda kv: kv[1], default=(None, 0))
    return {
        "file_count": len(files),
        "total_bytes": sum(raw.values()), "total_gzip_bytes": sum(by_path.values()),
        "initial_load_gzip_bytes": initial,
        "largest_area_load": {"municipality_code": largest[0], "gzip_bytes": largest[1]},
        "warnings": warnings, "errors": errors,
    }
