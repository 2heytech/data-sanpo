"""東京都教育委員会「公立学校統計調査報告書【公立学校卒業者の進路状況調査編】」小学校 第1表 状況別卒業者数（xlsx）。

形式（令和7年度版 r7-sotsugo-01 を 2026-10-03 に GitHub Actions から取得して確認）: シート「第1表」。
  4行目に大きな見出し（地区名・卒業者・都内中学校等への進学者・都外中学校等への進学者・その他 …）、
  5行目に「計」「公立」「国立」「私立」、7行目に「計」「男」「女」。1つの区分が3列（計・男・女）。
  1列目が地区名で、年度の行（令和元年度〜）・区部などの小計・区市町村の行・（再掲）都立が並ぶ。
  区市町村の行はその報告書の調査年度の前年度の卒業者（令和7年度版なら令和7年3月の卒業者）。
  地区名は区市町村の公立小学校の所在地（立川市には都立小学校を含む）。

指標（definition の progress_value で選ぶ）: 都内の公立・国立・私立の中学校等、都外の中学校等への進学者 ÷ 卒業者。
  公立には都立中学校・中等教育学校・義務教育学校・特別支援学校中学部への進学を含む（表の注による）。
卒業者が0の町村は値を出さない（not_applicable）。
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

from ..db import insert_observation
from ..xlsx import read_sheet
from .isj_geocode import normalize

GROUPS = {"graduates": "卒業者", "public": "公立", "national": "国立", "private": "私立", "outside": "都外中学校等"}


def _text(cell) -> str:
    return re.sub(r"\s", "", unicodedata.normalize("NFKC", str(cell))) if cell is not None else ""


def read_table(path: Path) -> dict[str, dict[str, float]]:
    """区市町村名（正規化済み） → {graduates, public, national, private, outside}（いずれも計の列）。"""
    rows = read_sheet(path)
    head_at = next(i for i, r in enumerate(rows) if r and _text(r[0]) == "地区名")
    cols: dict[str, int] = {}
    for r in rows[head_at:head_at + 3]:
        for j, c in enumerate(r):
            t = _text(c)
            for key, label in GROUPS.items():
                if key not in cols and t.startswith(label) and "再掲" not in t:
                    cols[key] = j
    # 「卒業者」の見出しは2列目（「卒業者を出した学校」）にもあるので、計の列（3列ごとの区分の先頭）にそろえる
    cols["graduates"] = next(j for j, c in enumerate(rows[head_at]) if _text(c).startswith("卒業者"))
    missing = set(GROUPS) - set(cols)
    if missing:
        raise ValueError(f"{path.name}: 見出しが見つかりません: {sorted(missing)}")
    out: dict[str, dict[str, float]] = {}
    for r in rows[head_at + 1:]:
        name = _text(r[0]) if r else ""
        if not name or not name.endswith(("区", "市", "町", "村")) or name.endswith(("部",)):
            continue
        vals = {k: r[j] if j < len(r) and isinstance(r[j], (int, float)) else None for k, j in cols.items()}
        out[normalize(name)] = vals
    return out


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict,
           period: tuple[str, str, str]) -> dict:
    table = read_table(path)
    by_name = {normalize(r["name"]): r["entity_id"] for r in conn.execute(
        "SELECT entity_id, name FROM entities WHERE entity_type = 'municipality' "
        "AND entity_id LIKE 'muni-13%'")}   # 東京都だけ。府中市（広島県）など同じ名前の市区町村が他県にもある
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "tokyo_jhs_progress"}
    result = {"municipalities": 0, "unmatched": sorted(set(table) - set(by_name))}
    for name, vals in table.items():
        entity_id = by_name.get(name)
        if entity_id is None:
            continue
        grads = vals["graduates"]
        for indicator_id, d in targets.items():
            num = vals[d["progress_value"]]
            obs = dict(entity_id=entity_id, indicator_id=indicator_id,
                       definition_version=d["definition_version"], period_start=period[0],
                       period_end=period[1], period_kind=period[2], source_id=source_id,
                       denominator_source_id=source_id, numerator=num, denominator=grads)
            if num is None or grads is None:
                insert_observation(conn, value=None, status="missing", **obs)
            elif grads <= 0:
                insert_observation(conn, value=None, status="not_applicable",
                                   method_note="卒業者が0のため算出しない", **obs)
            elif grads < d.get("min_denominator", 0):
                insert_observation(conn, value=None, status="withheld",
                                   method_note=f"卒業者が{d['min_denominator']}人未満のため非表示", **obs)
            else:
                insert_observation(conn, value=num / grads * d.get("scale", 1), status="derived", **obs)
        result["municipalities"] += 1
    return result
