"""子ども・子育て支援情報公表システム「ここdeサーチ」の全国施設CSV（認可施設）から、保育所などを取り込む
（docs/design-changes.md #137）。

形式（2026-10-17 に取得して確認）: 画面の「全国施設CSVファイルダウンロード」で ZIP（約31MB）。中に都道府県ごとの
「公表施設情報_認可_<都道府県名>_<取得日>.csv」（cp932、539列。認可外の施設のファイルは使わない）があり、取得では
<都道府県コード>/ninka_<取得日>.csv として保存する（fetch.fetch_kokode）。1行が1施設で、主な列は
  施設類型（「保育所」「認定こども園－幼保連携型」「小規模保育事業者－A型」など）、施設の名称、事業所番号（13桁）、
  施設の所在地 都道府県 / 市区町村（「東伯郡北栄町」「札幌市中央区」）/ 町名・番地、営業状況（「通常営業」「休止中」など）、
  法人等の種類（「社会福祉法人」「地方公共団体（市区町村）」など）、0歳〜5歳・合計の利用定員数と利用者数。
緯度経度と施設ごとの更新日はない。値は各施設が公表している最新の内容で、時点は施設ごとに違う（ファイルの取得日を時点にする）。
法人の代表者・施設の管理者の氏名の列は読まない。

取り込む施設: 通常営業の認可保育所・認定こども園・小規模保育（A型・B型）・事業所内保育。
  幼稚園は保育所ではないので除く。家庭的保育・小規模保育C型（保育者の自宅などで少人数を預かる）と居宅訪問型保育
  （子どもの家で保育する）は、個人の住まいの位置を地図に出さないよう除く。
  東京都の認可保育所は東京都福祉局の一覧（認可定員、tokyo_nurseries.py）を使うので、ここからは取り込まない。
  都の一覧に同じ区市町村・同じ名前の施設がある東京都の施設（保育所型の認定こども園など）も重ねて取り込まない。
値: 合計の利用定員数（空欄は値なし。0人にしない）。内訳 users に合計の利用者数、users:0歳〜users:5歳 に年齢別の利用者数
  （年齢別の合計が合計と一致するときだけ）。
位置は所在地から位置参照情報で求める（isj_geocode.py。街区がなければ町丁目の代表点、それもなければ位置なし）。
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

from shapely.geometry import Point

from ..db import insert_observation, upsert_entity
from .isj_geocode import Gazetteer, normalize, normalize_municipality
from .mlit_stations import _municipality_index, _municipality_of

# 施設類型（NFKC にした先頭の文字）→ 表示する種類
FACILITY_TYPES = [("保育所", "認可保育所"), ("認定こども園", "認定こども園"),
                  ("小規模保育事業者-A型", "小規模保育"), ("小規模保育事業者-B型", "小規模保育"),
                  ("事業所内保育事業者", "事業所内保育")]
TOKYO = "13"
TOKYO_LIST = "認可保育所"   # 東京都は都の一覧の認可保育所を使う
AGES = range(6)


def facility_type(raw: str) -> str | None:
    t = unicodedata.normalize("NFKC", raw).strip()
    if t == "保育所":
        return "認可保育所"
    for prefix, label in FACILITY_TYPES[1:]:
        if t.startswith(prefix):
            return label
    return None


def _int(cell: str) -> int | None:
    s = unicodedata.normalize("NFKC", cell or "").strip().replace(",", "")
    return int(s) if re.fullmatch(r"\d+", s) else None


def read_facilities(path: Path, pref: str) -> list[dict]:
    """通常営業の対象の施設。[{"id", "type", "name", "municipality", "street", "address", "founder", "capacity",
    "users", "users_by_age"}]"""
    out = []
    with path.open(encoding="cp932", errors="replace", newline="") as f:
        for r in csv.DictReader(f):
            kind = facility_type(r["施設類型"])
            if kind is None or r["営業状況"].strip() != "通常営業":
                continue
            if pref == TOKYO and kind == TOKYO_LIST:
                continue
            muni = r["施設の所在地 市区町村"].strip()
            street = r["施設の所在地 町名・番地"].strip()
            users = _int(r["合計_利用者数"])
            ages = {f"{a}歳": _int(r[f"{a}歳_利用者数"]) for a in AGES}
            by_age = ({k: v for k, v in ages.items() if v} if users is not None
                      and sum(v or 0 for v in ages.values()) == users else {})
            out.append({
                "id": r["事業所番号"].strip(), "type": kind, "name": r["施設の名称"].strip(),
                "municipality": muni, "street": street,
                "address": f"{r['施設の所在地 都道府県'].strip()}{muni}{street}",
                "founder": r["法人等の種類"].strip(),
                "capacity": _int(r["合計_利用定員数"]), "users": users, "users_by_age": by_age})
    return out


def period_of(path: Path) -> str:
    """ファイル名の取得日（ninka_20261017.csv → 2026-10-17）。"""
    m = re.search(r"(20\d\d)(\d\d)(\d\d)", path.name)
    if not m:
        raise ValueError(f"{path.name}: ファイル名に取得日がありません")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _name_key(name: str) -> str:
    return re.sub(r"\s", "", unicodedata.normalize("NFKC", name))


def _municipality_names(conn: sqlite3.Connection, pref: str) -> dict[str, str]:
    """市区町村名（郡名なし）→ 地域ID。政令指定都市の区は「札幌市中央区」でも引けるようにする。"""
    out = {}
    for r in conn.execute("SELECT entity_id, name, region FROM entities WHERE entity_type = 'municipality' "
                          "AND entity_id LIKE ?", (f"muni-{pref}%",)):
        name = normalize_municipality(r["name"])
        out[name] = r["entity_id"]
        if r["region"] and not name.startswith(normalize(r["region"])) and pref != TOKYO:
            out[normalize(r["region"]) + name] = r["entity_id"]
    return out


def ingest(conn: sqlite3.Connection, files: dict[str, list[Path]], source_id: str,
           gazetteers: dict[str, dict], indicator_id: str, definition: dict, boundary_version: str) -> dict:
    """files: 都道府県コード → その都道府県の CSV。gazetteers: 都道府県コード → {"block"|"oaza": (ファイル, source_id)}。"""
    result: dict = {}
    for pref, paths in sorted(files.items()):
        path = max(paths, key=lambda p: p.name)   # 取得日の新しいファイル
        period = period_of(path)
        names = _municipality_names(conn, pref)
        gz = gazetteers.get(pref, {})
        gaz = Gazetteer.read(gz["block"][0] if "block" in gz else None,
                             gz["oaza"][0] if "oaza" in gz else None) if gz else None
        index = _municipality_index(conn, boundary_version, [pref])
        r = {"facilities": 0, "located_block": 0, "located_town": 0, "not_located": 0, "no_municipality": 0,
             "in_tokyo_list": 0, "with_capacity": 0, "with_users": 0, "not_located_examples": []}
        # 都の一覧から取り込んだ施設（ID は「nursery-区市町村コード-…」）
        listed = {(row["parent_id"], _name_key(row["name"])) for row in conn.execute(
            "SELECT parent_id, name FROM entities WHERE entity_type = 'nursery' "
            "AND entity_id GLOB 'nursery-13[0-9][0-9][0-9]-*'")} if pref == TOKYO else set()
        for f in read_facilities(path, pref):
            geo = gaz.locate(f["municipality"], f["street"]) if gaz else None
            muni = _municipality_of(Point(geo.lon, geo.lat), *index) if geo else None
            if muni is None:
                muni = names.get(normalize_municipality(f["municipality"]))
            if muni is None:
                r["no_municipality"] += 1
                continue
            if (muni, _name_key(f["name"])) in listed:
                r["in_tokyo_list"] += 1
                continue
            entity_id = f"nursery-{f['id']}" if f["id"] else \
                f"nursery-{muni.removeprefix('muni-')}-" + hashlib.sha1(
                    f"{f['name']}|{normalize(f['address'])}".encode()).hexdigest()[:10]
            upsert_entity(conn, entity_id, "nursery", f["name"], parent_id=muni)
            attrs = {"facility_type": f["type"], "capacity_kind": "利用定員", "founder": f["founder"],
                     "address": f["address"]}
            if geo:
                conn.execute(
                    """INSERT INTO locations (location_id, entity_id, role, lon, lat, source_id)
                       VALUES (?, ?, 'main', ?, ?, ?)
                       ON CONFLICT(location_id) DO UPDATE SET lon = excluded.lon, lat = excluded.lat,
                         source_id = excluded.source_id""",
                    (f"{entity_id}:main", entity_id, round(geo.lon, 6), round(geo.lat, 6), gz[geo.level][1]))
                attrs["precision"] = geo.precision
                r["located_block" if geo.precision == "街区" else "located_town"] += 1
            else:
                conn.execute("DELETE FROM locations WHERE entity_id = ?", (entity_id,))
                r["not_located"] += 1
                r["not_located_examples"].append(f"{f['name']}（{f['address']}）")
            conn.execute(
                """INSERT INTO entity_attributes (entity_id, attributes) VALUES (?, ?)
                   ON CONFLICT(entity_id) DO UPDATE SET attributes = excluded.attributes""",
                (entity_id, json.dumps(attrs, ensure_ascii=False)))
            base = dict(entity_id=entity_id, indicator_id=indicator_id,
                        definition_version=definition["definition_version"], period_start=period,
                        period_end=period, period_kind="point", source_id=source_id)
            cap = f["capacity"]
            insert_observation(conn, **base, value=None if cap is None else float(cap),
                               status="missing" if cap is None else "observed")
            r["with_capacity"] += cap is not None
            if f["users"] is not None:
                insert_observation(conn, **base, dimension_key="users", value=float(f["users"]), status="observed")
                for age, v in f["users_by_age"].items():
                    insert_observation(conn, **base, dimension_key=f"users:{age}", value=float(v),
                                       status="observed")
                r["with_users"] += 1
            r["facilities"] += 1
        r["not_located_examples"] = r["not_located_examples"][:20]
        result[pref] = r
    return result
