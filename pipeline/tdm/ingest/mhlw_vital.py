"""厚生労働省の人口動態保健所・市区町村別統計（合計特殊出生率）と市区町村別生命表（平均寿命）を取り込む。

合計特殊出生率（kind = mhlw_tfr）
  「人口動態保健所・市区町村別統計」（5年ごと）の第2表「母の年齢（5歳階級）・都道府県・保健所・市区町村別
  合計特殊出生率（ベイズ推定値）」の xlsx（平成30〜令和4年 000040174881、平成25〜29年 000031976396 を
  2026-10-10 に GitHub Actions から取得して確認）。1シートで、0列目が「コード＋名前」（「13東京都」
  「1327世田谷保健所」「13101千代田区」、名前の後ろに全角空白）、1列目が合計特殊出生率。都道府県は2桁、
  保健所は4桁、市区町村は5桁のコード。ベイズ推定は5年分の出生をまとめた値。
  市区町村の値は推定値で、都道府県の値はその都道府県の5年間の値（どちらも表の値をそのまま使う）。

平均寿命（kind = mhlw_life_table）
  「市区町村別生命表」（令和2年 000040052725、平成27年 000031693271）の xlsx。シート「生命表1」〜「生命表7」に
  地域ごとの表が縦に並ぶ。各表は「表13101」（表＋5桁の地域コード。全国は 00000、都道府県は 13000）の行で始まり、
  「年齢(x)…平均余命」「…ex」の見出し、「男」の行、0歳からの行、続いて「女」の行、0歳からの行。
  0歳の平均余命（ex）が平均寿命。
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from ..db import insert_observation
from ..regions import municipality_entity_id, prefecture_entity_id
from ..xlsx import read_sheet, sheet_names

TFR_KIND = "mhlw_tfr"
LIFE_KIND = "mhlw_life_table"


def _entity(known: set[str], code: str) -> str | None:
    if len(code) == 2:
        entity_id = prefecture_entity_id(code)
    elif code.endswith("000"):
        entity_id = prefecture_entity_id(code[:2])
    else:
        entity_id = municipality_entity_id(code)
    return entity_id if entity_id in known else None


def _known(conn) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT entity_id FROM entities WHERE entity_type IN ('prefecture', 'municipality')")}


def _value(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").strip()
    return float(s) if re.fullmatch(r"\d+(\.\d+)?", s) else None   # 「-」「…」などは値なし


def _write(conn, entity_id, indicator_id, d, value, source_id, period) -> None:
    insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                       definition_version=d["definition_version"], period_start=period[0],
                       period_end=period[1], period_kind=period[2], value=value,
                       status="observed" if value is not None else "missing", source_id=source_id)


def ingest_tfr(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict,
               period: tuple[str, str, str]) -> dict:
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == TFR_KIND}
    known = _known(conn)
    result = {"municipalities": 0, "prefectures": 0}
    for r in read_sheet(path, sheet_names(path)[0]):
        if len(r) < 2:
            continue
        m = re.match(r"(\d+)", str(r[0] or "").strip())
        if m is None or len(m.group(1)) not in (2, 5):
            continue   # 全国・保健所・見出し
        entity_id = _entity(known, m.group(1))
        if entity_id is None:
            continue   # 政令指定都市の市全体・対象外の都道府県
        for indicator_id, d in targets.items():
            _write(conn, entity_id, indicator_id, d, _value(r[1]), source_id, period)
        result["prefectures" if entity_id.startswith("pref-") else "municipalities"] += 1
    return result


def read_life_expectancy(path: Path) -> dict[str, dict[str, float | None]]:
    """5桁コード → {"男": 平均寿命, "女": 平均寿命}。"""
    out: dict[str, dict[str, float | None]] = {}
    for name in sheet_names(path):
        if not name.startswith("生命表"):
            continue
        rows = read_sheet(path, name)
        code, ex_col, sex = None, None, None
        for r in rows:
            cells = ["" if c is None else str(c).strip() for c in r]
            m = next((re.fullmatch(r"表(\d{5})", c) for c in cells if re.fullmatch(r"表(\d{5})", c)), None)
            if m:
                code, ex_col, sex = m.group(1), None, None
                continue
            if code is None:
                continue
            if "ex" in cells:
                ex_col = cells.index("ex")
            elif cells and cells[0] in ("男", "女"):
                sex = cells[0]
            elif sex and ex_col is not None and _value(cells[0]) == 0.0:
                out.setdefault(code, {})[sex] = _value(r[ex_col]) if ex_col < len(r) else None
                sex = None
    return out


def ingest_life_table(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict,
                      period: tuple[str, str, str]) -> dict:
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == LIFE_KIND}
    known = _known(conn)
    result = {"municipalities": 0, "prefectures": 0}
    for code, by_sex in sorted(read_life_expectancy(path).items()):
        entity_id = _entity(known, code)
        if entity_id is None:
            continue
        for indicator_id, d in targets.items():
            _write(conn, entity_id, indicator_id, d, by_sex.get(d["sex"]), source_id, period)
        result["prefectures" if entity_id.startswith("pref-") else "municipalities"] += 1
    return result
