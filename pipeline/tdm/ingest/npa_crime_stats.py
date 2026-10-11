"""警察庁「犯罪統計」の年計（1～12月【確定値】、e-Stat の CSV）から、都道府県別の認知件数を取り込む。

形式（令和7年 statInfId=000040410682 を 2026-10-11 に確認。ほかの年も同じ並びの前提で、合計の照合で確かめる）:
  cp932 の CSV に複数の表が続く。各表は1列目が「第１表」のような表題で始まり、見出しは複数行（セル内改行あり）。
  第3表＝刑法犯の都道府県別、第4表＝窃盗犯の都道府県別、第6表＝重要犯罪の都道府県別。
  都道府県別の表は1列目が管区（北海道・東北・東京都・関東・中部・近畿・中国・四国・九州）、2列目が都道府県名。
  北海道は2列目が「計」の行が道の合計（ほかの行は方面ごと）、東京都は2列目が空の行。各管区の「計」の行もある。
  最初のデータ行は1列目が「全国」。3列目が当年の認知件数。
都道府県の値だけ（市区町村は公表されていない）。47都道府県の合計が全国の行と一致することを確かめる。
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
import unicodedata
from pathlib import Path

from ..db import insert_observation
from ..regions import PREFECTURES, prefecture_entity_id

KIND = "npa_crime_stats"
# 指標の npa_table（刑法犯・窃盗犯・重要犯罪）→ 表の番号
TABLES = {"total": 3, "theft": 4, "serious": 6}


def _text(cell: str) -> str:
    return re.sub(r"\s", "", unicodedata.normalize("NFKC", cell or ""))


def _int(cell: str) -> int | None:
    s = _text(cell).replace(",", "")
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def read_tables(path: Path, encoding: str = "cp932") -> dict[int, dict[str, int]]:
    """表の番号 → {都道府県コード2桁: 認知件数}（第3・4・6表）。"""
    by_name = {name: code for code, name in PREFECTURES.items()}
    out: dict[int, dict[str, int]] = {}
    national: dict[int, int] = {}
    table = None
    for r in csv.reader(io.StringIO(path.read_bytes().decode(encoding))):
        if not r:
            continue
        first = _text(r[0])
        m = re.match(r"第(\d+)表", first)
        if m:
            table = int(m.group(1))
            continue
        if table not in TABLES.values() or len(r) < 3:
            continue
        second = _text(r[1])
        value = _int(r[2])
        if value is None:
            continue
        if first == "全国" and table not in national:
            national[table] = value
            continue
        code = by_name.get(second)
        if code is None and first == "東京都" and second == "":
            code = "13"
        elif code is None and first == "北海道" and second == "計":
            code = "01"
        if code is None:
            continue   # 管区の計・北海道の方面・政令指定都市の内訳など
        out.setdefault(table, {}).setdefault(code, value)
    for name, no in TABLES.items():
        got = out.get(no, {})
        if len(got) != len(PREFECTURES):
            raise ValueError(f"{path.name}: 第{no}表の都道府県が {len(got)} 件しかありません")
        if no in national and sum(got.values()) != national[no]:
            raise ValueError(f"{path.name}: 第{no}表の都道府県の合計 {sum(got.values())} が全国 {national[no]} と合いません")
    return out


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict, year: int,
           encoding: str = "cp932") -> dict:
    tables = read_tables(path, encoding)
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == KIND}
    result = {"prefectures": 0}
    for pref in PREFECTURES:
        entity_id = prefecture_entity_id(pref)
        if not conn.execute("SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)).fetchone():
            continue   # この公開版で扱っていない都道府県
        for indicator_id, d in targets.items():
            insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                               definition_version=d["definition_version"], period_start=f"{year}-01-01",
                               period_end=f"{year}-12-31", period_kind="calendar_year", source_id=source_id,
                               value=float(tables[TABLES[d["npa_table"]]][pref]), status="observed")
        result["prefectures"] += 1
    return result
