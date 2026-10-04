"""SQLite から公開用の JSON・GeoJSON を生成する（設計書 第9章）。

出力先: <data>/releases/<release_id>/ 。版付きのパスで配信し、manifest.json に
全ファイルの hash を記録する。再配布できない出典（redistributable=0）の値・境界は出力しない。
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

from . import SCHEMA_VERSION
from .breaks import diverging_breaks, nice_breaks
from .db import now_iso
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


def _round_coords(obj, digits=COORD_DIGITS):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(float(x), digits) for x in obj]
        return [_round_coords(o, digits) for o in obj]
    return obj


def _simplified(geometry_json: str, tolerance: float, digits: int = COORD_DIGITS) -> dict:
    geom = shape(json.loads(geometry_json))
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


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _quantile_breaks(values: list[float], classes: int, digits: int) -> list[float]:
    if len(values) < 2:
        return []
    qs = statistics.quantiles(values, n=classes, method="inclusive")
    breaks: list[float] = []
    for q in qs:
        b = round(q, digits)
        if not breaks or b > breaks[-1]:
            breaks.append(b)
    return breaks


def _diverging_breaks(values: list[float], classes: int, digits: int) -> list[float]:
    """0（増減なし）を境にし、減少側・増加側をそれぞれ classes/2 等分した位置で区切る。"""
    half = max(1, classes // 2)
    breaks = [0.0]
    for side in ([v for v in values if v < 0], [v for v in values if v > 0]):
        if len(side) >= 2 and half > 1:
            breaks.extend(round(q, digits) for q in statistics.quantiles(side, n=half, method="inclusive"))
    out: list[float] = []
    for b in sorted(breaks):
        if not out or b > out[-1]:
            out.append(b)
    return out


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
                   release_id: str, censuses: list[dict], note: str | None = None) -> Path:
    """censuses は古い順。最後の時点の境界で地図を作り、過去の時点の値はそこへ重ねる。"""
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
    muni_shapes = {r["entity_id"]: shape(json.loads(r["geometry"])) for r in muni_rows}
    neighbors = _neighbors(muni_shapes)
    pref_names = {r["entity_id"]: r["name"] for r in conn.execute(
        "SELECT entity_id, name FROM entities WHERE entity_type = 'prefecture'")}

    # 区市町村界: 全国を粗く1ファイル（最初に読む）と、都道府県ごとに細かく（拡大したときに読む）
    bdir = f"boundaries/{boundary_version}"
    _write(out, f"{bdir}/municipalities.geojson", {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {"id": r["entity_id"], "name": r["name"]},
                      "geometry": _simplified(r["geometry"], NATION_TOLERANCE, NATION_DIGITS)}
                     for r in muni_rows]})
    munis_by_pref: dict[str, list] = defaultdict(list)
    for r in muni_rows:
        munis_by_pref[prefecture_of(r["entity_id"])].append(r)
    for pref, rows in munis_by_pref.items():
        _write(out, f"{bdir}/municipalities/{pref}.geojson", {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {"id": r["entity_id"], "name": r["name"]},
                          "geometry": _simplified(r["geometry"], MUNI_TOLERANCE)} for r in rows]})
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
    centers: dict[str, list[float]] = {}
    for muni_id, rows in by_muni.items():
        geoms = dict(conn.execute(
            """SELECT b.entity_id, b.geometry FROM boundaries b
               JOIN entities e ON e.entity_id = b.entity_id
               WHERE e.parent_id = ? AND e.entity_type = 'small_area' AND b.boundary_version = ?""",
            (muni_id, boundary_version)).fetchall())
        for r in rows:
            p = shape(json.loads(geoms[r["entity_id"]])).representative_point()
            centers[r["entity_id"]] = [round(p.x, 5), round(p.y, 5)]
        _write(out, f"{bdir}/{_code(muni_id)}.geojson", {
            "type": "FeatureCollection",
            "features": [{"type": "Feature",
                          "properties": {"id": r["entity_id"], "name": r["name"]},
                          "geometry": _simplified(geoms[r["entity_id"]], AREA_TOLERANCE)}
                         for r in rows]})

    # --- 地域一覧・検索索引 ----------------------------------------------------
    def bbox(r):
        return [round(r["bbox_west"], 5), round(r["bbox_south"], 5),
                round(r["bbox_east"], 5), round(r["bbox_north"], 5)]

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
    for muni_id, rows in by_muni.items():
        _write(out, f"areas/{_code(muni_id)}.json", {
            "schema_version": SCHEMA_VERSION, "municipality_id": muni_id,
            "areas": [{"id": r["entity_id"], "name": r["name"], "bbox": bbox(r),
                       "center": centers[r["entity_id"]]} for r in rows]})
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
        for o in obs:
            level = exported_entities.get(o["entity_id"])
            if level is None or o["source_id"] not in ok_sources:
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
                     nice_breaks if method == "nice" else _quantile_breaks)
        breaks_by_level = {key: breaks_fn(vals, d["legend"]["classes"], d["digits"])
                           for key, vals in pooled.items()}
        # 市区町村は都道府県ごとにも区切る（全国の区切りだと、東京都と山梨県のように水準の違う県で
        # 県内の差が見えなくなるため。地図は都道府県ごとの区切りで塗る）
        pooled_pref: dict[tuple[str, bool], list[float]] = defaultdict(list)
        for (_, _, kind), p in periods.items():
            for r in p["rows"].get(("municipality", "municipalities"), []):
                if r["value"] is not None and not (zero_blank and r["value"] == 0):
                    pooled_pref[(prefecture_of(r["entity_id"]), kind == "multi_year")].append(r["value"])
        pref_breaks: dict[bool, dict[str, list[float]]] = defaultdict(dict)
        for (pref, multi), vals in sorted(pooled_pref.items()):
            pref_breaks[multi][pref] = breaks_fn(vals, d["legend"]["classes"], d["digits"])
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
                by_pref = pref_breaks.get(kind == "multi_year", {})
                if level == "municipality" and len(by_pref) > 1:
                    legend[level]["by_prefecture"] = by_pref
            for (level, chunk), rows in p["rows"].items():
                _write(out, f"{vdir}/{chunk}.json", {
                    "schema_version": SCHEMA_VERSION, "release_id": release_id,
                    "indicator_id": indicator_id, "period": pid, "level": level,
                    "unit": d["unit"], "boundary_version": boundary_version,
                    "rows": sorted(rows, key=lambda r: r["entity_id"])})
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
            "min_denominator": d.get("min_denominator"), "legend": d["legend"],
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
                    "coord": [round(e["lon"], COORD_DIGITS), round(e["lat"], COORD_DIGITS)],
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
            used.add(r["source_id"])
        _write(out, f"places/{indicator_id}.json", {
            "schema_version": SCHEMA_VERSION, "release_id": release_id,
            "indicator_id": indicator_id, "name": d["name"], "unit": d["unit"],
            "description": d["description"], "method": d["method"], "caveats": d.get("caveats", []),
            "periods": [{"period": p[0], "period_end": p[1], "period_kind": p[2],
                         "label": _period_label(*p)} for p in periods],
            "source_ids": sorted(used),
            "stations": sorted(stations.values(), key=lambda s: s["id"])})
    return used


def export_schools(conn: sqlite3.Connection, catalog: dict[str, dict], out: Path,
                   release_id: str, ok_sources: set[str]) -> set[str]:
    """学校の点（places/<指標>.json）。位置のない学校も一覧には含め、coord を null にする。"""
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
        if not rows:
            continue
        periods = sorted({(r["period_start"], r["period_end"], r["period_kind"]) for r in rows})
        index = {p[0]: i for i, p in enumerate(periods)}
        info = {r["entity_id"]: r for r in conn.execute(
            """SELECT e.entity_id, e.name, e.parent_id, l.lon, l.lat, l.source_id AS loc_source,
                      a.attributes
               FROM entities e LEFT JOIN locations l ON l.entity_id = e.entity_id AND l.role = 'main'
               LEFT JOIN entity_attributes a ON a.entity_id = e.entity_id
               WHERE e.entity_type = 'school'""")}
        schools: dict[str, dict] = {}
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
                    "coord": [round(e["lon"], COORD_DIGITS), round(e["lat"], COORD_DIGITS)] if located else None,
                    "precision": attrs.get("precision") if located else None,
                    "values": [None] * len(periods), "status": [None] * len(periods)}
                if located:
                    used.add(e["loc_source"])
            i = index[r["period_start"]]
            if r["dimension_key"] != "all":
                sc.setdefault("by_grade", {}).setdefault(r["dimension_key"], [None] * len(periods))[i] = r["value"]
                continue
            sc["values"][i] = None if r["value"] is None else round(r["value"])
            sc["status"][i] = r["status"]
            used.add(r["source_id"])
        for sc in schools.values():
            if "by_grade" in sc:
                sc["by_grade"] = {g: [None if v is None else round(v) for v in vals]
                                  for g, vals in sorted(sc["by_grade"].items())}
        _write(out, f"places/{indicator_id}.json", {
            "schema_version": SCHEMA_VERSION, "release_id": release_id,
            "indicator_id": indicator_id, "name": d["name"], "unit": d["unit"],
            "description": d["description"], "method": d["method"], "caveats": d.get("caveats", []),
            "periods": [{"period": p[0], "period_end": p[1], "period_kind": p[2],
                         "label": _period_label(*p)} for p in periods],
            "source_ids": sorted(used),
            "schools": sorted(schools.values(), key=lambda s: s["id"])})
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
        for r in rows:
            e = info.get(r["entity_id"])
            if e is None or e["loc_source"] not in ok_sources:
                continue
            pt = points.get(r["entity_id"])
            if pt is None:
                attrs = json.loads(e["attributes"] or "{}")
                pt = points[r["entity_id"]] = {
                    "id": r["entity_id"], "name": e["name"], "municipality_id": e["parent_id"],
                    "coord": [round(e["lon"], COORD_DIGITS), round(e["lat"], COORD_DIGITS)],
                    **{k: attrs.get(k) for k in ("use", "use_label", "address", "residential_address",
                                                 "area_m2", "current_use", "station", "station_distance_m",
                                                 "zoning", "change_rate")},
                    "values": [None] * len(periods)}
                used.add(e["loc_source"])
            pt["values"][index[r["period_start"]]] = None if r["value"] is None else round(r["value"])
            used.add(r["source_id"])
        _write(out, f"places/{indicator_id}.json", {
            "schema_version": SCHEMA_VERSION, "release_id": release_id,
            "indicator_id": indicator_id, "name": d["name"], "unit": d["unit"],
            "description": d["description"], "method": d["method"], "caveats": d.get("caveats", []),
            "periods": [{"period": p[0], "period_end": p[1], "period_kind": p[2],
                         "label": _period_label(*p)} for p in periods],
            "source_ids": sorted(used),
            "points": sorted(points.values(), key=lambda s: s["id"])})
    return used


def export_nurseries(conn: sqlite3.Connection, catalog: dict[str, dict], out: Path,
                     release_id: str, ok_sources: set[str]) -> set[str]:
    """認可保育所の点（places/<指標>.json）。位置のない施設も一覧には含め、coord を null にする。"""
    used: set[str] = set()
    for indicator_id, d in catalog.items():
        if "nursery" not in d.get("levels", []):
            continue
        rows = conn.execute(
            """SELECT o.entity_id, o.period_start, o.period_end, o.period_kind, o.value, o.source_id
               FROM observations o JOIN entities e ON e.entity_id = o.entity_id
               WHERE e.entity_type = 'nursery' AND o.indicator_id = ? AND o.definition_version = ?
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
               FROM entities e LEFT JOIN locations l ON l.entity_id = e.entity_id AND l.role = 'main'
               LEFT JOIN entity_attributes a ON a.entity_id = e.entity_id
               WHERE e.entity_type = 'nursery'""")}
        points: dict[str, dict] = {}
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
                    "founder": attrs.get("founder", ""), "address": attrs.get("address"),
                    "coord": [round(e["lon"], COORD_DIGITS), round(e["lat"], COORD_DIGITS)] if located else None,
                    "precision": attrs.get("precision") if located else None,
                    "values": [None] * len(periods)}
                if located:
                    used.add(e["loc_source"])
            pt["values"][index[r["period_start"]]] = None if r["value"] is None else round(r["value"])
            used.add(r["source_id"])
        _write(out, f"places/{indicator_id}.json", {
            "schema_version": SCHEMA_VERSION, "release_id": release_id,
            "indicator_id": indicator_id, "name": d["name"], "unit": d["unit"],
            "description": d["description"], "method": d["method"], "caveats": d.get("caveats", []),
            "periods": [{"period": p[0], "period_end": p[1], "period_kind": p[2],
                         "label": _period_label(*p)} for p in periods],
            "source_ids": sorted(used),
            "points": sorted(points.values(), key=lambda s: s["id"])})
    return used


def _default_period(period_meta: list[dict], levels: list[str]) -> str:
    """最初に表示する時点。町丁・字等まである指標は、町丁・字等の値がある最新の時点にする
    （国勢調査の速報のように区市町村だけの新しい時点は、スライドバーで選べるようにするだけ）。"""
    annual = [p for p in period_meta if not p["aggregate"]]
    if "small_area" in levels:
        fine = [p for p in annual if "small_area" in p["levels"]]
        if fine:
            return fine[-1]["period"]
    return annual[-1]["period"]


def _add_prefecture_rows(rows: dict, d: dict, munis_by_pref: dict[str, list]) -> None:
    """区市町村の値を都道府県ごとに合計して、都道府県の値を作る（出典に都道府県の値があればそちらを使う）。

    割合などは分子・分母をそれぞれ合計して計算し、人数・件数は値を合計する。1つでも値のない区市町村が
    ある都道府県は、欠けた分を0とみなすことになるので値なしにする。合計できない指標（平均など分子・分母の
    ない値）は作らない。"""
    munis = {r["entity_id"]: r for r in rows.get(("municipality", "municipalities"), [])}
    if not munis:
        return
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
        if any(r is None or r["value"] is None for r in got):
            out.append({"entity_id": pid, "value": None, "status": "missing",
                        "note": "値のない市区町村があるため、都道府県の値は出していません"})
            continue
        if all("numerator" in r for r in got):
            num = sum(r["numerator"] for r in got)
            den = sum(r["denominator"] for r in got)
            if not den:
                out.append({"entity_id": pid, "value": None, "status": "missing"})
                continue
            out.append({"entity_id": pid, "value": round(num / den * scale, d["digits"] + 2),
                        "status": "derived", "numerator": round(num, 4), "denominator": round(den, 4),
                        "note": "市区町村の分子・分母を合計して計算"})
        elif d["kind"] == "count":
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
        # 町丁目を開くとき: その区市町村の境界・地域一覧と、都道府県の値・区市町村界（細かい版）
        pref = code[:2]
        values = by_path.get(f"values/{default[0]}/{default[1]}/{pref}.json", 0) if default else 0
        per_area[code] = (b + by_path.get(f"areas/{code}.json", 0) + values
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
