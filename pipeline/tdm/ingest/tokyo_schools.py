"""東京都教育委員会「公立学校統計調査報告書【東京都公立学校一覧】」の CSV を取り込む。

形式（令和3〜7年度、2026-10-03 に GitHub Actions から取得して確認）: CSV（cp932）。年度でファイル名が違う。
  一覧（*_ichiran）: 学校番号, 設置者, 学校名, 児童数(通級生を除く。)/総数, …/１学年, … 教員数, 職員数。
    中学校は「生徒数…」、義務教育学校は「児童・生徒数…/前期課程/１学年」〜「後期課程/９学年」。
    最後の行は「合計」。「-」は該当なし（学年の人数の合計が総数と一致することを確認）。
  住所（*_address）: 学校番号, 設置者, 学校名, 郵便番号, 住所, 電話番号, 学校名(フリガナ)。
    住所は設置者の区市町村名を省いた形（「麹町2-8」）。都立の附属中学校などと令和3年度は区市町村名から書く。
値は各年度の5月1日現在（学校一覧のページに記載）。住所は公表時点のもの。
学校名は「麹町」のように種別を省いた形なので、表示用に「小学校」「中学校」を補う。
中学校の通信制の課程（学校名が「(」で始まる行）は学校の点としては扱わない。

位置は住所から国土交通省「位置参照情報」で求める（isj_geocode.py）。区市町村は位置から決め、
位置がない学校は設置者（都立は住所の先頭）の区市町村にする。地図には位置のある学校だけを描く。
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import Point

from ..db import insert_observation, upsert_entity
from .isj_geocode import Gazetteer, normalize
from .mlit_stations import _municipality_index, _municipality_of

TYPE_LABEL = {"elementary": "小学校", "junior_high": "中学校", "compulsory": "義務教育学校"}
NOTE_GEOCODE_TOWN = "住所の街区が位置参照情報に見つからないため、町丁目の代表点に表示しています"


@dataclass
class School:
    number: str
    school_type: str
    founder: str
    name: str
    address: str | None = None
    address_year: int = 0
    values: dict[int, tuple[int, dict[str, int]]] = field(default_factory=dict)  # 年度 → (総数, 学年別)

    @property
    def entity_id(self) -> str:
        return f"school-{self.number}"

    @property
    def display_name(self) -> str:
        if self.school_type == "compulsory" or self.name.endswith("学校") or self.name.endswith("学園"):
            return self.name
        return self.name + TYPE_LABEL[self.school_type]


def _num(cell: str) -> int:
    """「-」は該当なし（0人）。空欄・その他の記号は読めないので例外にする。"""
    cell = cell.strip().replace(",", "")
    if cell in ("-", "－", "‐"):
        return 0
    return int(cell)


def _rows(path: Path, encoding: str):
    with path.open(encoding=encoding, newline="") as f:
        reader = csv.reader(f)
        head = [unicodedata.normalize("NFKC", h).strip() for h in next(reader)]
        for row in reader:
            if not row or not row[0].strip() or not re.fullmatch(r"\d+", row[0].strip()):
                continue   # 合計行・空行
            name = row[2].strip()
            if name.startswith(("(", "（")):
                continue   # 中学校の通信制の課程
            yield head, [c.strip() for c in row]


def read_counts(path: Path, encoding: str = "cp932") -> dict[str, tuple[str, str, int, dict[str, int]]]:
    """学校番号 → (設置者, 学校名, 総数, 学年別)。学年は「1年」〜「9年」。"""
    out = {}
    for head, row in _rows(path, encoding):
        total_col = next(i for i, h in enumerate(head) if re.search(r"数\(通級生を除く。\)/総数$", h))
        grades: dict[str, int] = {}
        for i, h in enumerate(head):
            m = re.search(r"数\(通級生を除く。\)/(?:前期課程/|後期課程/)?([１２３４５６７８９1-9])学年$", h)
            if m:
                g = int(m.group(1).translate(str.maketrans("１２３４５６７８９", "123456789")))
                grades[f"{g}年"] = _num(row[i])
        total = _num(row[total_col])
        if grades and sum(grades.values()) != total:
            raise ValueError(f"{path.name}: 学校番号 {row[0]} の学年別の合計が総数と一致しません")
        out[row[0]] = (row[1], row[2], total, grades)
    return out


def read_addresses(path: Path, encoding: str = "cp932") -> dict[str, tuple[str, str, str]]:
    """学校番号 → (設置者, 学校名, 住所)。"""
    out = {}
    for head, row in _rows(path, encoding):
        col = {h: i for i, h in enumerate(head)}
        out[row[0]] = (row[1], row[2], row[col["住所"]])
    return out


def tables_of(files: list[Path], cfg: dict, source_id: str) -> list[dict]:
    """出典のファイル（<学校種別>_<counts|address>.csv）を取込用の表の一覧にする。"""
    out = []
    for f in files:
        m = re.fullmatch(r"(elementary|junior_high|compulsory)_(counts|address)\.csv", f.name)
        if m:
            out.append({"year": cfg["school_year"], "school_type": m.group(1), "table": m.group(2),
                        "path": f, "source_id": source_id, "encoding": cfg.get("encoding", "cp932")})
    return out


def _municipality_names(conn: sqlite3.Connection) -> dict[str, str]:
    return {normalize(r["name"]): r["entity_id"] for r in conn.execute(
        "SELECT entity_id, name FROM entities WHERE entity_type = 'municipality' AND entity_id LIKE 'muni-13%'")}


def _split_municipality(founder: str, address: str, names: dict[str, str]) -> tuple[str | None, str]:
    """(区市町村名, 区市町村名を除いた住所)。都立の学校は住所の先頭から区市町村名を読む。"""
    a = normalize(address)
    if normalize(founder) in names:
        f = normalize(founder)
        return f, a[len(f):] if a.startswith(f) else a
    for n in sorted(names, key=len, reverse=True):
        if a.startswith(n):
            return n, a[len(n):]
    return None, a


def ingest(conn: sqlite3.Connection, tables: list[dict], gazetteers: dict[str, tuple[Path, str]],
           indicator_id: str, definition: dict, boundary_version: str) -> dict:
    """tables: [{"year", "school_type", "table"("counts"|"address"), "path", "source_id", "encoding"}]
    gazetteers: {"block" | "oaza": (位置参照情報のファイル, source_id)}"""
    schools: dict[str, School] = {}
    count_sources: dict[tuple[str, int], str] = {}
    for t in sorted(tables, key=lambda t: t["year"]):
        if t["table"] == "counts":
            for number, (founder, name, total, grades) in read_counts(t["path"], t.get("encoding", "cp932")).items():
                s = schools.setdefault(number, School(number, t["school_type"], founder, name))
                s.founder, s.name, s.school_type = founder, name, t["school_type"]
                s.values[t["year"]] = (total, grades)
                count_sources[(number, t["year"])] = t["source_id"]
    for t in sorted(tables, key=lambda t: t["year"]):
        if t["table"] == "address":
            for number, (founder, name, address) in read_addresses(t["path"], t.get("encoding", "cp932")).items():
                s = schools.get(number)
                if s and t["year"] >= s.address_year:
                    s.address, s.address_year = address, t["year"]

    names = _municipality_names(conn)
    gaz = (Gazetteer.read(gazetteers["block"][0] if "block" in gazetteers else None,
                          gazetteers["oaza"][0] if "oaza" in gazetteers else None)
           if gazetteers else None)
    ids, geoms, tree = _municipality_index(conn, boundary_version)
    result = {"schools": 0, "located_block": 0, "located_town": 0, "not_located": 0,
              "no_municipality": 0, "observations": 0}
    unlocated: list[str] = []
    for s in schools.values():
        muni_name, rest = _split_municipality(s.founder, s.address or "", names)
        geo = gaz.locate(muni_name, rest) if (gaz and muni_name and s.address) else None
        muni = None
        if geo:
            muni = _municipality_of(Point(geo.lon, geo.lat), ids, geoms, tree)
        if muni is None and muni_name:
            muni = names[muni_name]
        if muni is None:
            result["no_municipality"] += 1
            continue
        upsert_entity(conn, s.entity_id, "school", s.display_name, parent_id=muni)
        attrs = {"school_type": s.school_type, "type_label": TYPE_LABEL[s.school_type],
                 "founder": s.founder, "address": s.address, "address_year": s.address_year or None}
        if geo:
            conn.execute(
                """INSERT INTO locations (location_id, entity_id, role, lon, lat, source_id)
                   VALUES (?, ?, 'main', ?, ?, ?)
                   ON CONFLICT(location_id) DO UPDATE SET lon = excluded.lon, lat = excluded.lat,
                     source_id = excluded.source_id""",
                (f"{s.entity_id}:main", s.entity_id, round(geo.lon, 6), round(geo.lat, 6),
                 gazetteers[geo.level][1]))
            attrs["precision"] = geo.precision
            result["located_block" if geo.precision == "街区" else "located_town"] += 1
        else:
            conn.execute("DELETE FROM locations WHERE entity_id = ?", (s.entity_id,))
            result["not_located"] += 1
            unlocated.append(f"{s.display_name}（{s.founder} {s.address}）")
        conn.execute(
            """INSERT INTO entity_attributes (entity_id, attributes) VALUES (?, ?)
               ON CONFLICT(entity_id) DO UPDATE SET attributes = excluded.attributes""",
            (s.entity_id, json.dumps(attrs, ensure_ascii=False)))
        for y, (total, grades) in s.values.items():
            base = dict(entity_id=s.entity_id, indicator_id=indicator_id,
                        definition_version=definition["definition_version"],
                        period_start=f"{y}-05-01", period_end=f"{y}-05-01", period_kind="point",
                        source_id=count_sources[(s.number, y)])
            insert_observation(conn, **base, value=float(total), status="observed")
            for g, v in grades.items():
                insert_observation(conn, **base, dimension_key=g, value=float(v), status="observed")
            result["observations"] += 1
        result["schools"] += 1
    if unlocated:
        result["not_located_examples"] = unlocated[:30]
    return result
