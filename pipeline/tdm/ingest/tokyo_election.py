"""東京都選挙管理委員会の選挙結果（CSV）を区市町村ごとに取り込む。

形式（2026-10-03 に GitHub Actions から取得して確認。いずれも UTF-8（BOM つき））:
  投票結果（layout = "turnout"）: 2列目が開票区名、3〜5列目が当日有権者数（男・女・計）、
    6〜8列目が投票者数（男・女・計）。数値は「5,615,643」のように桁区切りや末尾の空白がつくことがある。
  比例代表の得票数は全国の総務省の表から取り込む（soumu_election.py、design-changes #111）。

開票区名は全角空白で字下げされ、都計・区部計などには★☆がつく。小選挙区で分かれる区市
（大田区・八王子市など）は「八王子市計」と「八王子市21区」…の行があるので、「…計」の行を使う。
都議選の「北多摩第一」などの選挙区の計、島しょの支庁の小計は区市町村ではないので使わない。

指標: 投票者数 ÷ 当日有権者数（投票率。区市町村の値。都道府県の値は総務省の表から）
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
from pathlib import Path

from ..db import insert_observation


def _rows(path: Path, encoding: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(path.read_text(encoding=encoding))))


def _num(cell: str) -> float | None:
    s = (cell or "").replace(",", "").strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _name(cell: str) -> str:
    return re.sub(r"[\s★☆]", "", cell or "")


def _municipality(cell: str, names: set[str]) -> str | None:
    """開票区名を区市町村名に直す。区市町村でない行（都計・選挙区の計・小選挙区ごとの行）は None。"""
    n = _name(cell)
    if n in names:
        return n
    if n.endswith("計") and n[:-1] in names:
        return n[:-1]
    return None


def read_turnout(path: Path, names: set[str], encoding: str = "utf-8-sig") -> dict[str, tuple[float, float]]:
    """区市町村名 → (投票者数, 当日有権者数)。"""
    out: dict[str, tuple[float, float]] = {}
    for r in _rows(path, encoding):
        if len(r) < 8:
            continue
        name = _municipality(r[1], names)
        voters, electorate = _num(r[7]), _num(r[4])
        if name and name not in out and voters is not None and electorate:
            out[name] = (voters, electorate)
    return out


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict, cfg: dict) -> dict:
    """出典1つ（1つの選挙の1ファイル）を取り込む。cfg は sources.toml の設定（period・layout・encoding）。"""
    by_name = {r["name"]: r["entity_id"] for r in conn.execute(
        "SELECT entity_id, name FROM entities WHERE entity_type = 'municipality' "
        "AND entity_id LIKE 'muni-13%'")}   # 東京都だけ。府中市（広島県）など同じ名前の市区町村が他県にもある
    names = set(by_name)
    layout, encoding = cfg["layout"], cfg.get("encoding", "utf-8-sig")
    if layout != "turnout":
        raise ValueError(f"不明な layout: {layout}")
    period = (cfg["period"], cfg["period"], "point")
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "tokyo_election"}
    turnout = read_turnout(path, names, encoding)
    result: dict = {}
    for indicator_id, d in targets.items():
        for name, (voters, electorate) in turnout.items():
            insert_observation(conn, entity_id=by_name[name], indicator_id=indicator_id,
                               definition_version=d["definition_version"], period_start=period[0],
                               period_end=period[1], period_kind=period[2], source_id=source_id,
                               value=voters / electorate * d.get("scale", 1), status="derived",
                               numerator=voters, denominator=electorate,
                               denominator_source_id=source_id)
        result[indicator_id] = len(turnout)
    result["unmatched"] = sorted(names - set(turnout))
    return result
