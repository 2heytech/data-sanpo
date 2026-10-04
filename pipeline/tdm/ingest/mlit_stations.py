"""国土数値情報「駅別乗降客数データ」（S12、GeoJSON）を取り込む。

形式（S12-25、2026-10-03 に GitHub Actions から取得し、製品仕様書 第3.3版と照合）:
  1地物が駅のホームを表す線。S12_001 駅名、S12_001c 駅コード、S12_001g グループコード
  （300m以内の同名駅をまとめた番号）、S12_002 運営会社、S12_003 路線名。
  2011年度から1年度ごとに4項目が続く（S12_006〜: 重複コード、データ有無コード、備考、乗降客数）。
  重複コード 1=当該路線駅に記載、2=他路線駅に記載（値は別の路線の行に含まれ、この行は0）。
  データ有無コード 1=あり、2=なし（無人駅など）、3=非公開、4=駅なし。
  同じ駅コードの地物が複数あることがある（ホームが分かれている）。

事業者ごとに別の駅として扱い（設計書 第8章）、地域IDは 300m 以内の同名駅のグループ＋事業者。
同じ事業者で値のある路線が複数あるときは路線別の値を内訳として残し、合計を駅の値にする。
値が別の路線・事業者の行に含まれる駅は、0 や推計にせず「含めて公表」と表示する
（docs/design-changes.md #33）。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from ..db import insert_observation, upsert_entity
from ..regions import prefecture_of

FIRST_YEAR = 2011
FIRST_FIELD = 6          # S12_006 が 2011年度の重複コード
NEAR_DEGREES = 0.002     # 約200m。海沿いなどで境界のわずかに外にある駅を最寄りの区市町村に含める

DUP_HERE = 1
HAS_DATA, NO_DATA, NOT_PUBLIC, NO_STATION = 1, 2, 3, 4

NOTE_INCLUDED = "同じ駅の別の路線の人数に含めて公表されています"
NOTE_NO_DATA = "事業者の資料に人数が載っていません（無人駅など）"
NOTE_NOT_PUBLIC = "事業者が人数を公表していません"


def entity_id_of(group_code: str, operator: str) -> str:
    return f"station-{group_code}-{hashlib.sha1(operator.encode()).hexdigest()[:6]}"


def year_fields(props: dict) -> dict[int, tuple[str, str, str, str]]:
    """年度 → (重複コード, データ有無コード, 備考, 乗降客数) の項目名。"""
    out = {}
    year = FIRST_YEAR
    while f"S12_{FIRST_FIELD + 4 * (year - FIRST_YEAR) + 3:03d}" in props:
        base = FIRST_FIELD + 4 * (year - FIRST_YEAR)
        out[year] = tuple(f"S12_{base + i:03d}" for i in range(4))
        year += 1
    return out


@dataclass
class Line:
    """1事業者・1駅コード（路線）の年度別の値。同じ駅コードの地物は1つにまとめる。"""
    name: str
    code: str
    records: dict[int, tuple[int, int, str | None, int | None]] = field(default_factory=dict)


@dataclass
class Station:
    entity_id: str
    name: str
    operator: str
    group_code: str
    points: list[tuple[float, float]] = field(default_factory=list)
    lines: dict[str, Line] = field(default_factory=dict)


def read_stations(path: Path) -> tuple[dict[str, Station], list[int]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    feats = data["features"]
    years = year_fields(feats[0]["properties"]) if feats else {}
    stations: dict[str, Station] = {}
    for f in feats:
        p = f["properties"]
        group = p.get("S12_001g") or p.get("S12_001c")
        if not group:
            continue
        operator = p["S12_002"]
        eid = entity_id_of(group, operator)
        st = stations.setdefault(eid, Station(eid, p["S12_001"], operator, group))
        c = shape(f["geometry"]).interpolate(0.5, normalized=True)
        st.points.append((c.x, c.y))
        code = p.get("S12_001c") or group
        line = st.lines.setdefault(code, Line(p["S12_003"], code))
        for y, (dup, has, note, value) in years.items():
            rec = (int(p[dup] or 0), int(p[has] or 0), p[note], p[value])
            # 同じ駅コードの地物が複数あるときは、値を記載した行（重複コード1）を優先する
            if y not in line.records or (rec[0] == DUP_HERE and line.records[y][0] != DUP_HERE):
                line.records[y] = rec
    return stations, sorted(years)


def _municipality_index(conn: sqlite3.Connection, boundary_version: str, prefs: list[str] | None = None):
    rows = conn.execute(
        """SELECT b.entity_id, b.geometry FROM boundaries b
           JOIN entities e ON e.entity_id = b.entity_id AND e.entity_type = 'municipality'
           WHERE b.boundary_version = ?""", (boundary_version,)).fetchall()
    rows = [r for r in rows if prefs is None or prefecture_of(r["entity_id"]) in prefs]
    ids = [r["entity_id"] for r in rows]
    geoms = [shape(json.loads(r["geometry"])) for r in rows]
    return ids, geoms, STRtree(geoms)


def _municipality_of(point: Point, ids, geoms, tree) -> str | None:
    hits = [i for i in tree.query(point, predicate="intersects")]
    if hits:
        return ids[hits[0]]
    near = tree.query(point.buffer(NEAR_DEGREES), predicate="intersects")
    if len(near):
        return ids[min(near, key=lambda i: geoms[i].distance(point))]
    return None


def _included_in(st: Station, line: Line, year: int, group: list[Station]) -> str | None:
    """値が含まれている路線（同じグループか同じ事業者の同名駅で、備考にこの路線名を挙げている行）を探す。"""
    for other in group:
        for ol in other.lines.values():
            rec = ol.records.get(year)
            if rec and rec[0] == DUP_HERE and rec[1] == HAS_DATA and rec[2] and line.name in rec[2]:
                return ol.name if other.operator == st.operator else f"{other.operator} {ol.name}"
    return None


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, indicator_id: str,
           definition: dict, boundary_version: str, prefs: list[str] | None = None) -> dict:
    stations, years = read_stations(path)
    ids, geoms, tree = _municipality_index(conn, boundary_version, prefs)
    by_group: dict[str, list[Station]] = defaultdict(list)
    result = {"stations": 0, "outside": 0, "observed": 0, "summed_lines": 0}
    for st in stations.values():
        lon = sum(x for x, _ in st.points) / len(st.points)
        lat = sum(y for _, y in st.points) / len(st.points)
        muni = _municipality_of(Point(lon, lat), ids, geoms, tree)
        if muni is None:
            result["outside"] += 1
            continue
        upsert_entity(conn, st.entity_id, "station", st.name, parent_id=muni)
        conn.execute(
            """INSERT INTO locations (location_id, entity_id, role, lon, lat, source_id)
               VALUES (?, ?, 'main', ?, ?, ?)
               ON CONFLICT(location_id) DO UPDATE SET lon = excluded.lon, lat = excluded.lat,
                 source_id = excluded.source_id""",
            (f"{st.entity_id}:main", st.entity_id, round(lon, 6), round(lat, 6), source_id))
        conn.execute(
            """INSERT INTO entity_attributes (entity_id, attributes) VALUES (?, ?)
               ON CONFLICT(entity_id) DO UPDATE SET attributes = excluded.attributes""",
            (st.entity_id, json.dumps({
                "operator": st.operator, "group": st.group_code,
                "lines": sorted({ln.name for ln in st.lines.values()})}, ensure_ascii=False)))
        by_group[st.group_code].append(st)
        result["stations"] += 1

    # 300m より離れたホーム（例: 東京駅の京葉線）は別のグループになるので、同じ事業者の同名駅も候補にする
    same_name: dict[tuple[str, str], list[Station]] = defaultdict(list)
    for group in by_group.values():
        for st in group:
            same_name[(st.operator, st.name)].append(st)
    for group in by_group.values():
        for st in group:
            candidates = group + [s for s in same_name[(st.operator, st.name)] if s not in group]
            for y in years:
                result["observed"] += _insert_year(conn, st, y, candidates, source_id, indicator_id,
                                                   definition, result)
    return result


def _insert_year(conn, st: Station, y: int, group: list[Station], source_id: str,
                 indicator_id: str, definition: dict, result: dict) -> int:
    base = dict(entity_id=st.entity_id, indicator_id=indicator_id,
                definition_version=definition["definition_version"],
                period_start=f"{y}-04-01", period_end=f"{y + 1}-03-31", period_kind="fiscal_year",
                source_id=source_id)
    recs = [(ln, ln.records[y]) for ln in sorted(st.lines.values(), key=lambda ln: ln.code)
            if y in ln.records]
    valued = [(ln, r) for ln, r in recs if r[0] == DUP_HERE and r[1] == HAS_DATA and r[3] is not None]
    if valued:
        notes = [r[2] for _, r in valued if r[2]]
        method = None
        if len(valued) > 1:
            # 路線別の内訳を残す（同じ事業者の別の路線の行で、重複コード1どうし）
            for ln, r in valued:
                insert_observation(conn, **base, dimension_key=ln.name, value=float(r[3]),
                                   status="observed")
            method = "同じ事業者の路線別の値（" + "・".join(ln.name for ln, _ in valued) + "）の合計"
            result["summed_lines"] += 1
        insert_observation(conn, **base, value=float(sum(r[3] for _, r in valued)), status="observed",
                           coverage_note="、".join(notes) or None, method_note=method)
        return 1
    has = {r[1] for _, r in recs}
    if any(r[1] == HAS_DATA for _, r in recs):
        where = next((w for ln, r in recs if r[1] == HAS_DATA
                      for w in [_included_in(st, ln, y, group)] if w), None)
        insert_observation(conn, **base, value=None, status="not_applicable",
                           coverage_note=NOTE_INCLUDED + (f"（{where}）" if where else ""))
    elif NOT_PUBLIC in has:
        insert_observation(conn, **base, value=None, status="suppressed", coverage_note=NOTE_NOT_PUBLIC)
    elif NO_DATA in has:
        insert_observation(conn, **base, value=None, status="missing", coverage_note=NOTE_NO_DATA)
    # 駅なし（開業前・廃止後）の年度は行を作らない
    return 0
