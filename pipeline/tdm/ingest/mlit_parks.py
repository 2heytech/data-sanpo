"""国土交通省「都市公園データベース」の都市公園整備現況一覧表（Excel）の「市町村別」シートから、
都市計画区域の住民1人あたりの都市公園の面積を取り込む（docs/design-changes.md #210）。

形式（令和6年度末（2025年3月31日）の 05_R06.xlsx を 2026-11-07 に GitHub Actions から取得して確認）:
  1〜3行目が題名・「国営含む」・「2025.3.31時点」、4行目が見出し（「市町村コード」「都道府県名」「市町村名」、
  公園の種類ごとの「箇所」「面積(ha)」、「ｶﾝﾄﾘｰﾊﾟｰｸ　面積(ha)」「都市公園合計　面積(ha)」「都市計画区域人口(千人)」など）。
  5行目から1市町村1行（全国1,741。政令指定都市は市全体の行だけで区の行はない。東京都特別区は区ごと）。
  「都市公園合計」はカントリーパーク（都市計画区域の外にある公園）を含むので、都市計画区域の人口で割るときは
  カントリーパークの面積を引く。既にある「1人当り公園面積」の列は市民緑地を含みカントリーパークの人口も分母に
  入れた値なので使わない。
  都市計画区域人口は千人単位（四捨五入）。0 の市町村は都市計画区域がない（値なし。0 にしない）。
政令指定都市は市全体の値しかないので、区には値を入れず注記を付ける（元データより細かく割り振らない）。
都道府県の値は、県内の市町村（政令指定都市は市全体）の分子・分母を合計して計算する。
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

from ..db import insert_observation
from ..regions import designated_city_wards
from ..xlsx import read_sheet

KIND = "mlit_city_parks"
SHEET = "市町村別"
WARD_NOTE = "政令指定都市は市全体の値だけが公表されているため、区の値はありません"
NO_AREA_NOTE = "都市計画区域がないため算出しない"
PREF_NOTE = "市区町村の分子・分母を合計して計算"
COLUMNS = {"code": "市町村コード", "country": "カントリーパーク面積(ha)", "total": "都市公園合計面積(ha)",
           "population": "都市計画区域人口(千人)"}


def _label(cell) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(cell))) if cell is not None else ""


def read_table(path: Path) -> dict[str, tuple[float, float]]:
    """5桁の市町村コード → (カントリーパークを除く都市公園の面積 m², 都市計画区域の人口 人)。"""
    rows = read_sheet(path, SHEET)
    at = next(i for i, r in enumerate(rows[:10]) if r and _label(r[0]) == COLUMNS["code"])
    head = [_label(c) for c in rows[at]]
    cols = {}
    for key, label in COLUMNS.items():
        if head.count(label) < 1:
            raise ValueError(f"{path.name}: 見出し「{label}」がありません（{head}）")
        cols[key] = head.index(label)
    out: dict[str, tuple[float, float]] = {}
    for r in rows[at + 1:]:
        code = r[cols["code"]] if len(r) > cols["code"] else None
        if code is None or not re.fullmatch(r"\d{4,5}(\.0)?", str(code)):
            continue
        code = str(code).removesuffix(".0").zfill(5)
        vals = [r[cols[k]] if len(r) > cols[k] else None for k in ("total", "country", "population")]
        if not all(isinstance(v, float) for v in vals):
            raise ValueError(f"{path.name}: {code} の面積・人口が数値ではありません: {vals}")
        total, country, population = vals
        out[code] = ((total - country) * 10_000, population * 1_000)
    return out


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict,
           period: tuple[str, str, str]) -> dict:
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == KIND}
    table = read_table(path)
    base = dict(period_start=period[0], period_end=period[1], period_kind=period[2], source_id=source_id)
    known = {r[0] for r in conn.execute("SELECT entity_id FROM entities")}
    result = {"municipalities": 0, "designated_cities": 0, "prefectures": 0, "unmatched": []}
    totals: dict[str, list[float]] = {}
    for code, (area, population) in sorted(table.items()):
        t = totals.setdefault(code[:2], [0.0, 0.0])
        t[0] += area
        t[1] += population
        entity_id = f"muni-{code}"
        if entity_id in known:
            _insert(conn, entity_id, area, population, targets, base)
            result["municipalities"] += 1
        elif wards := designated_city_wards(conn, code):
            for ward in wards:
                for indicator_id, d in targets.items():
                    insert_observation(conn, entity_id=ward, indicator_id=indicator_id,
                                       definition_version=d["definition_version"], value=None,
                                       status="not_applicable", method_note=WARD_NOTE, **base)
            result["designated_cities"] += 1
        else:
            result["unmatched"].append(code)
    for pref, (area, population) in sorted(totals.items()):
        if f"pref-{pref}" in known:
            _insert(conn, f"pref-{pref}", area, population, targets, base, PREF_NOTE)
            result["prefectures"] += 1
    return result


def _insert(conn: sqlite3.Connection, entity_id: str, area: float, population: float, targets: dict,
            base: dict, note: str | None = None) -> None:
    for indicator_id, d in targets.items():
        obs = dict(entity_id=entity_id, indicator_id=indicator_id, definition_version=d["definition_version"],
                   numerator=area, denominator=population, method_note=note, **base)
        if population == 0:
            insert_observation(conn, value=None, status="not_applicable", **{**obs, "method_note": NO_AREA_NOTE})
        elif population < float(d.get("min_denominator", 0)):
            insert_observation(conn, value=None, status="withheld", **obs)
        else:
            insert_observation(conn, value=area / population * d.get("scale", 1), status="derived",
                               denominator_source_id=base["source_id"], **obs)
