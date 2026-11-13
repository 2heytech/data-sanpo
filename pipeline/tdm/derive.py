"""観測値から別の指標を計算する（人口密度など）。"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import statistics
from collections import defaultdict

from .db import insert_observation
from .regions import prefecture_entity_id


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
    """区市町村の分母を都道府県ごとに合計して den に加える（都道府県の分母が元からあればそのまま）。
    分母の指標にどの時点の行もない区市町村（ほかの出典が作った、今はない市区町村や政令指定都市の市全体など）は
    数えない。そうしないと東京都・愛知県・福岡県のように、そうした地域がある都道府県の分母が作られない。"""
    with_rows = {e for e, _ in den}
    munis: dict[str, list[str]] = defaultdict(list)
    for entity_id, t in types.items():
        if t == "municipality" and entity_id in with_rows:
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
    denominator_period = "same_year" なら分子と同じ年に始まる時点の分母を使う（例: 2025年度の住民税の納税者 ÷
    2025年1月1日の住民基本台帳の人口）。
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
    same_period = definition["denominator_period"] in ("same", "same_year")
    key_len = 4 if definition["denominator_period"] == "same_year" else None

    def key(period_start: str) -> str | None:
        return period_start[:key_len] if same_period else None

    den = {(r["entity_id"], key(r["period_start"])): r for r in conn.execute(
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
        d = den.get((r["entity_id"], key(r["period_start"])))
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


_KANJI_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _kanji_number(s: str) -> int:
    """「二十三」→ 23（丁目の番号だけなので九十九まで）"""
    tens, _, ones = s.partition("十") if "十" in s else ("", "", s)
    return ((_KANJI_DIGITS[tens] if tens else 1) * 10 if "十" in s else 0) + (_KANJI_DIGITS.get(ones, 0) if ones else 0)


def normalize_land_address(address: str | None) -> str:
    """所在地を比べるための形にする（数字を半角に、漢数字の丁目を数字に、空白を除く）。
    地価調査は「新富一丁目５番１」、地価公示は「新富１丁目５番１」のように書き方が違うことがある。
    地図の web/src/map/landprices.ts の normalizeLandAddress と同じ。"""
    if not address:
        return ""
    a = re.sub(r"\s", "", address.translate(str.maketrans("０１２３４５６７８９", "0123456789")))
    return re.sub(r"([一二三四五六七八九十]+)丁目", lambda m: f"{_kanji_number(m.group(1))}丁目", a)


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = (a[0] - b[0]) * math.cos(math.radians(a[1])) * 111_320
    dy = (a[1] - b[1]) * 110_540
    return math.hypot(dx, dy)


def pair_land_points(publics: list[dict], surveys: list[dict], max_m: float = 100) -> dict[str, str]:
    """地価公示の標準地と同じ土地を調べている地価調査の基準地（共通地点）。基準地のID → 標準地のID。
    公開データに共通地点の印がないので、位置が同じか、所在地が同じで max_m 以内のものを同じ土地とみなす
    （地図の web/src/map/landprices.ts の pairLandPoints と同じ決まり。#134）。
    点は {"id", "coord": (経度, 緯度), "address"}。"""
    by_coord = {p["coord"]: p for p in publics}
    by_address: dict[str, list[dict]] = defaultdict(list)
    for p in publics:
        a = normalize_land_address(p["address"])
        if a:
            by_address[a].append(p)
    used: set[str] = set()
    out: dict[str, str] = {}
    for s in surveys:
        near = sorted((p for p in by_address.get(normalize_land_address(s["address"]), [])
                       if _distance_m(p["coord"], s["coord"]) <= max_m),
                      key=lambda p: _distance_m(p["coord"], s["coord"]))
        hit = next((p for p in [by_coord.get(s["coord"]), *near] if p and p["id"] not in used), None)
        if hit:
            used.add(hit["id"])
            out[s["id"]] = hit["id"]
    return out


def derive_land_median(conn: sqlite3.Connection, indicator_id: str, definition: dict,
                       catalog: dict[str, dict]) -> dict[str, int]:
    """地価公示・都道府県地価調査の地点の価格を、市区町村・都道府県ごとの中央値にまとめる（#137）。

    各年1月1日の地価公示の価格に、前年7月1日の地価調査の価格（1月1日の時点でわかっている最新の価格）を合わせる。
    共通地点（pair_land_points）は地価公示の価格だけを使い、2回数えない。用途（住宅地・商業地）は land_median.use。
    地点が min_points 未満の地域は値を出さない（withheld）。地点のない市区町村は値なし（missing）。
    元データには今ある地点の過去の価格しかなく、古い年ほど地点が少ないため、地点の数が最新の年の min_share に
    満たない年は作らない（値が価格の動きより地点の入れ替わりで動くため）。
    """
    cfg = definition["land_median"]
    use, use_label = cfg["use"], cfg["use_label"]
    min_points = int(cfg.get("min_points", 3))
    min_share = float(cfg.get("min_share", 0.8))
    points: dict[str, dict] = {}
    for r in conn.execute(
            """SELECT e.entity_id, e.parent_id, a.attributes, l.lon, l.lat FROM entities e
               JOIN entity_attributes a ON a.entity_id = e.entity_id
               JOIN locations l ON l.entity_id = e.entity_id AND l.role = 'main'
               WHERE e.entity_type = 'land_point'"""):
        attrs = json.loads(r["attributes"])
        if attrs.get("use") == use:
            points[r["entity_id"]] = {"id": r["entity_id"], "muni": r["parent_id"], "coord": (r["lon"], r["lat"]),
                                      "address": attrs.get("address")}

    def values(source_indicator: str) -> tuple[dict[tuple[str, str], float], set[str]]:
        d = catalog[source_indicator]
        out, sources = {}, set()
        for r in conn.execute(
                """SELECT entity_id, period_start, value, source_id FROM observations
                   WHERE indicator_id = ? AND definition_version = ? AND value IS NOT NULL""",
                (source_indicator, d["definition_version"])):
            if r["entity_id"] in points:
                out[(r["entity_id"], r["period_start"])] = r["value"]
                sources.add(r["source_id"])
        return out, sources

    pub, pub_sources = values(cfg["public"])
    sur, sur_sources = values(cfg["survey"])
    if not pub:
        return {}
    pub_ids = {e for e, _ in pub}
    sur_ids = {e for e, _ in sur}
    pairs = pair_land_points([points[i] for i in sorted(pub_ids)], [points[i] for i in sorted(sur_ids)])
    pub_by_period: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (e, p), v in pub.items():
        pub_by_period[p].append((points[e]["muni"], v))
    years = sorted({int(p[:4]) for p in pub_by_period})
    by_year: dict[int, list[tuple[str, float]]] = {}
    for y in years:
        got = list(pub_by_period.get(f"{y}-01-01", []))
        for s in sur_ids:
            v = sur.get((s, f"{y - 1}-07-01"))
            if v is None or (s in pairs and (pairs[s], f"{y}-01-01") in pub):
                continue   # 共通地点は、その年の地価公示の価格があればそちらを使う
            got.append((points[s]["muni"], v))
        by_year[y] = got
    latest = len(by_year[years[-1]])
    munis = [r["entity_id"] for r in conn.execute(
        "SELECT entity_id FROM entities WHERE entity_type = 'municipality' ORDER BY entity_id")]
    prefs = sorted({m.split("-", 1)[1][:2] for m in (p["muni"] for p in points.values()) if m})
    munis = [m for m in munis if m.split("-", 1)[1][:2] in prefs]
    source_id = sorted(pub_sources)[0]
    survey_source = sorted(sur_sources)[0] if sur_sources else None
    result: dict[str, int] = {}
    for y, got in by_year.items():
        if len(got) < min_share * latest:
            continue
        groups: dict[str, list[float]] = defaultdict(list)
        for muni, v in got:
            groups[muni].append(v)
            groups[prefecture_entity_id(muni.split("-", 1)[1][:2])].append(v)
        for entity_id in munis + [prefecture_entity_id(p) for p in prefs]:
            vals = groups.get(entity_id, [])
            obs = dict(entity_id=entity_id, indicator_id=indicator_id,
                       definition_version=definition["definition_version"],
                       period_start=f"{y}-01-01", period_end=f"{y}-01-01", period_kind="point",
                       source_id=source_id, denominator_source_id=survey_source)
            if len(vals) >= min_points:
                obs.update(value=statistics.median(vals), status="derived", method_note=f"{len(vals)}地点の中央値")
            elif vals:
                obs.update(value=None, status="withheld",
                           method_note=f"{use_label}の地点が{len(vals)}つのため出していません（{min_points}地点以上の地域だけ）")
            else:
                obs.update(value=None, status="missing", method_note=f"{use_label}の地点がありません")
            insert_observation(conn, **obs)
        result[str(y)] = sum(1 for e in munis if len(groups.get(e, [])) >= min_points)
    return result
