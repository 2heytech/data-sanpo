"""観光庁「宿泊旅行統計調査」年の確定値 集計結果（xlsx）から、都道府県別の延べ宿泊者数を取り込む。

形式（2015〜2025年の年の確定値。2025年 002026762.xlsx・2015年 002026815.xlsx などを 2026-10-18 に取得して確認）:
  シート「第2表(年計)」。4行目の見出しに「施設所在地（47区分及び運輸局等）」「延べ宿泊者数」…「うち外国人延べ宿泊者数」、
  7行目が全国計（「令和7年 1～12月  計」）、8行目から「　01北海道」…「　47沖縄県」、その後に運輸局等の行が続く。
  2015・2016年は都道府県名にコードが付かない（「　北海道」）。単位は人泊。該当なしは「-」。従業者数10人未満の施設も
  含む全施設の推計値。
  シート「第4表(年計)」は宿泊施設タイプ（旅館・リゾートホテル・ビジネスホテル・シティホテル・簡易宿所・会社・団体の
  宿泊所）別の延べ宿泊者数。見出しの次の行にタイプの名前が並び、「うち外国人延べ宿泊者数」の列より左が全体の値。
  シート「第9表(年計)」は居住地（県内・県外）別の延べ宿泊者数。見出しから2行下に「県内1)」「県外1)」が並ぶ
  （最初の組が宿泊目的を問わない値。延べ宿泊者数の総数は居住地不詳を含むので、県内＋県外より大きい）。
  外国人は「県外」に入る。行の並びは第2表と同じ。
  2014年以前の年（xls）は施設の区分などが違うので取り込まない。
指標（definition の inbound_value で選ぶ）:
  total（延べ宿泊者数）、foreign（外国人延べ宿泊者数）、japanese（延べ宿泊者数 − 外国人延べ宿泊者数）、
  share（外国人 ÷ 延べ宿泊者数）、facility（facility_type のタイプの延べ宿泊者数）、
  outside_share（県外 ÷（県内＋県外）。居住地不詳は分母に入れない）。
都道府県の値だけ（市区町村は公表されていない）。
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

from ..db import insert_observation
from ..regions import PREFECTURES, prefecture_entity_id
from ..xlsx import read_sheet

SHEET = "第2表(年計)"
FACILITY_SHEET = "第4表(年計)"
RESIDENCE_SHEET = "第9表(年計)"
FACILITY_TYPES = ("旅館", "リゾートホテル", "ビジネスホテル", "シティホテル", "簡易宿所", "会社・団体の宿泊所")


def _text(cell) -> str:
    return re.sub(r"\s", "", unicodedata.normalize("NFKC", str(cell))) if cell is not None else ""


def _num(cell) -> float | None:
    return float(cell) if isinstance(cell, (int, float)) else None


def _header_at(rows: list[list]) -> int:
    return next(i for i, r in enumerate(rows) if r and _text(r[0]).startswith("施設所在地"))


def _prefecture_rows(path: Path, rows: list[list], start: int) -> dict[str, list]:
    """都道府県コード2桁 → その行。"""
    by_name = {name: code for code, name in PREFECTURES.items()}
    out: dict[str, list] = {}
    for r in rows[start:]:
        # 2017年以降は「01北海道」、2015・2016年は「北海道」（コードなし）
        m = re.fullmatch(r"(\d{2})?(\D+)", _text(r[0]) if r else "")
        code = m and by_name.get(m.group(2))
        if not code or (m.group(1) and m.group(1) != code) or code in out:
            continue   # 見出し・全国計・運輸局等の行（運輸局等の区分に同じ名前が出ても最初の行を使う）
        out[code] = r
    if len(out) != len(PREFECTURES):
        raise ValueError(f"{path.name}: 都道府県の行が {len(out)} 行しかありません")
    return out


def _cell(r: list, j: int) -> float | None:
    return _num(r[j]) if j < len(r) else None


def read_table(path: Path) -> dict[str, dict[str, float | None]]:
    """都道府県コード2桁 → 値の名前 → 人泊。名前は total（延べ宿泊者数）、foreign（外国人延べ宿泊者数）、
    宿泊施設タイプの名前（第4表）、県内・県外（第9表）。"""
    rows = read_sheet(path, SHEET)
    at = _header_at(rows)
    head = [_text(c) for c in rows[at]]
    c_total = next(j for j, t in enumerate(head) if t.startswith("延べ宿泊者数"))
    c_foreign = next(j for j, t in enumerate(head) if "外国人延べ宿泊者数" in t)
    out = {code: {"total": _cell(r, c_total), "foreign": _cell(r, c_foreign)}
           for code, r in _prefecture_rows(path, rows, at + 1).items()}

    # 宿泊施設タイプ別（「うち外国人」の列より左の組が全体の値）
    rows = read_sheet(path, FACILITY_SHEET)
    at = _header_at(rows)
    end = next(j for j, t in enumerate(_text(c) for c in rows[at]) if "外国人" in t)
    names = [_text(c) for c in rows[at + 1]]
    cols = {t: j for j, t in enumerate(names[:end]) if t in FACILITY_TYPES}
    if set(cols) != set(FACILITY_TYPES):
        raise ValueError(f"{path.name}: {FACILITY_SHEET} に宿泊施設タイプの列 {sorted(set(FACILITY_TYPES) - set(cols))} がありません")
    for code, r in _prefecture_rows(path, rows, at + 2).items():
        out[code].update({t: _cell(r, j) for t, j in cols.items()})

    # 居住地別（最初に出てくる「県内」「県外」が宿泊目的を問わない値。注の番号「1)」は除いて見る）
    rows = read_sheet(path, RESIDENCE_SHEET)
    at = _header_at(rows)
    names = [re.sub(r"\d\)$", "", _text(c)) for c in rows[at + 2]]
    cols = {t: names.index(t) for t in ("県内", "県外") if t in names}
    if len(cols) != 2:
        raise ValueError(f"{path.name}: {RESIDENCE_SHEET} に県内・県外の列がありません")
    for code, r in _prefecture_rows(path, rows, at + 3).items():
        out[code].update({t: _cell(r, j) for t, j in cols.items()})
    return out


def _value(values: dict[str, float | None], d: dict) -> tuple[float | None, float | None]:
    """(分子, 分母)。率でない指標は分母を None にする。"""
    kind = d["inbound_value"]
    if kind in ("total", "foreign"):
        return values.get(kind), None
    if kind == "facility":
        return values.get(d["facility_type"]), None
    if kind == "japanese":
        total, foreign = values.get("total"), values.get("foreign")
        return (None if total is None or foreign is None else total - foreign), None
    if kind == "share":
        return values.get("foreign"), values.get("total")
    if kind == "outside_share":
        inside, outside = values.get("県内"), values.get("県外")
        return outside, (None if inside is None or outside is None else inside + outside)
    raise ValueError(f"inbound_value が不明です: {kind}")


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict, year: int) -> dict:
    table = read_table(path)
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "mlit_inbound"}
    result = {"prefectures": 0}
    for pref, values in table.items():
        entity_id = prefecture_entity_id(pref)
        if not conn.execute("SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)).fetchone():
            continue   # この公開版で扱っていない都道府県
        for indicator_id, d in targets.items():
            obs = dict(entity_id=entity_id, indicator_id=indicator_id,
                       definition_version=d["definition_version"], period_start=f"{year}-01-01",
                       period_end=f"{year}-12-31", period_kind="calendar_year", source_id=source_id)
            numerator, denominator = _value(values, d)
            if d["kind"] != "ratio":
                # 日本人（延べ宿泊者数 − 外国人）は計算した値
                status = "derived" if d["inbound_value"] == "japanese" else "observed"
                insert_observation(conn, value=None if numerator is None else numerator * d.get("scale", 1),
                                   status=status if numerator is not None else "missing", **obs)
            elif numerator is None or not denominator:
                insert_observation(conn, value=None, status="missing", numerator=numerator,
                                   denominator=denominator, denominator_source_id=source_id, **obs)
            else:
                insert_observation(conn, value=numerator / denominator * d.get("scale", 1), status="derived",
                                   numerator=numerator, denominator=denominator, denominator_source_id=source_id,
                                   **obs)
        result["prefectures"] += 1
    return result
