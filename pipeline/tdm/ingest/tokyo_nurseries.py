"""東京都福祉局「社会福祉施設等一覧」の認可保育所のシート（xlsx）を取り込む。

形式（令和7年10月1日時点、2026-10-03 に GitHub Actions から取得して確認）: シート「認可保育所」。
  見出しの行: 設置, 施設名, 郵便番号（3列）, 所在地, 電話番号（5列）, 認可定員。見出しのない13列目は
  区市町村コードの下3桁（101 → 13101）。例:
  ['営利法人', 'ほっぺるランド外神田', '101', '-', '0021', '千代田区外神田４－８－６', '03', '-', '3526', '-', '2065', 87, 101]
  所在地は区市町村名から書く。島しょは島名から書くことがある（「八丈島八丈町三根５０５番地１」）。

位置は住所から国土交通省「位置参照情報」で求める（isj_geocode.py）。区市町村は位置から決め、
位置がない施設は区市町村コード（なければ住所の先頭）の区市町村にする。地図には位置のある施設だけを描く。
施設に番号がないので、ID は区市町村コードと施設名・所在地から作る（一覧が変わると変わりうる）。
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from shapely.geometry import Point

from ..db import insert_observation, upsert_entity
from ..xlsx import read_sheet
from .isj_geocode import Gazetteer, normalize
from .mlit_stations import _municipality_index, _municipality_of

SHEET = "認可保育所"


def _text(cell) -> str:
    if cell is None:
        return ""
    if isinstance(cell, float) and cell.is_integer():
        return str(int(cell))
    return str(cell).strip()


def read_nurseries(path: Path, sheet: str = SHEET) -> list[dict]:
    """[{"founder", "name", "address", "capacity", "code"}]。定員が数でない行（見出し・空行）は飛ばす。"""
    rows = read_sheet(path, sheet)
    head_at = next(i for i, r in enumerate(rows) if "施設名" in [_text(c) for c in r])
    col = {_text(c): j for j, c in enumerate(rows[head_at]) if _text(c)}
    c_name, c_addr, c_cap = col["施設名"], col["所在地"], col["認可定員"]
    out = []
    for r in rows[head_at + 1:]:
        if len(r) <= c_cap or not _text(r[c_name]):
            continue
        cap = r[c_cap]
        if not isinstance(cap, (int, float)):
            try:
                cap = float(_text(cap).replace(",", ""))
            except ValueError:
                continue
        code = _text(r[c_cap + 1]) if len(r) > c_cap + 1 else ""
        out.append({"founder": _text(r[col["設置"]]) if "設置" in col else "",
                    "name": _text(r[c_name]), "address": _text(r[c_addr]),
                    "capacity": float(cap),
                    "code": f"13{int(code):03d}" if re.fullmatch(r"\d{1,3}", code) else None})
    return out


def _split(address: str, code: str | None, names: dict[str, str], ids: dict[str, str]) -> tuple[str | None, str]:
    """(区市町村名, 区市町村名より後ろの住所)。島名から書く住所（「八丈島八丈町…」）は区市町村名までを除く。"""
    a = normalize(address)
    known = [ids[f"muni-{code}"]] if code and f"muni-{code}" in ids else []
    for n in known + sorted(names, key=len, reverse=True):
        k = a.find(n)
        if k == 0 or (k > 0 and n in known):
            return n, a[k + len(n):]
    return None, a


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, gazetteers: dict[str, tuple[Path, str]],
           indicator_id: str, definition: dict, period: tuple[str, str, str], boundary_version: str) -> dict:
    names = {normalize(r["name"]): r["entity_id"] for r in conn.execute(
        "SELECT entity_id, name FROM entities WHERE entity_type = 'municipality'")}
    name_of = {eid: n for n, eid in names.items()}
    gaz = (Gazetteer.read(gazetteers["block"][0] if "block" in gazetteers else None,
                          gazetteers["oaza"][0] if "oaza" in gazetteers else None)
           if gazetteers else None)
    mids, geoms, tree = _municipality_index(conn, boundary_version)
    result = {"nurseries": 0, "located_block": 0, "located_town": 0, "not_located": 0, "no_municipality": 0}
    unlocated: list[str] = []
    seen: set[str] = set()
    for n in read_nurseries(path):
        muni_name, rest = _split(n["address"], n["code"], names, name_of)
        geo = gaz.locate(muni_name, rest) if (gaz and muni_name) else None
        muni = _municipality_of(Point(geo.lon, geo.lat), mids, geoms, tree) if geo else None
        if muni is None and muni_name:
            muni = names[muni_name]
        if muni is None:
            result["no_municipality"] += 1
            continue
        digest = hashlib.sha1(f"{n['name']}|{normalize(n['address'])}".encode()).hexdigest()[:10]
        entity_id = f"nursery-{(n['code'] or muni.removeprefix('muni-'))}-{digest}"
        if entity_id in seen:
            continue
        seen.add(entity_id)
        upsert_entity(conn, entity_id, "nursery", n["name"], parent_id=muni)
        attrs = {"founder": n["founder"], "address": n["address"]}
        if geo:
            conn.execute(
                """INSERT INTO locations (location_id, entity_id, role, lon, lat, source_id)
                   VALUES (?, ?, 'main', ?, ?, ?)
                   ON CONFLICT(location_id) DO UPDATE SET lon = excluded.lon, lat = excluded.lat,
                     source_id = excluded.source_id""",
                (f"{entity_id}:main", entity_id, round(geo.lon, 6), round(geo.lat, 6),
                 gazetteers[geo.level][1]))
            attrs["precision"] = geo.precision
            result["located_block" if geo.precision == "街区" else "located_town"] += 1
        else:
            conn.execute("DELETE FROM locations WHERE entity_id = ?", (entity_id,))
            result["not_located"] += 1
            unlocated.append(f"{n['name']}（{n['address']}）")
        conn.execute(
            """INSERT INTO entity_attributes (entity_id, attributes) VALUES (?, ?)
               ON CONFLICT(entity_id) DO UPDATE SET attributes = excluded.attributes""",
            (entity_id, json.dumps(attrs, ensure_ascii=False)))
        insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                           definition_version=definition["definition_version"], period_start=period[0],
                           period_end=period[1], period_kind=period[2], source_id=source_id,
                           value=n["capacity"], status="observed")
        result["nurseries"] += 1
    if unlocated:
        result["not_located_examples"] = unlocated[:30]
    return result
