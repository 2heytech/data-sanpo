"""観測値から別の指標を計算する（人口密度など）。"""
from __future__ import annotations

import sqlite3
from collections import defaultdict

from .db import insert_observation


def derive_density(conn: sqlite3.Connection, indicator_id: str, definition: dict,
                   numerator_definition: dict, boundary_version: str, period_start: str) -> int:
    """period_start 時点の分子を、同じ時点の境界（boundary_version）の面積で割る。"""
    rows = conn.execute(
        """SELECT o.entity_id, o.period_start, o.period_end, o.period_kind, o.value, o.status,
                  o.source_id, o.coverage_note, b.boundary_id, b.area_m2,
                  b.source_id AS boundary_source
           FROM observations o
           JOIN boundaries b ON b.entity_id = o.entity_id AND b.boundary_version = ?
           WHERE o.indicator_id = ? AND o.definition_version = ? AND o.dimension_key = 'all'
             AND o.period_start = ?""",
        (boundary_version, definition["numerator"], numerator_definition["definition_version"],
         period_start),
    ).fetchall()
    for r in rows:
        obs = dict(entity_id=r["entity_id"], indicator_id=indicator_id,
                   definition_version=definition["definition_version"],
                   period_start=r["period_start"], period_end=r["period_end"],
                   period_kind=r["period_kind"], source_id=r["source_id"],
                   denominator_source_id=r["boundary_source"], boundary_id=r["boundary_id"],
                   coverage_note=r["coverage_note"])
        area_km2 = (r["area_m2"] or 0) / 1_000_000
        if r["value"] is None:
            obs.update(value=None, status=r["status"])
        elif area_km2 <= 0:
            obs.update(value=None, status="not_applicable", method_note="面積が不明のため算出しない")
        else:
            obs.update(value=r["value"] / area_km2, numerator=r["value"], denominator=area_km2,
                       status="derived")
        insert_observation(conn, **obs)
    return len(rows)


def derive_change(conn: sqlite3.Connection, indicator_id: str, definition: dict,
                  base_definition: dict, censuses: list[dict],
                  comparable: dict[str, set[str]]) -> dict[str, int]:
    """前回の国勢調査からの増減率（(今回 − 前回) ÷ 前回 × scale）。

    町丁・字等は、両時点とも最新の境界と比べられる（comparable、最新の時点は常に可）地域だけ
    計算する。秘匿の合算の扱いが両時点で異なる地域も比べない。
    """
    scale = float(definition.get("scale", 1))
    min_den = float(definition.get("min_denominator", 0))
    types = {r["entity_id"]: r["entity_type"] for r in conn.execute(
        "SELECT entity_id, entity_type FROM entities")}
    latest = censuses[-1]["period"]

    def values(period: str) -> dict[str, sqlite3.Row]:
        return {r["entity_id"]: r for r in conn.execute(
            """SELECT * FROM observations
               WHERE indicator_id = ? AND definition_version = ? AND dimension_key = 'all'
                 AND period_start = ?""",
            (definition["base"], base_definition["definition_version"], period))}

    def comparable_at(period: str, entity_id: str) -> bool:
        return (period == latest or types.get(entity_id) != "small_area"
                or entity_id in comparable.get(period, set()))

    result: dict[str, int] = {}
    for prev_census, census in zip(censuses, censuses[1:]):
        prev, cur = values(prev_census["period"]), values(census["period"])
        if not prev or not cur:
            continue  # 前回の時点が取り込まれていない
        for entity_id, c in cur.items():
            p = prev.get(entity_id)
            if p is None:
                continue  # 前回の時点に存在しない地域（新設など）
            obs = dict(entity_id=entity_id, indicator_id=indicator_id,
                       definition_version=definition["definition_version"],
                       period_start=c["period_start"], period_end=c["period_end"],
                       period_kind=c["period_kind"], source_id=c["source_id"],
                       denominator_source_id=p["source_id"], coverage_note=c["coverage_note"],
                       method_note=None)
            if not (comparable_at(prev_census["period"], entity_id)
                    and comparable_at(census["period"], entity_id)):
                obs.update(value=None, status="not_applicable",
                           method_note=f"{prev_census['label']}と境界が異なるため算出しない")
            elif c["value"] is None or p["value"] is None:
                statuses = {c["status"], p["status"]}
                obs.update(value=None, status="suppressed" if "suppressed" in statuses else "missing")
            elif (c["coverage_note"] or "") != (p["coverage_note"] or ""):
                obs.update(value=None, status="not_applicable",
                           method_note=f"秘匿処理の合算の扱いが{prev_census['label']}と異なるため算出しない")
            else:
                diff = c["value"] - p["value"]
                obs.update(numerator=diff, denominator=p["value"])
                if p["value"] <= 0:
                    obs.update(value=None, status="not_applicable",
                               method_note=f"{prev_census['label']}の値が0のため算出しない")
                elif p["value"] < min_den:
                    obs.update(value=None, status="withheld",
                               method_note=f"{prev_census['label']}の値が{min_den:g}未満のため非表示")
                else:
                    obs.update(value=diff / p["value"] * scale, status="derived")
            insert_observation(conn, **obs)
        result[census["label"]] = len(cur)
    return result


