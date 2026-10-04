"""文部科学省「学校基本調査」中学校 市町村別学年別生徒数（計・国立・公立・私立の4つの xlsx、e-Stat）を取り込む。

形式（令和7年度 statInfId 000040393498〜501 を 2026-10-04 に GitHub Actions から取得して確認）:
  シートは「全国」と47都道府県（シート名は都道府県名）。都道府県のシートは2行目に都道府県名、3〜4行目が見出し
  （計・1学年・2学年・3学年 × 計・男・女）、5行目が「計」（都道府県の合計）、6行目から区市町村が
  ['101', '千代田区', 計, 男, 女, …] と並ぶ（3列目が生徒数の計）。政令指定都市は区ごとの行（札幌市は '101' 中央区…）。
  最後に「999 東京都外」のような行がある。学校のない町村は0。
生徒は学校の所在地で数える（住んでいる市区町村ではない）。
指標（definition の school_type で選ぶ）: national / public / private の生徒数 ÷ 計（国公私立の合計）。
都道府県の値は都道府県のシートの「計」の行から出す（学校のない町村があっても欠けにしないため）。
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from ..db import insert_observation
from ..regions import PREFECTURES, municipality_entity_id, prefecture_entity_id
from ..xlsx import read_sheet, sheet_names

TYPES = ("total", "national", "public", "private")


def read_counts(path: Path, pref: str) -> dict[str, float]:
    """地域ID → 生徒数（計の列）。都道府県の合計は pref-XX。"""
    name = PREFECTURES[pref]
    if name not in sheet_names(path):
        return {}
    out: dict[str, float] = {}
    for r in read_sheet(path, name):
        if len(r) < 3 or not isinstance(r[2], float):
            continue
        code = str(r[0]).strip() if r[0] is not None else ""
        if code == "計":
            out[prefecture_entity_id(pref)] = r[2]
        elif re.fullmatch(r"\d{3}", code) and code != "999":
            out[municipality_entity_id(pref + code)] = r[2]
    return out


def ingest(conn: sqlite3.Connection, files: list[Path], source_id: str, catalog: dict,
           period: tuple[str, str, str], prefs: list[str]) -> dict:
    by_type = {t: next((f for f in files if f.stem == t), None) for t in TYPES}
    missing = [t for t, f in by_type.items() if f is None]
    if missing:
        raise FileNotFoundError(f"学校基本調査のファイルが足りません: {missing}")
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "estat_school_basic"}
    known = {r[0] for r in conn.execute(
        "SELECT entity_id FROM entities WHERE entity_type IN ('prefecture', 'municipality')")}
    result = {"municipalities": 0, "prefectures": 0, "unmatched": []}
    for pref in prefs:
        counts = {t: read_counts(f, pref) for t, f in by_type.items()}
        for entity_id, total in counts["total"].items():
            if entity_id not in known:
                result["unmatched"].append(entity_id)
                continue
            for indicator_id, d in targets.items():
                num = counts[d["school_type"]].get(entity_id)
                obs = dict(entity_id=entity_id, indicator_id=indicator_id,
                           definition_version=d["definition_version"], period_start=period[0],
                           period_end=period[1], period_kind=period[2], source_id=source_id,
                           denominator_source_id=source_id, numerator=num, denominator=total)
                if num is None:
                    insert_observation(conn, value=None, status="missing", **obs)
                elif total <= 0:
                    insert_observation(conn, value=None, status="not_applicable",
                                       method_note="中学校の生徒がいないため算出しない", **obs)
                elif total < d.get("min_denominator", 0):
                    insert_observation(conn, value=None, status="withheld",
                                       method_note=f"生徒が{d['min_denominator']}人未満のため非表示", **obs)
                else:
                    insert_observation(conn, value=num / total * d.get("scale", 1), status="derived", **obs)
            result["prefectures" if entity_id.startswith("pref-") else "municipalities"] += 1
    result["unmatched"] = result["unmatched"][:30]
    return result
