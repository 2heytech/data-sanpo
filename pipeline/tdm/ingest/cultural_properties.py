"""文化庁「国指定文化財等データベース」の一覧（pipeline/tdm/prepare/cultural_properties.py が分けて取得してまとめた CSV）から、
国指定文化財の点と、市区町村ごとの種類別の件数を取り込む（docs/design-changes.md #149）。

形式（2026-10-18 に取得して確認）: CSV（UTF-8、gzip）。列は 台帳ID, 管理対象ID, 名称, 棟名, 文化財種類, 種別1, 種別2, 国, 時代,
重文指定年月日（分類によって指定・登録・選定の年月日）, 国宝指定年月日, 都道府県, 所在地, 保管施設の名称, 緯度, 経度, 取得日。
台帳ID が分類: 102 国宝・重要文化財（建造物）、101 登録有形文化財（建造物）、401 史跡名勝天然記念物、103 重要伝統的建造物群
保存地区。年月日は「19890519」。所在地は都道府県名から書くもの（建造物）と、市区町村から書くもの（史跡など）がある。
都道府県は「２県以上」「地域を定めない」や壊れた値（"98" など）のこともある。

まとめ方:
  - 国宝・重要文化財（建造物）は棟ごとの行なので、名称・都道府県・所在地の市区町村が同じ行を1件にまとめる
    （データベースの件の番号は CSV にない）。点は最初の棟の位置、国宝の棟が1つでもあれば国宝とする。
  - ほかの分類は1行が1件。史跡名勝天然記念物は種別1・種別2の両方の種類に数える（「史跡及び名勝」は史跡にも名勝にも1件）。
    特別史跡・特別名勝・特別天然記念物は、それぞれ史跡・名勝・天然記念物に含める。
  - 「地域を定めない」天然記念物（動物の種など）は場所がないので入れない。
位置: 緯度・経度があり、その点が行の都道府県の中（または近く）にあればそれを使う。ないものは所在地から位置参照情報で求める
（pipeline/tdm/ingest/isj_geocode.py。町丁目・大字の代表点になったものは、おおよその位置と注記する）。
市区町村: 点のある市区町村（政令指定都市は区）。位置が分からなければ所在地の市区町村名。2つ以上の市区町村にまたがる
史跡などは点のある市区町村だけで数える。どちらでも決まらないものは、都道府県の件数にだけ入れる。
"""
from __future__ import annotations

import csv
import gzip
import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import Point

from ..db import insert_observation, upsert_entity
from ..progress import progress
from ..regions import PREFECTURES
from .isj_geocode import MUNICIPALITY_VARIANTS, PREFECTURE_PREFIX, Gazetteer, normalize, normalize_municipality
from .mlit_stations import _municipality_index

ENTITY_TYPE = "cultural_property"
PREF_BY_NAME = {name: code for code, name in PREFECTURES.items()}
NEAR_DEGREES = 0.05   # 約5km。島・海岸の文化財で、点がわずかに市区町村の形の外にあるもの
# 分類（台帳ID）→ 地図に出す分類の名前と、年月日の意味
CATEGORIES = {
    "102": ("重要文化財（建造物）", "指定"),
    "101": ("登録有形文化財（建造物）", "登録"),
    "401": ("史跡名勝天然記念物", "指定"),
    "103": ("重要伝統的建造物群保存地区", "選定"),
}
# 指標の種類（indicators.toml の cultural_type）
KINDS_401 = ("史跡", "名勝", "天然記念物")
NO_AREA = "地域を定めない"


@dataclass
class Item:
    cat: str
    rows: list[dict]
    pref: str | None = None
    muni: str | None = None
    point: tuple[float, float] | None = None
    loc_note: str = ""
    types: list[str] = field(default_factory=list)

    @property
    def first(self) -> dict:
        return self.rows[0]


def _date(s: str) -> str | None:
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", (s or "").strip())
    return f"{int(m.group(1))}年{int(m.group(2))}月{int(m.group(3))}日" if m else None


def _coord(r: dict) -> tuple[float, float] | None:
    try:
        lon, lat = float(r["経度"]), float(r["緯度"])
    except (TypeError, ValueError):
        return None
    return (lon, lat) if 20 <= lat <= 46 and 122 <= lon <= 154 else None


