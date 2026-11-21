"""厚生労働省「医療施設（動態）調査」の二次医療圏・市区町村編（e-Stat の CSV、cp932）を取り込む（#207）。

形式（令和7年（2025年10月1日）の第1表・第2表を 2026-11-06 に GitHub Actions から取得して確認）:
  1〜2行目が調査名と表題、その下の数行が列の見出し（項目名が縦に分かれて書かれている）。そのあと1地域1行で、
  1列目が「01　　北海道　」（都道府県。2桁）、「0101　南渡島　…」（二次医療圏。4桁、使わない）、
  「01202 函館市　…」（市区町村・政令指定都市の区。5桁）。「-」は該当なし（0）。
  区を再編した市（浜松市）の地図の区（2020年国勢調査の区）は表に行がないので、値なしにして理由を書く。
  第1表「病院数；病床数，病院－病床の種類・二次医療圏・市区町村別」: 8列目（0から数えて7）が病院の病床数の総数。
  第2表「一般診療所数；歯科診療所数；病床数，病床の有無・二次医療圏・市区町村別」: 9列目（同8）が一般診療所の病床数。
指標（definition の medical_item）: hospital_beds（病院の病床数）・clinic_beds（一般診療所の病床数）・
  beds_total（その合計）。
"""
from __future__ import annotations

import csv
import re
import sqlite3
from pathlib import Path

from ..db import insert_observation
from ..regions import REORGANIZED_WARD_NOTE, wards_without_rows

KIND = "mhlw_medical_facilities"
# (ファイル名に含まれる表の番号, 列, 列の見出しに含まれるはずの言葉)
COLUMNS = {"hospital_beds": ("n1", 7, "病床数"), "clinic_beds": ("n2", 8, "病床数")}


def _value(s: str) -> float | None:
    s = s.strip()
    if s in ("-", "－"):
        return 0.0
    if s in ("", "…", "...", "x", "X"):
        return None
    return float(s.replace(",", ""))


def read_table(path: Path, column: int, label: str) -> dict[str, float | None]:
    """地域コード（都道府県は2桁、市区町村は5桁）→ 値。"""
    with path.open(encoding="cp932", errors="replace", newline="") as f:
        rows = list(csv.reader(f))
    first = next(i for i, r in enumerate(rows) if r and re.match(r"\d{2}\s", r[0].replace("　", " ")))
    # 見出しは横に結合したセルの左端にだけ書かれているので、その列から左へ見る
    heads = "".join(re.sub(r"\s|　", "", c) for r in rows[2:first] for c in r[max(1, column - 7):column + 1])
    if label not in heads:
        raise ValueError(f"{path.name}: {column + 1}列目の見出しに「{label}」がありません（{heads}）")
    out: dict[str, float | None] = {}
    for r in rows[first:]:
        if not r or len(r) <= column:
            continue
        m = re.match(r"(\d+)", r[0].strip())
        if not m or len(m.group(1)) not in (2, 5):
            continue   # 二次医療圏（4桁）・注記
        out[m.group(1)] = _value(r[column])
    return out


def ingest(conn: sqlite3.Connection, files: list[Path], source_id: str, catalog: dict,
           period: tuple[str, str, str]) -> dict:
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == KIND}
    tables = {}
    for item, (name, column, label) in COLUMNS.items():
        path = next(f for f in files if name in f.stem)
        tables[item] = read_table(path, column, label)
    result = {"municipalities": 0, "prefectures": 0, "reorganized_wards": []}
    base = dict(period_start=period[0], period_end=period[1], period_kind=period[2], source_id=source_id)
    written: set[str] = set()
    codes = set(tables["hospital_beds"]) | set(tables["clinic_beds"])
    for code in sorted(codes):
        entity_id = f"pref-{code}" if len(code) == 2 else f"muni-{code}"
        if not conn.execute("SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)).fetchone():
            continue
        h, c = tables["hospital_beds"].get(code), tables["clinic_beds"].get(code)
        values = {"hospital_beds": h, "clinic_beds": c,
                  "beds_total": None if h is None or c is None else h + c}
        for indicator_id, d in targets.items():
            v = values[d["medical_item"]]
            insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                               definition_version=d["definition_version"], value=v,
                               status="observed" if v is not None else "missing", **base)
        written.add(entity_id)
        result["prefectures" if len(code) == 2 else "municipalities"] += 1
    for ward in wards_without_rows(conn, written):
        for indicator_id, d in targets.items():
            insert_observation(conn, entity_id=ward, indicator_id=indicator_id, definition_version=d["definition_version"],
                               value=None, status="missing", method_note=REORGANIZED_WARD_NOTE, **base)
        result["reorganized_wards"].append(ward)
    return result
