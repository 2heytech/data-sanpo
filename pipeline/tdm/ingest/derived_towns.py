"""町丁・字等ごとに集計した土地利用・標高（tdm/prepare で作った CSV。docs/design-changes.md #123）を取り込む。

land_use_cells / urban_land_use_cells: 列は「KEY_CODE, 年度, 区分ごとのマスの数…, 範囲外の列」。
  KEY_CODE は2020年国勢調査の小地域境界の地域コード、年度はデータの年度（西暦）。範囲外の列（sources.toml の gap_column）は、
  その年度のデータがない（都市地域では、都市地域の範囲外の）陸のマスの数。
  指標の値は numerator_columns の合計 ÷ denominator_columns の合計 × scale（"*" は範囲外の列を除くすべての区分）。
  市区町村の値は町丁・字等のマスの合計から計算する（都道府県の値は公開ファイルを作るときに市区町村の合計から作る）。
  範囲外のマスが、陸のマスとの合計の MAX_GAP_SHARE を超える地域は値なし（missing）にする。
vegetation_areas（現存植生図、#124）も同じ形で、マスの数の代わりに区分ごとの面積（ha）、範囲外の列は植生図のない面積。
farmland_areas（筆ポリゴン、#124）は「KEY_CODE, 年度, 田, 畑（ha）, 田の区画, 畑の区画（数）, 面積（ha）」で、範囲外の列はない。
town_elevation: 列は「KEY_CODE, 点の数, 標高の合計, 最低, 最高」（標高タイルの画素の数と標高）。
  elevation_value = "mean" は 標高の合計 ÷ 点の数、"range" は 最高 − 最低。市区町村・都道府県の高低差は、中の町丁・字等の
  最高・最低から求める（平均標高の都道府県の値は、公開ファイルを作るときに市区町村の合計から作る）。
town_slope（#179）: 列は「KEY_CODE, 点の数, 傾斜の合計, 3度以上, 4度以上, …」（標高タイルの画素ごとの傾斜の点の数・度の合計・
  その傾斜以上の点の数）。「○度以上」の列ごとに「○度未満」（点の数 − ○度以上）も作り、指標の値は
  numerator_columns の合計 ÷ denominator_columns の合計 × scale。市区町村の値は町丁・字等の合計から計算する。
town_slope_land_use（#181）: 列は「KEY_CODE, 区分, 点の数, 傾斜の合計, 1度以上, …」（town_slope を土地利用の区分ごとに
  分けたもの。点のない組は行がない）。指標の land_use の区分の行を town_slope と同じように使う。その区分の点がない
  地域は値なし（not_applicable）。市区町村は min_denominator_municipality があれば、その点の数未満を出さない。

集計に含まれない都道府県（集計を全国で作り直す前の都道府県など）は取り込まない（値なしの行も作らない）。
"""
from __future__ import annotations

import csv
import gzip
import io
import sqlite3
from collections import defaultdict
from pathlib import Path

from ..db import insert_observation
from ..regions import prefecture_entity_id, prefecture_of, small_area_entity_id

MAX_GAP_SHARE = 0.05


def iter_rows(path: Path):
    """read_rows と同じ行を1行ずつ（大きな集計を、すべての行を一度に持たずに読む）。"""
    with path.open("rb") as f:
        packed = f.read(2) == b"\x1f\x8b"
    with (gzip.open(path, "rt", encoding="utf-8", newline="") if packed
          else path.open(encoding="utf-8", newline="")) as f:
        yield from csv.DictReader(f)


def read_rows(path: Path) -> list[dict[str, str]]:
    data = path.read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"))))


def _areas(conn: sqlite3.Connection, prefs: list[str]) -> dict[str, str]:
    """町丁・字等の地域ID → 市区町村の地域ID（取り込む都道府県の分）。"""
    return {r[0]: r[1] for r in conn.execute(
        "SELECT entity_id, parent_id FROM entities WHERE entity_type = 'small_area'")
        if prefecture_of(r[0]) in prefs}


def _columns(spec, all_columns: list[str]) -> list[str]:
    return list(all_columns) if spec == "*" else list(spec)


