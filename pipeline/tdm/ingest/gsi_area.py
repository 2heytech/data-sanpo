"""国土地理院「全国都道府県市区町村別面積調」の CSV（市区町村・都道府県の面積）を取り込む（docs/design-changes.md #119）。

形式（令和元年〜令和5年・令和6年4月以降の CSV を 2026-10-15 に取得して確認）: 説明の行のあと、5行目が列名
「標準地域コード」「都道府県」「郡･支庁･振興局等」「市区町村」「令和7年10月1日(k㎡)」「令和7年10月1日備考」…
（時点ごとに面積と備考の2列。新しい時点が左）。文字コードは CSV によって違う（令和6年4月以降は BOM 付き UTF-8、
令和元年〜令和5年は Shift_JIS）。標準地域コードは先頭の0のない4〜5桁で、末尾が000の行は都道府県。
郡・支庁の小計の行（市区町村名が空）と、「北海道(市部)」のようなコードのない行がある。
政令指定都市は市の行（例: 1100 札幌市）と区の行（1101「(札幌市)中央区」）の両方がある。
境界が決まっていない部分のある市区町村は、備考に「（参考値）」（便宜上の概算）とある。
都道府県の面積は公表値を使う（市区町村の合計にすると、北方領土の6村や境界未定の湖などの分が足りなくなるため）。
"""
from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path

from ..db import insert_observation
from ..regions import municipality_entity_id, prefecture_entity_id

REFERENCE = "（参考値）"
REFERENCE_NOTE = "境界の一部が決まっていないため、便宜上の概算の面積（参考値）"


def _text(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "cp932"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path.name}: 文字コードが分かりません")


def read_areas(path: Path, column: str, prefs: list[str]) -> dict[str, tuple[float | None, str]]:
    """地域コード5桁（都道府県は「13000」の形）→（面積 km²、備考）。column は時点（例:「令和7年10月1日」）。"""
    rows = list(csv.reader(io.StringIO(_text(path))))
    at = next(i for i, r in enumerate(rows) if r and r[0].strip() == "標準地域コード")
    header = [h.strip() for h in rows[at]]
    # 時点によっては「令和元年10月1日面積(k㎡)」のように「面積」が入る
    value_col = next(j for j, h in enumerate(header) if h.startswith(column) and h.endswith("(k㎡)"))
    note_col = header.index(f"{column}備考")
    out: dict[str, tuple[float | None, str]] = {}
    for r in rows[at + 1:]:
        if len(r) <= note_col or not r[0].strip().isdigit():
            continue
        code = r[0].strip().zfill(5)
        if code[:2] not in prefs or not (code.endswith("000") or r[3].strip()):
            continue   # 郡・支庁の小計の行
        raw = r[value_col].strip().replace(",", "")
        out[code] = (float(raw) if raw else None, r[note_col].strip())
    return out


def note_of(remark: str) -> str | None:
    """備考を地図の注記にする（「（参考値）」は意味を書き、「本栖湖を除く。」などはそのまま）。"""
    rest = remark.replace(REFERENCE, "").strip()
    parts = ([REFERENCE_NOTE] if REFERENCE in remark else []) + ([rest.rstrip("。")] if rest else [])
    return "。".join(parts) or None


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict, column: str,
           period: tuple[str, str, str], prefs: list[str]) -> dict:
    data = read_areas(path, column, prefs)
    targets = [k for k, d in catalog.items() if d.get("source_kind") == "gsi_area"]
    result = {"municipalities": 0, "prefectures": 0, "not_in_map": []}
    for code, (value, remark) in sorted(data.items()):
        if code.endswith("000"):
            entity_id = prefecture_entity_id(code[:2])
        else:
            entity_id = municipality_entity_id(code)
            if not conn.execute("SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)).fetchone():
                # 政令指定都市の市全体の行（地図の単位は区）、北方領土の村、地図の時点と区の分け方が違う市の区など
                result["not_in_map"].append(code)
                continue
        for indicator_id in targets:
            insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                               definition_version=catalog[indicator_id]["definition_version"],
                               period_start=period[0], period_end=period[1], period_kind=period[2],
                               source_id=source_id, value=value,
                               status="missing" if value is None else "observed",
                               method_note=note_of(remark))
        result["prefectures" if code.endswith("000") else "municipalities"] += 1
    return result