def read_rows(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def types_of(cat: str, r: dict) -> list[str]:
    """件を数える指標の種類。"""
    if cat == "401":
        kinds = {r["種別1"].strip(), r["種別2"].strip()}
        return [k for k in KINDS_401 if k in kinds or "特別" + k in kinds]
    return [{"102": "重要文化財（建造物）", "101": "登録有形文化財（建造物）", "103": "重要伝統的建造物群保存地区"}[cat]]


class Municipalities:
    """所在地の文字から市区町村を決める（都道府県ごとの名前 → 地域ID。政令指定都市の区は「横浜市中区」でも引ける）。"""

    def __init__(self, conn: sqlite3.Connection):
        self.names: dict[str, dict[str, str]] = defaultdict(dict)
        self.full: dict[str, str] = {}   # 地域ID → 位置参照情報と同じ書き方の名前（政令指定都市の区は「横浜市中区」）
        for r in conn.execute("SELECT entity_id, name, region FROM entities WHERE entity_type = 'municipality'"):
            pref = r["entity_id"][5:7]
            name = normalize_municipality(r["name"])
            self.names[pref][name] = r["entity_id"]
            self.full[r["entity_id"]] = name
            if r["region"] and pref != "13" and not name.startswith(normalize(r["region"])):
                self.names[pref][normalize(r["region"]) + name] = r["entity_id"]
                self.full[r["entity_id"]] = normalize(r["region"]) + name

    def find(self, pref: str, address: str) -> tuple[str, str] | None:
        """(地域ID, 市区町村より後の所在地)。所在地の頭に合う最も長い名前（郡名は除いても見る）。"""
        a = normalize(PREFECTURE_PREFIX.sub("", address.strip())).translate(MUNICIPALITY_VARIANTS)
        for text in (a, re.sub(r"^.+?郡", "", a)):
            hit = max((n for n in self.names[pref] if text.startswith(n)), key=len, default=None)
            if hit:
                return self.names[pref][hit], text[len(hit):]
        return None


def group_items(rows: list[dict], munis: Municipalities) -> tuple[list[Item], int]:
    """行 → 件（建造物の棟をまとめる）。「地域を定めない」の行は除き、その数も返す。"""
    items: list[Item] = []
    buildings: dict[tuple, Item] = {}
    skipped = 0
    for r in rows:
        cat = r["台帳ID"].strip()
        if cat not in CATEGORIES:
            continue
        if NO_AREA in (r["都道府県"], r["所在地"]):
            skipped += 1
            continue
        pref = PREF_BY_NAME.get(r["都道府県"].strip())
        if cat == "102":
            found = munis.find(pref, r["所在地"]) if pref else None
            key = (r["名称"].strip(), pref, found[0] if found else r["所在地"].strip())
            if key in buildings:
                buildings[key].rows.append(r)
                continue
            buildings[key] = item = Item(cat, [r], pref)
        else:
            item = Item(cat, [r], pref)
        item.types = types_of(cat, r)
        items.append(item)
    return items, skipped


def _locate(item: Item, munis: Municipalities, index) -> str | None:
    """緯度・経度から位置と市区町村を決める。点がなければ所在地の市区町村を決め、位置を求めるための残りの所在地を返す。"""
    ids, geoms, tree = index
    for r in item.rows:
        if (pt := _coord(r)) is None:
            continue
        p = Point(*pt)
        hits = list(tree.query(p, predicate="intersects")) or \
            sorted(tree.query(p.buffer(NEAR_DEGREES), predicate="intersects"), key=lambda i: geoms[i].distance(p))
        muni = ids[hits[0]] if hits else None
        # 行の都道府県と違う所の点（緯度・経度の誤り）は使わない。「２県以上」などは点の都道府県にする
        if muni and (item.pref is None or muni[5:7] == item.pref):
            item.point, item.muni, item.pref = pt, muni, muni[5:7]
            return None
    if item.pref is None:
        item.pref = next((c for name, c in PREF_BY_NAME.items() if item.first["所在地"].startswith(name)), None)
    found = munis.find(item.pref, item.first["所在地"]) if item.pref else None
    if not found:
        return None
    item.muni, rest = found
    return rest or None


def _geocode(items: list[tuple[Item, str]], munis: Municipalities, gazetteers: dict) -> None:
    """点のない件の位置を所在地から求める（位置参照情報は都道府県ごとに読み、読み終えたら手放す）。"""
    by_pref: dict[str, list[tuple[Item, str]]] = defaultdict(list)
    for item, rest in items:
        by_pref[item.pref].append((item, rest))
    for pref, lst in sorted(by_pref.items()):
        gz = gazetteers.get(pref)
        if not gz:
            continue
        gaz = Gazetteer.read(gz["block"][0] if "block" in gz else None, gz["oaza"][0] if "oaza" in gz else None)
        for item, rest in lst:
            hit = gaz.locate(munis.full[item.muni], rest)
            if hit:
                item.point = (hit.lon, hit.lat)
                item.loc_note = ("所在地から求めた位置" if hit.precision == "街区"
                                 else "所在地の町丁目・大字の代表点で、おおよその位置")


def _attrs(item: Item, source_id: str, as_of: str) -> dict:
    r = item.first
    label, verb = CATEGORIES[item.cat]
    if item.cat == "102":
        treasure = sorted(d for x in item.rows if (d := x["国宝指定年月日"].strip()))
        kind = "国宝（建造物）" if any(x["種別1"].strip() == "国宝" for x in item.rows) else label
        dates = sorted(d for x in item.rows if (d := x["重文指定年月日"].strip()))
        when = _date(dates[0]) if dates else None
    else:
        treasure = []
        kinds = [k for k in (r["種別1"].strip(), r["種別2"].strip()) if k]
        kind = "・".join(kinds) if item.cat == "401" else label
        when = _date(r["重文指定年月日"])
    return {
        "prefecture": item.pref, "kind": kind, "types": item.types,
        # 建造物の種類（「近代／文化施設」「住宅」）・町並みの種類（「港町」）
        "subtype": ("・".join(k for k in (r["種別1"].strip(), r["種別2"].strip()) if k) if item.cat == "101"
                    else (r["種別2"].strip() if item.cat == "102" else r["種別1"].strip() if item.cat == "103" else "")) or None,
        "era": r["時代"].strip() or None,
        "date": f"{when}{verb}" if when else None,
        "treasure": f"{_date(treasure[0])}国宝に指定" if treasure and _date(treasure[0]) else None,
        "buildings": [b for x in item.rows if (b := x["棟名"].strip())] or None,
        "address": r["所在地"].strip() or None,
        "db": f"{item.cat}/{r['管理対象ID'].strip()}",
        "location_note": item.loc_note or None,
        "source_id": source_id, "as_of": as_of,
    }


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict, boundary_version: str,
           prefs: list[str], gazetteers: dict) -> dict:
    rows = read_rows(path)
    as_of = max((r.get("取得日") or "" for r in rows), default="") or None
    if not as_of:
        raise ValueError(f"{path.name}: 取得日の列がありません")
    munis = Municipalities(conn)
    index = _municipality_index(conn, boundary_version, prefs)
    items, skipped = group_items(rows, munis)
    result = {"rows": len(rows), "no_area": skipped, "items": 0, "located": 0, "geocoded": 0,
              "no_location": 0, "no_municipality": 0}
    kept: list[Item] = []
    todo: list[tuple[Item, str]] = []
    for item in items:
        rest = _locate(item, munis, index)
        if item.pref in prefs:
            kept.append(item)
            if rest:
                todo.append((item, rest))
    _geocode(todo, munis, gazetteers)
    for item in kept:
        result["items"] += 1
        if item.point and not item.loc_note:
            result["located"] += 1
        elif item.point:
            result["geocoded"] += 1
        else:
            result["no_location"] += 1
        if not item.muni:
            result["no_municipality"] += 1
            progress(f"国指定文化財の市区町村が決まりません: {item.first['名称']}（{item.first['都道府県']} {item.first['所在地']}）")

    for item in kept:
        r = item.first
        eid = f"cp-{item.cat}-{r['管理対象ID'].strip()}"
        upsert_entity(conn, eid, ENTITY_TYPE, r["名称"].strip(), parent_id=item.muni or f"pref-{item.pref}")
        if item.point:
            conn.execute(
                """INSERT INTO locations (location_id, entity_id, role, lon, lat, source_id)
                   VALUES (?, ?, 'main', ?, ?, ?)
                   ON CONFLICT(location_id) DO UPDATE SET lon = excluded.lon, lat = excluded.lat,
                     source_id = excluded.source_id""",
                (f"{eid}:main", eid, round(item.point[0], 6), round(item.point[1], 6), source_id))
        conn.execute(
            """INSERT INTO entity_attributes (entity_id, attributes) VALUES (?, ?)
               ON CONFLICT(entity_id) DO UPDATE SET attributes = excluded.attributes""",
            (eid, json.dumps(_attrs(item, source_id, as_of), ensure_ascii=False)))

    # 市区町村・都道府県の種類別の件数（文化財のない市区町村は0）
    for indicator_id, d in catalog.items():
        if d.get("source_kind") != "kunishitei_cultural_properties":
            continue
        kind = d["cultural_type"]
        by_muni: dict[str, int] = defaultdict(int)
        by_pref: dict[str, int] = defaultdict(int)
        for item in kept:
            if kind in item.types:
                by_pref[item.pref] += 1
                if item.muni:
                    by_muni[item.muni] += 1
        base = dict(indicator_id=indicator_id, definition_version=d["definition_version"], period_start=as_of,
                    period_end=as_of, period_kind="point", source_id=source_id, status="observed")
        for muni in index[0]:
            insert_observation(conn, entity_id=muni, value=float(by_muni.get(muni, 0)), **base)
        for pref in sorted({m[5:7] for m in index[0]}):
            insert_observation(conn, entity_id=f"pref-{pref}", value=float(by_pref.get(pref, 0)), **base)
        result[indicator_id] = sum(by_pref.values())
    return result