def ingest_cells(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict, cfg: dict,
                 prefs: list[str]) -> dict:
    rows = read_rows(path)
    if not rows:
        return {"rows": 0}
    gap = cfg.get("gap_column")
    categories = [c for c in rows[0] if c not in ("KEY_CODE", "年度", gap)]
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == cfg["kind"]}
    areas = _areas(conn, prefs)
    # 年度 → 地域ID → 区分ごとのマスの数（範囲外の列を含む）
    counts: dict[int, dict[str, dict[str, float]]] = defaultdict(dict)
    covered: set[str] = set()   # 集計に含まれる都道府県
    unmatched = []
    for r in rows:
        entity_id = small_area_entity_id(r["KEY_CODE"])
        if prefecture_of(entity_id) not in prefs:
            continue
        covered.add(prefecture_of(entity_id))
        if entity_id not in areas:
            unmatched.append(r["KEY_CODE"])
            continue
        counts[int(r["年度"])][entity_id] = {c: float(r[c]) for c in [*categories, *([gap] if gap else [])]}
    result: dict = {"unmatched": unmatched}
    for year, by_area in sorted(counts.items()):
        period = (f"{year}-04-01", f"{year + 1}-03-31", "fiscal_year")
        munis: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for entity_id, muni in areas.items():
            if prefecture_of(entity_id) not in covered:
                continue
            c = by_area.get(entity_id, {})   # マスの中心が1つも入らない小さな地域は行が0
            for k, v in c.items():
                munis[muni][k] += v
        for indicator_id, d in targets.items():
            num_cols = _columns(d["numerator_columns"], categories)
            den_cols = _columns(d["denominator_columns"], categories)
            n = 0
            for entity_id, c in [*((e, by_area.get(e, {})) for e in areas if prefecture_of(e) in covered),
                                 *munis.items()]:
                den = sum(c.get(k, 0) for k in den_cols)
                _insert_ratio(conn, entity_id, indicator_id, d, period, source_id,
                              sum(c.get(k, 0) for k in num_cols), den, c.get(gap, 0) if gap else 0, cfg,
                              over="over_columns" in d and sum(c.get(k, 0) for k in d["over_columns"]) > den)
                n += 1
            result[f"{indicator_id} {year}"] = n
    return result


def _insert_ratio(conn, entity_id: str, indicator_id: str, d: dict, period: tuple, source_id: str,
                  numerator: float, denominator: float, gap: float, cfg: dict, over: bool = False,
                  min_den: float | None = None) -> None:
    """over: 分母を超える内訳がある（筆ポリゴンの区画は重心の入る地域に数えるので、小さな地域では田・畑の区画の
    面積の合計が地域の面積を超えることがある。そのような地域は田・畑どちらの割合も出さない）。
    min_den: 指標の min_denominator の代わりに使う値（市区町村だけ別の値にする指標）。"""
    obs = dict(entity_id=entity_id, indicator_id=indicator_id, definition_version=d["definition_version"],
               period_start=period[0], period_end=period[1], period_kind=period[2],
               source_id=source_id, denominator_source_id=source_id)
    unit = d.get("denominator_label", "マス")
    min_den = float(d.get("min_denominator", 0)) if min_den is None else float(min_den)
    min_note = f"{unit}が{min_den:g}{d.get('min_denominator_unit', '')}未満のため非表示"
    if gap > MAX_GAP_SHARE * (denominator + gap):
        obs.update(value=None, status="missing", method_note=cfg.get("gap_note", "データのない範囲を含むため値なし"))
    else:
        obs.update(numerator=numerator, denominator=denominator)
        if denominator <= 0:
            obs.update(value=None, status="not_applicable", method_note=f"{unit}がないため算出しない")
        elif denominator < min_den:
            obs.update(value=None, status="withheld", method_note=min_note)
        elif over:
            obs.update(value=None, status="withheld", method_note=d.get("over_note", "割合が100%を超えるため非表示"))
        else:
            obs.update(value=numerator / denominator * float(d.get("scale", 1)), status="derived")
    insert_observation(conn, **obs)


def ingest_elevation(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict, cfg: dict,
                     prefs: list[str]) -> dict:
    rows = read_rows(path)
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "town_elevation"}
    areas = _areas(conn, prefs)
    period = (cfg["period"], cfg["period"], "point")
    stats: dict[str, tuple[float, float, float, float]] = {}   # 地域ID → (点の数, 合計, 最低, 最高)
    covered: set[str] = set()
    unmatched = []
    for r in rows:
        entity_id = small_area_entity_id(r["KEY_CODE"])
        if prefecture_of(entity_id) not in prefs:
            continue
        covered.add(prefecture_of(entity_id))
        if entity_id not in areas:
            unmatched.append(r["KEY_CODE"])
            continue
        n = float(r["点の数"])
        stats[entity_id] = ((n, float(r["標高の合計"]), float(r["最低"]), float(r["最高"])) if n
                            else (0.0, 0.0, float("inf"), float("-inf")))
    groups: dict[str, list[str]] = defaultdict(list)   # 市区町村・都道府県 → 町丁・字等
    for entity_id, muni in areas.items():
        if prefecture_of(entity_id) in covered:
            groups[muni].append(entity_id)
            groups[prefecture_entity_id(prefecture_of(entity_id))].append(entity_id)
    merged = dict(stats)
    for parent, members in groups.items():
        got = [stats.get(m, (0.0, 0.0, float("inf"), float("-inf"))) for m in members]
        merged[parent] = (sum(g[0] for g in got), sum(g[1] for g in got),
                          min(g[2] for g in got), max(g[3] for g in got))
    result: dict = {"unmatched": unmatched}
    for indicator_id, d in targets.items():
        mean = d["elevation_value"] == "mean"
        min_den = float(d.get("min_denominator", 0))
        n_rows = 0
        for entity_id in [*(e for e in areas if prefecture_of(e) in covered), *groups]:
            if mean and entity_id.startswith("pref-"):
                continue   # 平均標高の都道府県の値は公開ファイルを作るときに市区町村の合計から作る
            count, total, low, high = merged.get(entity_id, (0.0, 0.0, float("inf"), float("-inf")))
            obs = dict(entity_id=entity_id, indicator_id=indicator_id, definition_version=d["definition_version"],
                       period_start=period[0], period_end=period[1], period_kind=period[2], source_id=source_id)
            if count <= 0:
                obs.update(value=None, status="not_applicable", method_note="標高の点がないため算出しない")
            elif count < min_den:
                obs.update(value=None, status="withheld", method_note=f"標高の点が{min_den:g}未満のため非表示")
            elif mean:
                obs.update(value=total / count, numerator=total, denominator=count, status="derived",
                           denominator_source_id=source_id)
            else:
                obs.update(value=high - low, status="derived",
                           method_note=f"最高 {high:,.1f}m・最低 {low:,.1f}m")
            if mean and count > 0 and obs["status"] != "derived":
                # 点が少なくて出さない地域も、都道府県の合計には入れる（分子・分母を残す）
                obs.update(numerator=total, denominator=count, denominator_source_id=source_id)
            insert_observation(conn, **obs)
            n_rows += 1
        result[indicator_id] = n_rows
    return result


