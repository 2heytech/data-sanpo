"""気象庁「平年値（統計期間1991〜2020年）」のアメダスの月・年別平年値と地点情報を取り込む。

形式（normal_amedas_monthly.zip・amedas_station_index.zip を 2026-10-11 に GitHub Actions から取得し、
フォーマット表 format_amedas.pdf と照合）:
  月・年別平年値 monthly/area??/nml_amd_m_<観測所番号>.csv（cp932、見出しなし、全国 1,298 地点）。
    1行が1要素: 平年値種別(21), 観測所番号, 要素番号, 資料年数, 統計開始年, 統計終了年,
    1〜12月の値と品質(RMK) の組 × 12, 年の値と品質。品質 8 は正常値、0 は統計値なし（値の欄も 0 になる）。
    要素番号: 3500 日照時間の合計（0.1時間）、4000 降水量の合計（0.1mm）、
    6200 積雪の深さの最大（1cm）、6300 降雪の深さの合計（1cm）。
    資料年数が30年に満たない地点（観測を始めた・移した地点）もあり、統計開始年が1991年より後になる。
  地点情報 amedas_station_index.csv（cp932、1行目は見出し）: 観測所番号, 観測所名（全角空白で埋める）,
    カナ, ローマ字, 緯度の度, 緯度の分（0.1分）, 経度の度, 経度の分, 高度(m), 風速計の高さ(m),
    観測の有無（降水量・風・気温・日照時間・積雪の深さ。1 観測、0 なし、日照時間の 2 は推計）。

統計値のない要素（品質 0）は値なしにし、0 にしない。雪の降らない地点で正常値の 0cm は 0 として載せる。
観測所は地点ごとの値なので、地域（市区町村・都道府県）には割り振らない。市区町村は一覧・地図の都道府県分けに使う。
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import zipfile
from pathlib import Path

from shapely.geometry import Point

from ..db import insert_observation, upsert_entity
from .mlit_stations import _municipality_index, _municipality_of

PERIOD = ("1991-01-01", "2020-12-31", "multi_year")
OK = "8"   # 品質: 正常値


def _rows(data: bytes) -> list[list[str]]:
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(data.decode("cp932"))) if r]


def read_stations(data: bytes) -> dict[str, dict]:
    """観測所番号 → 名前・カナ・位置・高度。見出しの行（観測所番号が5桁の数字でない行）は飛ばす。"""
    out = {}
    for r in _rows(data):
        if len(r) < 9 or not (len(r[0]) == 5 and r[0].isdigit()):
            continue
        out[r[0]] = {
            "name": r[1].replace("　", "").strip(), "kana": r[2],
            "lat": int(r[4]) + float(r[5]) / 60, "lon": int(r[6]) + float(r[7]) / 60,
            "altitude_m": int(r[8]),
        }
    return out


def read_normals(data: bytes) -> dict[str, dict]:
    """1地点のファイル → 要素番号 → {years, start, end, monthly[12], annual}。統計値なしの月・年は None。"""
    out = {}
    for r in _rows(data):
        if len(r) < 32 or r[0] != "21":
            continue
        pairs = [(r[6 + 2 * k], r[7 + 2 * k]) for k in range(13)]
        vals = [float(v) if q == OK else None for v, q in pairs]
        out[r[2]] = {"years": int(r[3]), "start": int(r[4]), "end": int(r[5]),
                     "monthly": vals[:12], "annual": vals[12]}
    return out


def _members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist() if n.lower().endswith(".csv")}


def ingest(conn: sqlite3.Connection, files: list[Path], source_id: str, catalog: dict[str, dict],
           boundary_version: str, prefs: list[str]) -> dict:
    members: dict[str, bytes] = {}
    for f in files:
        members.update(_members(f) if f.suffix.lower() == ".zip" else {f.name: f.read_bytes()})
    # 地点情報は平年値（nml_…）でない CSV（amedas_station_index.zip の中の1ファイル）
    stations: dict[str, dict] = {}
    for n, data in members.items():
        if not Path(n).name.startswith("nml_"):
            stations.update(read_stations(data))
    defs = {i: d for i, d in catalog.items() if d.get("source_kind") == "jma_normals"}
    munis = _municipality_index(conn, boundary_version, prefs)
    result = {"stations": 0, "no_station_info": 0, "outside": 0, "observations": 0, "no_value": 0}
    for name, data in sorted(members.items()):
        base = Path(name).name
        if not base.startswith("nml_amd_m_"):
            continue
        number = base.removeprefix("nml_amd_m_").removesuffix(".csv")
        st = stations.get(number)
        if st is None:
            result["no_station_info"] += 1
            continue
        normals = read_normals(data)
        values = {i: normals.get(str(d["element"])) for i, d in defs.items()}
        if not any(v and v["annual"] is not None for v in values.values()):
            continue
        muni = _municipality_of(Point(st["lon"], st["lat"]), *munis)
        if muni is None:   # 取り込む都道府県の外（または境界から遠い）
            result["outside"] += 1
            continue
        entity_id = f"wx-{number}"
        upsert_entity(conn, entity_id, "weather_station", st["name"], parent_id=muni)
        conn.execute("UPDATE entities SET name_kana = ? WHERE entity_id = ?", (st["kana"], entity_id))
        conn.execute(
            """INSERT INTO locations (location_id, entity_id, role, lon, lat, source_id)
               VALUES (?, ?, 'main', ?, ?, ?)
               ON CONFLICT(location_id) DO UPDATE SET lon = excluded.lon, lat = excluded.lat,
                 source_id = excluded.source_id""",
            (f"{entity_id}:main", entity_id, round(st["lon"], 5), round(st["lat"], 5), source_id))
        attrs = {"number": number, "altitude_m": st["altitude_m"], "elements": {}}
        for indicator_id, d in defs.items():
            v = values[indicator_id]
            if v is None or v["annual"] is None:
                result["no_value"] += 1
                continue
            scale = float(d.get("scale", 1))
            attrs["elements"][indicator_id] = {
                "years": v["years"], "start": v["start"], "end": v["end"],
                "monthly": [None if m is None else round(m * scale, 1) for m in v["monthly"]]}
            insert_observation(
                conn, entity_id=entity_id, indicator_id=indicator_id,
                definition_version=d["definition_version"],
                period_start=PERIOD[0], period_end=PERIOD[1], period_kind=PERIOD[2],
                value=round(v["annual"] * scale, 1), status="observed", source_id=source_id)
            result["observations"] += 1
        conn.execute(
            """INSERT INTO entity_attributes (entity_id, attributes) VALUES (?, ?)
               ON CONFLICT(entity_id) DO UPDATE SET attributes = excluded.attributes""",
            (entity_id, json.dumps(attrs, ensure_ascii=False)))
        result["stations"] += 1
    return result
