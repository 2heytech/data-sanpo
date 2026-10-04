"""国立教育政策研究所「全国学力・学習状況調査」の都道府県別「調査結果概況」（xlsx）から、公立学校の
教科ごとの平均正答率を取り込む。

形式（令和7年度 13_tokyo/13p_25r.xlsx・13m_25rs.xlsx を 2026-10-04 に GitHub Actions から取得して確認）:
  小学校（…p_25r.xlsx）はシート「国語」「算数」「理科」、中学校（…m_25rs.xlsx）は「国語」「数学」「理科 」。
  各シートの7行目付近に「東京都（公立）」の行があり、児童（生徒）数・平均正答数・「/」・問題数・平均正答率(%)・
  中央値・標準偏差が並ぶ。次の行が「全国（公立）」。中学校の理科は IRT スコアで、平均正答率がない。
  ファイルは都道府県ごとのフォルダ（例: 13_tokyo）にあり、data/raw/<キー>/<都道府県>/ に置く。
指標（definition の gakuryoku_subject で教科のシート名、gakuryoku_school で p / m を選ぶ）。都道府県の値だけ。
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

from ..db import insert_observation
from ..regions import PREFECTURES, prefecture_entity_id
from ..xlsx import read_sheet, sheet_names


def _text(cell) -> str:
    return re.sub(r"\s", "", unicodedata.normalize("NFKC", str(cell))) if cell is not None else ""


def average_rate(path: Path, subject: str, pref_name: str) -> float | None:
    """その都道府県（公立）の平均正答率（%）。シートがない・正答率のない形式なら None。"""
    sheet = next((n for n in sheet_names(path) if _text(n) == subject), None)
    if sheet is None:
        return None
    for r in read_sheet(path, sheet)[:20]:
        at = next((j for j, c in enumerate(r) if _text(c) == f"{pref_name}(公立)"), None)
        if at is None:
            continue
        vals = [c for c in r[at + 1:] if c not in (None, "")]
        # 児童数, 平均正答数, "/", 問題数, 平均正答率, …（平均正答数 ÷ 問題数 と正答率が合うかで並びを確かめる）
        if len(vals) >= 5 and vals[2] == "/" and all(isinstance(v, float) for v in (vals[1], vals[3], vals[4])):
            if vals[3] > 0 and abs(vals[1] / vals[3] * 100 - vals[4]) < 1.0:
                return vals[4]
        return None
    return None


def ingest(conn: sqlite3.Connection, files: list[Path], source_id: str, catalog: dict,
           school: str, period: tuple[str, str, str]) -> dict:
    targets = {k: d for k, d in catalog.items()
               if d.get("source_kind") == "nier_gakuryoku" and d["gakuryoku_school"] == school}
    result = {"prefectures": 0, "missing": []}
    for path in files:
        pref = path.parent.name
        name = PREFECTURES.get(pref)
        entity_id = prefecture_entity_id(pref)
        if name is None or not conn.execute("SELECT 1 FROM entities WHERE entity_id = ?",
                                            (entity_id,)).fetchone():
            continue
        for indicator_id, d in targets.items():
            v = average_rate(path, d["gakuryoku_subject"], name)
            if v is None:
                result["missing"].append(f"{pref} {indicator_id}")
            insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                               definition_version=d["definition_version"], period_start=period[0],
                               period_end=period[1], period_kind=period[2], source_id=source_id,
                               value=v, status="observed" if v is not None else "missing")
        result["prefectures"] += 1
    return result
