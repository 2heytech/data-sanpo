"""過去の国勢調査（2010・2015年）の市区町村の値を、地図の市区町村（最新の境界）の区域に組み替える（design-changes #125）。

当時の市区町村の値をそのまま地図の市区町村に付けると、その後に町村を編入した市は古い年の区域が狭く
（川口市の2010年に、2011年に編入した鳩ヶ谷市の分がない）、増減率や都道府県の合計が誤る。町村が市になって
コードが変わった市区町村（滝沢村→滝沢市など）は、地図のコードに当時の行がなく値がない。

当時の境界と最新の境界を重ね、当時の市区町村を、その面積の95%以上が入る最新の市区町村に丸ごと足す。
- 当時の市区町村より細かくは割り振らない。のちに複数の市区町村に分かれた区域（2010年の熊本市と、2012年に
  できた5区など）は、どこにも足さず、分かれた先の市区町村は値なしにする。
- 足す当時の市区町村の面積の合計と、最新の面積の差が5%を超える市区町村は、区域が合わないので値なしにする
  （町丁・字等を過去の時点と比べるときと同じ基準。#20）。
- 人口のない区域（2010年の東京都の所属未定地など）は、値を足さず、分かれていても値なしの理由にしない。
- 割合・人口密度は分子・分母をそれぞれ足して計算し、人数は値を足す。1つでも値のない当時の市区町村があれば値なし。
- 当時と同じコードで区域が変わっていない市区町村は、そのまま。
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

from .db import insert_observation, load_geometry

WHOLE_SHARE = 0.95       # 当時の市区町村の面積のうち、これ以上が入る最新の市区町村に足す
PART_SHARE = 0.05        # 分かれた区域が、これ以上入る最新の市区町村は値なしにする
AREA_DIFF = 0.05         # 足した面積と最新の面積の差がこれを超えたら値なし（町丁・字等と同じ。#20）
POPULATION = "population_total"
OK_STATUSES = {"observed", "derived", "estimated"}
NOTE_BROKEN = "その後の市区町村の分割・境界の変更で区域が合わないため値なし"
NOTE_PARTIAL = "編入前の市町村の一部に値がないため値なし"
NOTE_SECRET = "編入前の市町村の一部が秘匿のため値なし"


@dataclass
class Lineage:
    """最新の市区町村 → 足す当時の市区町村（自分を含む）と、値なしにする最新の市区町村。"""
    members: dict[str, list[str]] = field(default_factory=dict)
    broken: set[str] = field(default_factory=set)
    names: dict[str, str] = field(default_factory=dict)


def _munis(conn: sqlite3.Connection, version: str) -> dict[str, sqlite3.Row]:
    return {r["entity_id"]: r for r in conn.execute(
        """SELECT b.entity_id, b.boundary_id, b.area_m2, b.bbox_west, b.bbox_south, b.bbox_east, b.bbox_north,
                  e.name
           FROM boundaries b JOIN entities e ON e.entity_id = b.entity_id AND e.entity_type = 'municipality'
           WHERE b.boundary_version = ?""", (version,))}


def _geometry(conn: sqlite3.Connection, boundary_id: str):
    geom = load_geometry(conn.execute("SELECT geometry FROM boundaries WHERE boundary_id = ?",
                                      (boundary_id,)).fetchone()[0])
    return geom if geom.is_valid else geom.buffer(0)


def _populated(conn: sqlite3.Connection, period: str) -> set[str]:
    """その時点に人口がある（または秘匿などで分からない）市区町村。人口の値がない区域は足さない。"""
    return {r["entity_id"] for r in conn.execute(
        """SELECT entity_id, value FROM observations
           WHERE indicator_id = ? AND period_start = ? AND dimension_key = 'all' AND entity_id LIKE 'muni-%'""",
        (POPULATION, period)) if r["value"] is None or r["value"] > 0}


def municipality_lineage(conn: sqlite3.Connection, old_version: str, new_version: str, period: str) -> Lineage:
    old, new = _munis(conn, old_version), _munis(conn, new_version)
    populated = _populated(conn, period)
    out = Lineage(names={k: r["name"] for k, r in {**old, **new}.items()})
    assigned: dict[str, list[str]] = defaultdict(list)
    new_geoms: dict[str, object] = {}
    for oid, o in old.items():
        if oid in new:
            assigned[oid].append(oid)   # 同じコードの市区町村は、区域が広がっていても自分に足す
            continue
        geom = _geometry(conn, o["boundary_id"])
        if geom.is_empty or geom.area <= 0:
            continue
        shares: dict[str, float] = {}
        for nid, n in new.items():
            if (n["bbox_west"] > o["bbox_east"] or n["bbox_east"] < o["bbox_west"]
                    or n["bbox_south"] > o["bbox_north"] or n["bbox_north"] < o["bbox_south"]):
                continue
            if nid not in new_geoms:
                new_geoms[nid] = _geometry(conn, n["boundary_id"])
            share = geom.intersection(new_geoms[nid]).area / geom.area
            if share > 0:
                shares[nid] = share
        best = max(shares, key=shares.get, default=None)
        if best is not None and shares[best] >= WHOLE_SHARE:
            assigned[best].append(oid)
        elif oid in populated:
            # 当時の市区町村が、のちに複数に分かれた（細かく割り振らない）
            out.broken |= {nid for nid, s in shares.items() if s >= PART_SHARE}
    for nid, n in new.items():
        members = assigned.get(nid, [])
        with_values = [m for m in members if m in populated]
        if not with_values or with_values == [nid]:
            continue   # 当時と同じ区域（または当時の値がない）
        area = sum(old[m]["area_m2"] or 0 for m in members)
        if nid in out.broken or not n["area_m2"] or abs(area - n["area_m2"]) / n["area_m2"] > AREA_DIFF:
            out.broken.add(nid)
            continue
        out.members[nid] = with_values
    return out


def _compose(rows: list[sqlite3.Row], definition: dict) -> dict:
    """当時の市区町村の観測値を足して、最新の市区町村の値にする。"""
    if all(r["numerator"] is not None and r["denominator"] is not None for r in rows):
        num = sum(r["numerator"] for r in rows)
        den = sum(r["denominator"] for r in rows)
        min_den = float(definition.get("min_denominator", 0))
        if den <= 0:
            return dict(value=None, status="not_applicable", numerator=num, denominator=den,
                        method_note="分母が0のため算出しない")
        if den < min_den:
            return dict(value=None, status="withheld", numerator=num, denominator=den,
                        method_note=f"分母が{min_den:g}未満のため非表示")
        return dict(value=num / den * float(definition.get("scale", 1)), status="derived",
                    numerator=num, denominator=den)
    if definition["kind"] == "count" and all(r["value"] is not None and r["status"] in OK_STATUSES for r in rows):
        return dict(value=sum(r["value"] for r in rows), status="derived")
    if any(r["status"] == "suppressed" for r in rows):
        return dict(value=None, status="suppressed", method_note=NOTE_SECRET)
    return dict(value=None, status="missing", method_note=NOTE_PARTIAL)


def regroup_municipalities(conn: sqlite3.Connection, catalog: dict[str, dict], census: dict,
                           new_version: str) -> dict:
    """census（過去の国勢調査の1時点）の市区町村の観測値を、最新の境界の市区町村の区域に組み替える。"""
    period = census["period"]
    lineage = municipality_lineage(conn, census["boundary_version"], new_version, period)
    if not lineage.members and not lineage.broken:
        return {"組み替えた市区町村": 0}
    groups: dict[tuple, dict[str, sqlite3.Row]] = defaultdict(dict)
    for r in conn.execute(
            """SELECT * FROM observations WHERE period_start = ? AND entity_id LIKE 'muni-%'""", (period,)):
        groups[(r["indicator_id"], r["definition_version"], r["dimension_key"])][r["entity_id"]] = r
    label = lambda m: lineage.names.get(m) or m  # noqa: E731
    written = 0

    def note(members: list[str]) -> str:
        if len(members) == 1:
            return f"{census['label']}の{label(members[0])}の値（今の区域と同じ）"
        return f"{census['label']}の値を今の区域に組み替え（{'・'.join(label(m) for m in members)}の合計）"

    for (indicator_id, version, dim), by_entity in groups.items():
        d = catalog.get(indicator_id)
        if d is None:
            continue
        for nid, members in lineage.members.items():
            got = [by_entity.get(m) for m in members]
            if all(r is None for r in got):
                continue   # この指標に当時の市区町村の値がない
            base = by_entity.get(nid) or next(r for r in got if r is not None)
            notes = sorted({r["coverage_note"] for r in got if r is not None and r["coverage_note"]})
            obs = dict(entity_id=nid, indicator_id=indicator_id, definition_version=version,
                       period_start=base["period_start"], period_end=base["period_end"],
                       period_kind=base["period_kind"], source_id=base["source_id"], dimension_key=dim,
                       denominator_source_id=base["denominator_source_id"],
                       coverage_note="。".join(notes) or None, method_note=note(members))
            if any(r is None for r in got):
                obs.update(value=None, status="missing", method_note=NOTE_PARTIAL)
            else:
                composed = _compose(got, d)
                obs.update({**composed, "method_note": composed.get("method_note", obs["method_note"])})
            insert_observation(conn, **obs)
            written += 1
        for nid in lineage.broken:
            r = by_entity.get(nid)
            if r is None or r["value"] is None:
                continue
            insert_observation(conn, entity_id=nid, indicator_id=indicator_id, definition_version=version,
                               period_start=r["period_start"], period_end=r["period_end"],
                               period_kind=r["period_kind"], source_id=r["source_id"], dimension_key=dim,
                               value=None, status="missing", method_note=NOTE_BROKEN)
            written += 1
    return {"組み替えた市区町村": len(lineage.members), "値なしにした市区町村": len(lineage.broken),
            "観測値": written,
            "組み替え": [f"{label(n)} ← {'・'.join(label(m) for m in ms)}" for n, ms in sorted(lineage.members.items())],
            "値なし": sorted(label(n) for n in lineage.broken)}
