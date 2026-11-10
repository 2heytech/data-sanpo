"""厚生労働省「介護サービス施設・事業所調査」の基本票 閲覧表 第1表「介護保険施設数－定員，市区町村、施設の種類別」
（e-Stat の CSV、cp932）から、介護保険施設の定員を取り込む（docs/design-changes.md #209）。

形式（令和6年（2024年10月1日）の表を 2026-11-07 に GitHub Actions から取得して確認）:
  1〜2行目が調査名・調査時点と表題、3行目が施設の種類（介護老人福祉施設・介護老人保健施設・介護医療院。
  横に結合したセルの左端にだけ書かれている）、4行目が「施設数」「定員」。5行目から1地域1行で、1列目が
  「00000 全国」「01000 北海道」「01100 札幌市」「01101 中央区」のように5桁のコードと名前（全国・都道府県・
  政令指定都市の市全体・区・市町村）。「-」は該当なし（0）。
  政令指定都市は区の行があるので、市全体の行は使わない（地図の地域にない）。区を再編した市（浜松市）の地図の区
  （2020年国勢調査の区）は表に行がないので、値なしにして理由を書く。
指標（definition の care_item）: capacity（3種類の施設の定員の合計）。
"""
from __future__ import annotations

import csv
import re
import sqlite3
from pathlib import Path

from ..db import insert_observation
from ..regions import REORGANIZED_WARD_NOTE, wards_without_rows

KIND = "mhlw_care_facilities"
FACILITIES = ["介護老人福祉施設", "介護老人保健施設", "介護医療院"]


def _value(s: str) -> float | None:
    s = s.strip()
    if s in ("-", "－"):
        return 0.0
    if s in ("", "…", "...", "x", "X", "・"):
        return None
    return float(s.replace(",", ""))


def read_table(path: Path) -> dict[str, float | None]:
    """5桁の地域コード → 3種類の施設の定員の合計（どれかが不明なら None）。"""
    with path.open(encoding="cp932", errors="replace", newline="") as f:
        rows = list(csv.reader(f))
    head = next(i for i, r in enumerate(rows) if "定員" in r)
    kinds, current = [], ""
    for c in rows[head - 1]:
        current = re.sub(r"\s", "", c) or current
        kinds.append(current)
    cols = []
    for name in FACILITIES:
        found = [j for j, c in enumerate(rows[head]) if c.strip() == "定員" and j < len(kinds) and kinds[j] == name]
        if len(found) != 1:
            raise ValueError(f"{path.name}: 「{name}」の定員の列が見つかりません（{rows[head - 1]} / {rows[head]}）")
        cols.append(found[0])
    out: dict[str, float | None] = {}
    for r in rows[head + 1:]:
        m = re.match(r"(\d{5})\D", (r[0] + " ") if r else "")
        if not m or len(r) <= max(cols):
            continue
        vals = [_value(r[j]) for j in cols]
        out[m.group(1)] = None if None in vals else sum(vals)
    return out


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict,
           period: tuple[str, str, str]) -> dict:
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == KIND}
    table = read_table(path)
    result = {"municipalities": 0, "prefectures": 0, "reorganized_wards": []}
    base = dict(period_start=period[0], period_end=period[1], period_kind=period[2], source_id=source_id)
    written: set[str] = set()
    for code, v in sorted(table.items()):
        if code == "00000":
            continue
        entity_id = f"pref-{code[:2]}" if code.endswith("000") else f"muni-{code}"
        if not conn.execute("SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)).fetchone():
            continue   # 政令指定都市の市全体（区の行を使う）
        for indicator_id, d in targets.items():
            insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                               definition_version=d["definition_version"], value=v,
                               status="observed" if v is not None else "missing", **base)
        written.add(entity_id)
        result["prefectures" if entity_id.startswith("pref-") else "municipalities"] += 1
    for ward in wards_without_rows(conn, written):
        for indicator_id, d in targets.items():
            insert_observation(conn, entity_id=ward, indicator_id=indicator_id, definition_version=d["definition_version"],
                               value=None, status="missing", method_note=REORGANIZED_WARD_NOTE, **base)
        result["reorganized_wards"].append(ward)
    return result