def derive_multi_year_sum(conn: sqlite3.Connection, indicator_id: str, definition: dict,
                          years: int) -> dict[str, int]:
    """年計の直近 years 年分を合計した値（時点の種類は multi_year）。例: 犯罪の認知件数の5年合計。

    年が欠けていればその地域・その合計は出さない（missing）。どれかの年が秘匿なら suppressed。
    年がそろっていない（取り込んだ年が years 年未満）なら作らない。
    """
    rows = conn.execute(
        """SELECT * FROM observations WHERE indicator_id = ? AND definition_version = ?
             AND dimension_key = 'all' AND period_kind = 'calendar_year'""",
        (indicator_id, definition["definition_version"])).fetchall()
    starts = sorted({r["period_start"] for r in rows})[-years:]
    if len(starts) < years:
        return {}
    first, last = starts[0], max(r["period_end"] for r in rows if r["period_start"] == starts[-1])
    by_entity: dict[str, dict[str, sqlite3.Row]] = defaultdict(dict)
    for r in rows:
        if r["period_start"] in starts:
            by_entity[r["entity_id"]][r["period_start"]] = r
    label = f"{first[:4]}〜{last[:4]}年の{years}年分の合計"
    for entity_id, per_year in by_entity.items():
        latest = per_year.get(starts[-1]) or next(iter(per_year.values()))
        obs = dict(entity_id=entity_id, indicator_id=indicator_id,
                   definition_version=definition["definition_version"],
                   period_start=first, period_end=last, period_kind="multi_year",
                   source_id=latest["source_id"], coverage_note=None, method_note=label)
        values = [per_year[s]["value"] if s in per_year else None for s in starts]
        if any(v is None for v in values):
            statuses = {per_year[s]["status"] for s in starts if s in per_year}
            obs.update(value=None, status="suppressed" if "suppressed" in statuses else "missing")
        else:
            obs.update(value=sum(values), status="derived")
        insert_observation(conn, **obs)
    return {label: len(by_entity)}


def _add_prefecture_denominators(den: dict, types: dict[str, str]) -> None:
    """区市町村の分母を都道府県ごとに合計して den に加える（都道府県の分母が元からあればそのまま）。"""
    munis: dict[str, list[str]] = defaultdict(list)
    for entity_id, t in types.items():
        if t == "municipality":
            munis[entity_id.split("-", 1)[1][:2]].append(entity_id)
    periods = {p for _, p in den}
    for pref, members in munis.items():
        pid = f"pref-{pref}"
        for period in periods:
            if (pid, period) in den:
                continue
            rows = [den.get((m, period)) for m in members]
            if any(r is None or r["value"] is None for r in rows):
                continue
            den[(pid, period)] = {"value": sum(r["value"] for r in rows), "status": "derived",
                                  "source_id": rows[0]["source_id"]}


def derive_rate(conn: sqlite3.Connection, indicator_id: str, definition: dict,
                catalog: dict[str, dict]) -> dict[str, int]:
    """別の指標どうしの比（分子の指標 ÷ 分母の指標 × scale）。例: 犯罪の認知件数 ÷ 人口 × 1,000。

    分母は denominator_period の時点の値を全時点に使う（例: 2020年国勢調査の人口）。
    denominator_period = "same" なら分子と同じ時点の分母を使う（例: 各年の昼間人口 ÷ 同じ年の人口）。
    分母が min_denominator 未満なら値を出さない（withheld）。
    levels に prefecture があれば都道府県も計算する。都道府県の分母がなければ、県内の区市町村の分母を合計して
    使う（値のない区市町村が1つでもあれば作らない）。例: ふるさと納税の県内合計 ÷ 県内の人口。
    """
    num_def, den_def = catalog[definition["numerator_indicator"]], catalog[definition["denominator_indicator"]]
    scale = float(definition.get("scale", 1))
    min_den = float(definition.get("min_denominator", 0))
    levels = {lv if lv in ("municipality", "prefecture") else "small_area" for lv in definition["levels"]}
    types = {r["entity_id"]: r["entity_type"] for r in conn.execute(
        "SELECT entity_id, entity_type FROM entities")}
    same_period = definition["denominator_period"] == "same"
    den = {(r["entity_id"], r["period_start"] if same_period else None): r for r in conn.execute(
        """SELECT * FROM observations WHERE indicator_id = ? AND definition_version = ?
             AND dimension_key = 'all' AND (? OR period_start = ?)""",
        (definition["denominator_indicator"], den_def["definition_version"],
         same_period, definition["denominator_period"]))}
    if "prefecture" in levels:
        _add_prefecture_denominators(den, types)
    label = definition.get("denominator_label", "分母")
    result: dict[str, int] = {}
    for r in conn.execute(
            """SELECT * FROM observations WHERE indicator_id = ? AND definition_version = ?
                 AND dimension_key = 'all'""",
            (definition["numerator_indicator"], num_def["definition_version"])).fetchall():
        if types.get(r["entity_id"]) not in levels:
            continue
        d = den.get((r["entity_id"], r["period_start"] if same_period else None))
        if d is None:
            continue  # 分母のない地域（昼間人口は区市町村のみ）
        obs = dict(entity_id=r["entity_id"], indicator_id=indicator_id,
                   definition_version=definition["definition_version"],
                   period_start=r["period_start"], period_end=r["period_end"],
                   period_kind=r["period_kind"], source_id=r["source_id"],
                   denominator_source_id=d["source_id"], coverage_note=r["coverage_note"],
                   method_note=None)
        if r["value"] is None or d["value"] is None:
            statuses = {r["status"], d["status"]}
            obs.update(value=None, status="suppressed" if "suppressed" in statuses else "missing")
        else:
            obs.update(numerator=r["value"], denominator=d["value"])
            if d["value"] <= 0:
                obs.update(value=None, status="not_applicable",
                           method_note=f"{label}が0のため算出しない")
            elif d["value"] < min_den:
                obs.update(value=None, status="withheld",
                           method_note=f"{label}が{min_den:g}未満のため非表示")
            else:
                obs.update(value=r["value"] / d["value"] * scale, status="derived")
        insert_observation(conn, **obs)
        result[r["period_start"][:4]] = result.get(r["period_start"][:4], 0) + 1
    return result