def ingest_slope(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict, cfg: dict,
                 prefs: list[str]) -> dict:
    rows = read_rows(path)
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "town_slope"}
    areas = _areas(conn, prefs)
    period = (cfg["period"], cfg["period"], "point")
    by_area: dict[str, dict[str, float]] = {}
    covered: set[str] = set()
    unmatched = []
    for r in rows:
        entity_id = small_area_entity_id(r["KEY_CODE"])
        if prefecture_of(entity_id) not in prefs:
            continue
        covered.add(prefecture_of(entity_id))
        if entity_id not in areas:
            unmatched.append(r["KEY_CODE"])
            continue
        by_area[entity_id] = _slope_columns(r)
    munis: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for entity_id, muni in areas.items():
        for k, v in by_area.get(entity_id, {}).items():   # 画素の中心が1つも入らない小さな地域は点が0
            munis[muni][k] += v
    result: dict = {"unmatched": unmatched}
    for indicator_id, d in targets.items():
        n = 0
        for entity_id, c in [*((e, by_area.get(e, {})) for e in areas if prefecture_of(e) in covered),
                             *munis.items()]:
            _insert_ratio(conn, entity_id, indicator_id, d, period, source_id,
                          sum(c.get(k, 0) for k in d["numerator_columns"]),
                          sum(c.get(k, 0) for k in d["denominator_columns"]), 0, cfg)
            n += 1
        result[indicator_id] = n
    return result


def _slope_columns(r: dict[str, str]) -> dict[str, float]:
    """傾斜の集計の行 → 列ごとの数。「○度以上」の列ごとに「○度未満」（点の数 − ○度以上）も作る。"""
    c = {k: float(v or 0) for k, v in r.items() if k not in ("KEY_CODE", "区分")}
    for k in [k for k in c if k.endswith("度以上")]:
        c[k.removesuffix("以上") + "未満"] = c["点の数"] - c[k]
    return c


def ingest_slope_land_use(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict, cfg: dict,
                          prefs: list[str]) -> dict:
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "town_slope_land_use"}
    needed = {c for d in targets.values() for c in [*d["numerator_columns"], *d["denominator_columns"]]}
    areas = _areas(conn, prefs)
    y = int(cfg["fiscal_year"])
    period = (f"{y}-04-01", f"{y + 1}-03-31", "fiscal_year")
    by_area: dict[tuple[str, str], dict[str, float]] = {}   # (地域ID, 区分) → 列ごとの数
    covered: set[str] = set()
    unmatched = []
    for r in iter_rows(path):   # 全国で百万行近くあるので、使う列だけを残す
        entity_id = small_area_entity_id(r["KEY_CODE"])
        if prefecture_of(entity_id) not in prefs:
            continue
        covered.add(prefecture_of(entity_id))
        if entity_id not in areas:
            unmatched.append(r["KEY_CODE"])
            continue
        c = _slope_columns(r)
        by_area[(entity_id, r["区分"])] = {k: c[k] for k in needed}
    towns = [e for e in areas if prefecture_of(e) in covered]
    munis = sorted({areas[e] for e in towns})
    muni_counts: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for (entity_id, land), c in by_area.items():
        for k, v in c.items():
            muni_counts[(areas[entity_id], land)][k] += v
    result: dict = {"unmatched": unmatched}
    for indicator_id, d in targets.items():
        land = d["land_use"]
        n = 0
        # その区分の点がない地域も行を作る（not_applicable。都道府県の合計で値のない市区町村と区別するため）
        for entity_id, c, min_den in [*((e, by_area.get((e, land), {}), None) for e in towns),
                                      *((m, muni_counts.get((m, land), {}), d.get("min_denominator_municipality"))
                                        for m in munis)]:
            _insert_ratio(conn, entity_id, indicator_id, d, period, source_id,
                          sum(c.get(k, 0) for k in d["numerator_columns"]),
                          sum(c.get(k, 0) for k in d["denominator_columns"]), 0, cfg, min_den=min_den)
            n += 1
        result[indicator_id] = n
    return result
