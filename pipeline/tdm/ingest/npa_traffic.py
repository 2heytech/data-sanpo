"""警察庁「交通事故統計情報のオープンデータ」（本票、人身事故1件1行のCSV）を取り込む。

形式（2019〜2025年の実ファイルとコード表 codebook_2025 で確認、2026-10-03）:
  1行目が列名。年によって列が増減する（2019年は「上下線」「環状交差点の直径」がある）ので列名で読む。
  「都道府県コード」は警察の本部のコード（30 が警視庁＝東京都、北海道は方面本部ごとに 10〜14）。
  「事故内容」1=死亡、2=負傷。
  「事故類型」01=人対車両、21=車両相互、41=車両単独、61=列車。
  「当事者種別（当事者A）」「同（当事者B）」51=自転車、52=駆動補助機付自転車。
  「地点　緯度（北緯）」は度分秒を続けた数字（例: 354115168 = 35度41分15.168秒）、経度は10桁。
  各年のファイルには、前年の年末に起きて翌年の統計に計上された事故が少し含まれる（2%程度）。
  件数は公表の年計に合わせ、ファイルの年（統計の年）で数える。

事故の地点を町丁目・区市町村の境界（最新）に重ねて数える。地点は町丁目より細かいので、
集計は元データより粗くなる（細かく割り振らない原則に沿う）。全事故の地点が載っているため、
事故のない町丁目は0件とする。地点のない事故は数えない。
"""
from __future__ import annotations

import csv
import io
import sqlite3
from collections import Counter
from pathlib import Path

from shapely.geometry import Point
from shapely.strtree import STRtree

from ..db import insert_observation, load_geometry
from ..regions import TOKYO, prefecture_of

# 警察の都道府県コード → 全国地方公共団体コードの都道府県（コード表 codebook_2025 の「都道府県コード」）
POLICE_PREFECTURES = {
    "10": "01", "11": "01", "12": "01", "13": "01", "14": "01",
    "20": "02", "21": "03", "22": "04", "23": "05", "24": "06", "25": "07",
    "30": "13",
    "40": "08", "41": "09", "42": "10", "43": "11", "44": "12", "45": "14", "46": "15",
    "47": "19", "48": "20", "49": "22",
    "50": "16", "51": "17", "52": "18", "53": "21", "54": "23", "55": "24",
    "60": "25", "61": "26", "62": "27", "63": "28", "64": "29", "65": "30",
    "70": "31", "71": "32", "72": "33", "73": "34", "74": "35",
    "80": "36", "81": "37", "82": "38", "83": "39",
    "90": "40", "91": "41", "92": "42", "93": "43", "94": "44", "95": "45", "96": "46", "97": "47",
}
BICYCLE = {"51", "52"}
COLUMNS = ("都道府県コード", "市区町村コード", "事故内容", "事故類型", "当事者種別（当事者A）", "当事者種別（当事者B）",
           "地点　緯度（北緯）", "地点　経度（東経）")
NEAR_DEGREES = 0.002     # 約200m。橋の上・海沿いなどで境界のわずかに外にある地点を最寄りの地域に含める
NO_LOCATION_NOTE = "地点の記録がない事故は含みません"

# 指標の traffic_filter ごとの対象（1件の事故がどれに当たるか）
FILTERS = {
    "all": lambda r: True,
    "fatal": lambda r: r["事故内容"].strip() == "1",
    "pedestrian": lambda r: r["事故類型"].strip() == "01",
    "bicycle": lambda r: (r["当事者種別（当事者A）"].strip() in BICYCLE
                          or r["当事者種別（当事者B）"].strip() in BICYCLE),
}


def dms_to_degrees(raw: str, degree_digits: int) -> float | None:
    """度分秒を続けた数字（度は2桁または3桁、秒は小数3桁）を度に直す。"""
    s = (raw or "").strip()
    if not s.isdigit() or int(s) == 0:
        return None
    s = s.rjust(degree_digits + 7, "0")
    deg, minutes, sec = int(s[:degree_digits]), int(s[degree_digits:degree_digits + 2]), s[degree_digits + 2:]
    return deg + minutes / 60 + int(sec) / 1000 / 3600


