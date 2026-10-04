"""観光庁「宿泊旅行統計調査」年の確定値 集計結果（xlsx）の第2表（年計）から、都道府県別の延べ宿泊者数と
外国人延べ宿泊者数を取り込む。

形式（2025年 002010340.xlsx・2019年 001350484.xlsx を 2026-10-04 に GitHub Actions から取得して確認）:
  シート「第2表(年計)」。4行目の見出しに「施設所在地（47区分及び運輸局等）」「延べ宿泊者数」…「うち外国人延べ宿泊者数」、
  7行目が全国計（「令和7年 1～12月  計」）、8行目から「　01北海道」…「　47沖縄県」、その後に運輸局等の行が続く。
  2015・2016年（001312940.xlsx・001190399.xlsx）は都道府県名にコードが付かない（「　北海道」）。単位は人泊。該当なしは「-」。従業者数10人未満の施設も含む全施設の推計値。
指標（definition の inbound_value で選ぶ）: foreign（外国人延べ宿泊者数）、share（外国人 ÷ 延べ宿泊者数）。
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


def _text(cell) -> str:
    return re.sub(r"\s", "", unicodedata.normalize("NFKC", str(cell))) if cell is not None else ""


def _num(cell) -> float | None:
    return float(cell) if isinstance(cell, (int, float)) else None


def read_table(path: Path) -> dict[str, tuple[float | None, float | None]]:
    """都道府県コード2桁 → (延べ宿泊者数, 外国人延べ宿泊者数)。"""
    rows = read_sheet(path, SHEET)
    at = next(i for i, r in enumerate(rows) if r and _text(r[0]).startswith("施設所在地"))
    head = [_text(c) for c in rows[at]]
    c_total = next(j for j, t in enumerate(head) if t.startswith("延べ宿泊者数"))
    c_foreign = next(j for j, t in enumerate(head) if "外国人延べ宿泊者数" in t)
    by_name = {name: code for code, name in PREFECTURES.items()}
    out: dict[str, tuple[float | None, float | None]] = {}
    for r in rows[at + 1:]:
        # 2017年以降は「01北海道」、2015・2016年は「北海道」（コードなし）
        m = re.fullmatch(r"(\d{2})?(\D+)", _text(r[0]) if r else "")
        code = m and by_name.get(m.group(2))
        if not code or (m.group(1) and m.group(1) != code) or code in out:
            continue   # 見出し・全国計・運輸局等の行（運輸局等の区分に同じ名前が出ても最初の行を使う）
        out[code] = (_num(r[c_total]) if c_total < len(r) else None,
                     _num(r[c_foreign]) if c_foreign < len(r) else None)
    if len(out) != len(PREFECTURES):
        raise ValueError(f"{path.name}: 都道府県の行が {len(out)} 行しかありません")
    return out


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict, year: int) -> dict:
    table = read_table(path)
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "mlit_inbound"}
    result = {"prefectures": 0}
    for pref, (total, foreign) in table.items():
        entity_id = prefecture_entity_id(pref)
        if not conn.execute("SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)).fetchone():
            continue   # この公開版で扱っていない都道府県
        for indicator_id, d in targets.items():
            obs = dict(entity_id=entity_id, indicator_id=indicator_id,
                       definition_version=d["definition_version"], period_start=f"{year}-01-01",
                       period_end=f"{year}-12-31", period_kind="calendar_year", source_id=source_id)
            if d["inbound_value"] == "foreign":
                insert_observation(conn, value=None if foreign is None else foreign * d.get("scale", 1),
                                   status="observed" if foreign is not None else "missing", **obs)
            elif foreign is None or not total:
                insert_observation(conn, value=None, status="missing", numerator=foreign,
                                   denominator=total, denominator_source_id=source_id, **obs)
            else:
                insert_observation(conn, value=foreign / total * d.get("scale", 1), status="derived",
                                   numerator=foreign, denominator=total, denominator_source_id=source_id,
                                   **obs)
        result["prefectures"] += 1
    return result
