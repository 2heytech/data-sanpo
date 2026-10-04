"""警視庁「区市町村の町丁別、罪種別及び手口別認知件数」（年計のCSV）を取り込む。

形式（令和元年〜令和7年の実ファイルで確認、2026-10-03）:
  1列目「市区町丁」に区市町村名と町丁目名が続けて入る（例: 千代田区飯田橋１丁目）。
  「千代田区計」が区市町村の合計、「千代田区以下不詳」は町丁目が分からない件数。
  「２３区計」「多摩地区・島部計」「他県」「海外認知」「不明」「合計」は対象外。
  島しょ・郡部は「三宅島三宅村」「西多摩郡瑞穂町」のように島名・郡名が付く。
  認知件数が0件の町丁目は原則として行がない（0件の行がある年もある）。

町丁目は名称で境界（地域ID）に対応付ける。区市町村ごとに「町丁目の合計＋以下不詳＝計」を
確かめ、一致すれば表にない町丁目は0件とする。一致しない区市町村では表にない町丁目を
値なし（missing）にする（docs/design-changes.md #28）。
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from ..db import insert_observation

KANJI_DIGITS = {c: i for i, c in enumerate("〇一二三四五六七八九")}
NOT_LISTED_NOTE = "警視庁の表に掲載がないため0件（市区町村の合計と町丁目の合計が一致することを確認）"
UNKNOWN_SUFFIX = "以下不詳"
TOTAL_SUFFIX = "計"
# 島名・郡名の接頭辞（境界データの市区町村名には付かない）
MUNI_PREFIXES = ("西多摩郡", "大島", "三宅島", "八丈島")


def _kanji_number(text: str) -> str:
    if "十" in text:
        tens, _, ones = text.partition("十")
        return str((KANJI_DIGITS.get(tens, 1) if tens else 1) * 10 + (KANJI_DIGITS.get(ones, 0) if ones else 0))
    return "".join(str(KANJI_DIGITS[c]) for c in text)


def normalize_name(name: str) -> str:
    """町丁目名の表記ゆれ（全角数字・漢数字の丁目・ヶ／ケ／が）を吸収する。"""
    s = unicodedata.normalize("NFKC", name or "")
    s = "".join(s.split())
    s = re.sub(r"(?<=[一-鿿])[ヶケヵが](?=[一-鿿])", "が", s)
    s = re.sub(r"([〇一二三四五六七八九十]+)(?=丁目)", lambda m: _kanji_number(m.group(1)), s)
    return s


@dataclass
class CrimeTable:
    labels: list[str]
    totals: dict[str, dict[str, str]] = field(default_factory=dict)     # 市区町村名 → 行
    unknown: dict[str, dict[str, str]] = field(default_factory=dict)    # 市区町村名 → 以下不詳の行
    towns: dict[str, list[tuple[str, dict[str, str]]]] = field(default_factory=dict)  # 市区町村名 → (町丁目名, 行)
    unparsed: list[str] = field(default_factory=list)


def read_table(path: Path, municipality_names: list[str], encoding: str = "cp932") -> CrimeTable:
    """municipality_names（境界データの区市町村名）を手がかりに、1列目を区市町村と町丁目に分ける。"""
    text = path.read_bytes().decode(encoding)
    records = list(csv.reader(io.StringIO(text)))
    labels = [c.strip() for c in records[0]]
    table = CrimeTable(labels)
    # 長い名前から照合する（例: 「東村山市」を「村山市」より先に）
    names = sorted(municipality_names, key=len, reverse=True)
    for r in records[1:]:
        if not r or not r[0].strip():
            continue
        row = dict(zip(labels, (c.strip() for c in r)))
        raw = unicodedata.normalize("NFKC", r[0].strip())
        for prefix in MUNI_PREFIXES:
            if raw.startswith(prefix) and any(raw[len(prefix):].startswith(n) for n in names):
                raw = raw[len(prefix):]
                break
        muni = next((n for n in names if raw.startswith(n)), None)
        if muni is None:
            table.unparsed.append(r[0].strip())   # ２３区計・他県・不明・合計など
            continue
        rest = raw[len(muni):]
        if rest == TOTAL_SUFFIX:
            table.totals[muni] = row
        elif rest == UNKNOWN_SUFFIX:
            table.unknown[muni] = row
        elif rest == "":
            table.totals.setdefault(muni, row)    # 「千代田区」だけの行は計と同じ値（年による）
        else:
            table.towns.setdefault(muni, []).append((rest, row))
    return table


def _value(row: dict[str, str] | None, column: str) -> float:
    raw = (row or {}).get(column, "").replace(",", "")
    return float(raw) if raw else 0.0


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict,
           period: tuple[str, str, str], encoding: str = "cp932") -> dict:
    """catalog のうち source_kind = "keishicho_crime" の指標（件数）を取り込む。"""
    munis = {r["name"]: r["entity_id"] for r in conn.execute(
        "SELECT entity_id, name FROM entities WHERE entity_type = 'municipality' AND entity_id LIKE 'muni-13%'")}
    areas: dict[str, dict[str, str]] = {}
    # 警視庁の管轄（東京都）の地域だけ。全国版では同じ名前の区市町村（府中市など）が他県にもある
    for r in conn.execute("SELECT entity_id, name, parent_id FROM entities "
                          "WHERE entity_type = 'small_area' AND entity_id LIKE 'area-13%'"):
        areas.setdefault(r["parent_id"], {})[normalize_name(r["name"])] = r["entity_id"]
    table = read_table(path, list(munis), encoding)
    indicators = {k: d for k, d in catalog.items() if d.get("source_kind") == "keishicho_crime"}
    total_column = next(d["column"] for d in indicators.values() if d.get("total"))
    result = {"municipalities": 0, "areas": 0, "unmatched": [], "incomplete": []}
    for muni_name, muni_id in munis.items():
        total_row = table.totals.get(muni_name)
        town_rows = table.towns.get(muni_name, [])
        matched: dict[str, dict[str, str]] = {}
        unmatched_sum = 0.0
        for town, row in town_rows:
            entity_id = areas.get(muni_id, {}).get(normalize_name(town))
            if entity_id is None or entity_id in matched:
                result["unmatched"].append(muni_name + town)
                unmatched_sum += _value(row, total_column)
                continue
            matched[entity_id] = row
        # 町丁目の合計＋以下不詳（＋対応できなかった町丁目）が計と一致すれば、表にない町丁目は0件
        listed = sum(_value(r, total_column) for _, r in town_rows) + _value(table.unknown.get(muni_name), total_column)
        complete = total_row is not None and listed == _value(total_row, total_column)
        if total_row is not None and not complete:
            result["incomplete"].append(muni_name)
        for indicator_id, d in indicators.items():
            base = dict(indicator_id=indicator_id, definition_version=d["definition_version"],
                        period_start=period[0], period_end=period[1], period_kind=period[2],
                        source_id=source_id)
            # 区市町村の値は「計」の行。行がない区市町村（島しょなど）はその年の認知件数が0件
            insert_observation(conn, entity_id=muni_id, value=_value(total_row, d["column"]),
                               status="observed",
                               coverage_note=None if total_row is not None else
                               "警視庁の表に掲載がないため0件", **base)
            for entity_id in areas.get(muni_id, {}).values():
                row = matched.get(entity_id)
                if row is not None:
                    insert_observation(conn, entity_id=entity_id, value=_value(row, d["column"]),
                                       status="observed", **base)
                elif complete or total_row is None:
                    insert_observation(conn, entity_id=entity_id, value=0.0, status="observed",
                                       coverage_note=NOT_LISTED_NOTE, **base)
                else:
                    insert_observation(conn, entity_id=entity_id, value=None, status="missing",
                                       method_note="警視庁の表と町丁目の対応が確認できないため値なし",
                                       **base)
        result["municipalities"] += 1
        result["areas"] += len(matched)
    return result