def read_accidents(path: Path, encoding: str = "cp932", prefs: list[str] | None = None) -> list[dict[str, str]]:
    """取り込む都道府県（既定は東京都）の警察が記録した事故。県境の近くの地点を隣の県に数えないよう、
    地点ではなく記録した警察で絞る。"""
    wanted = set(prefs or [TOKYO])
    text = path.read_bytes().decode(encoding, errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    reader.fieldnames = [f.strip() for f in reader.fieldnames or []]
    # 全国では1年で30万行ほどあるので、使う列だけ残してメモリを抑える
    return [{k: r.get(k) or "" for k in COLUMNS} for r in reader
            if POLICE_PREFECTURES.get((r.get("都道府県コード") or "").strip()) in wanted]


class _Index:
    def __init__(self, conn: sqlite3.Connection, boundary_version: str, entity_type: str,
                 prefs: list[str] | None = None):
        rows = conn.execute(
            """SELECT b.entity_id, b.geometry FROM boundaries b
               JOIN entities e ON e.entity_id = b.entity_id AND e.entity_type = ?
               WHERE b.boundary_version = ?""", (entity_type, boundary_version)).fetchall()
        # 取り込んだ事故の範囲（都道府県）の地域だけ。範囲外の地域を0件にしない
        rows = [r for r in rows if prefs is None or prefecture_of(r["entity_id"]) in prefs]
        self.ids = [r["entity_id"] for r in rows]
        self.geoms = [load_geometry(r["geometry"]) for r in rows]
        self.tree = STRtree(self.geoms)

    def locate(self, point: Point) -> str | None:
        hits = self.tree.query(point, predicate="intersects")
        if len(hits):
            return self.ids[min(hits)]
        near = self.tree.query(point.buffer(NEAR_DEGREES), predicate="intersects")
        if len(near):
            return self.ids[min(near, key=lambda i: self.geoms[i].distance(point))]
        return None


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict,
           period: tuple[str, str, str], boundary_version: str, encoding: str = "cp932",
           prefs: list[str] | None = None, indexes: dict | None = None) -> dict:
    """indexes: 年ごとのファイルで同じ境界の索引を使い回すための入れ物（全国の町丁目の形は読むのに時間とメモリを使う）。"""
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "npa_traffic"}
    prefs = prefs or [TOKYO]
    accidents = read_accidents(path, encoding, prefs)
    indexes = {} if indexes is None else indexes
    for kind in ("small_area", "municipality"):
        if (boundary_version, kind) not in indexes:
            indexes[(boundary_version, kind)] = _Index(conn, boundary_version, kind, prefs)
    areas, munis = indexes[(boundary_version, "small_area")], indexes[(boundary_version, "municipality")]
    parents = {r["entity_id"]: r["parent_id"] for r in conn.execute(
        "SELECT entity_id, parent_id FROM entities WHERE entity_type = 'small_area'")}
    counts: dict[str, Counter] = {k: Counter() for k in targets}
    result = {"accidents": len(accidents), "no_location": 0, "outside": 0}
    for r in accidents:
        lat = dms_to_degrees(r.get("地点　緯度（北緯）", ""), 2)
        lon = dms_to_degrees(r.get("地点　経度（東経）", ""), 3)
        if lat is None or lon is None:
            result["no_location"] += 1
            continue
        point = Point(lon, lat)
        # 区市町村は町丁目の属する区市町村とし、町丁目の合計と食い違わないようにする。区市町村の境界は
        # 表示用に穴を埋めているため（飛び地を囲む区市町村など）、地点を直接重ねると別の区市町村に入ることがある
        area = areas.locate(point)
        muni = parents.get(area) if area else munis.locate(point)
        places = [p for p in (area, muni) if p]
        if not places:
            result["outside"] += 1   # 都外の地点（警視庁の管轄外に記録された事故など）
            continue
        for indicator_id, d in targets.items():
            if FILTERS[d["traffic_filter"]](r):
                counts[indicator_id].update(places)
    for indicator_id, d in targets.items():
        for entity_id in areas.ids + munis.ids:
            insert_observation(
                conn, entity_id=entity_id, indicator_id=indicator_id,
                definition_version=d["definition_version"],
                period_start=period[0], period_end=period[1], period_kind=period[2],
                value=float(counts[indicator_id][entity_id]), status="observed", source_id=source_id,
                coverage_note=NO_LOCATION_NOTE if result["no_location"] else None)
        result[indicator_id] = sum(counts[indicator_id][m] for m in munis.ids)
    return result
