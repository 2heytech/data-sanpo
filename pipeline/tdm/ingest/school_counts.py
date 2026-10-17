"""東京都以外の公立小中学校の、学校ごとの児童・生徒数を取り込む（docs/design-changes.md #138）。

学校ごとの数を商用利用できる条件（CC BY 4.0・公共データ利用規約 PDL1.0）で県内全域分出している道県と、
市だけで出している市の一覧を、出典ごとの読み方（READERS。sources.toml の reader で選ぶ）で読み、
学校の点（国土数値情報「学校データ」P29 の位置、mlit_facilities.py）に人数を付ける。
読み方は都道府県・市ごとに school_readers.py にある。

突き合わせ（P29 は2023年度、出典は2024〜2026年度）:
  1. 文部科学省の学校コード（13桁、例: B111210000017）が出典にあれば、P29 の学校コード（P29_002）とそのまま対応する。
  2. なければ、設置者の市区町村名・学校の種類・学校名（「札幌市立」「小学校」などを除いた部分）が同じ学校。
     市区町村の分からない学校（都道府県立）は、学校の種類と学校名が同じ学校が都道府県の中に1つだけならそれ。
  3. 1・2 を全校で決めたあと、残った学校は、同じ市区町村で学校名が同じ義務教育学校（またはその逆）。
  対応する点がない学校（2024年度以降に開校・統合した学校など）は、出典に所在地があれば位置参照情報で位置を求め、
  なければ位置なしにする（地図には描かない）。出典が扱う市区町村にあって一覧にない P29 の学校（休校・閉校、
  学校名の違いなど）は、位置だけの点のまま、見つからなかった一覧（unlisted）を残す。

人数は元データの総数（学年別があれば学年別も）。休校の学校（総数が0・「休校」の行）は値を作らない（0人にしない）。
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import Point

from ..db import insert_observation, upsert_entity
from ..regions import PREFECTURES
from ..xlsx import read_sheet, sheet_names
from .isj_geocode import Gazetteer, kanji_number, normalize, normalize_municipality
from .mlit_stations import _municipality_index, _municipality_of

TYPES = {"elementary": "小学校", "junior_high": "中学校", "compulsory": "義務教育学校"}


@dataclass
class SchoolCount:
    """出典の1校。"""
    pref: str              # 都道府県コード2桁
    municipality: str      # 設置者の市区町村名（例: 「札幌市」「上川郡東川町」）。都道府県立は所在地の市区町村名か ""
    name: str              # 学校名（元データの書き方のまま。「中央」「中央小学校」「札幌市立中央小学校」など）
    school_type: str       # elementary | junior_high | compulsory
    year: int              # 年度（5月1日現在の値）
    total: int             # 児童・生徒数の総数
    grades: dict[str, int] = field(default_factory=dict)   # 「1年」〜「9年」（中学校は「1年」〜「3年」）
    code: str | None = None      # 文部科学省の学校コード（13桁）
    address: str | None = None   # 所在地（都道府県名・市区町村名から書いた住所でもよい）
    founder: str = "市区町村立"    # 「都道府県立」なら都道府県立の学校


def cell_text(cell) -> str:
    """表のセルを文字にする（全角・半角をそろえ、空白を除く。整数の数値は「12」）。"""
    if cell is None:
        return ""
    if isinstance(cell, float):
        return str(int(cell)) if cell.is_integer() else str(cell)
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(cell)))


def cell_int(cell) -> int | None:
    """人数のセル。空欄・「-」などは None（読めない値は 0 にしない）。"""
    if isinstance(cell, (int, float)):
        return int(cell)
    s = cell_text(cell).replace(",", "")
    return int(s) if re.fullmatch(r"\d+", s) else None


def workbook(path: Path) -> list[tuple[str, list[list]]]:
    """Excel のシート（名前と行）。旧形式（.xls）は xlrd で読み、空のセルは None にそろえる。"""
    if zipfile.is_zipfile(path) and "xl/workbook.xml" in zipfile.ZipFile(path).namelist():
        return [(name, read_sheet(path, name)) for name in sheet_names(path)]
    import xlrd
    book = xlrd.open_workbook(str(path))
    return [(s.name, [[None if v == "" else v for v in s.row_values(i)] for i in range(s.nrows)])
            for s in book.sheets()]


# --- 学校名の突き合わせ ------------------------------------------------------------------------------------

FOUNDER = re.compile(r"^(.+?(?:市|区|町|村|組合|都|道|府|県))立")
TYPE_WORDS = re.compile(r"(義務教育学校|小学校|中学校)")


def core_name(name: str, municipality: str = "") -> str:
    """学校名から設置者（「札幌市立」）と学校の種類（「小学校」）を除いた部分。分校は「市場けやき分校」の形。"""
    s = normalize(name)
    s = re.sub(r"^.+?[都道府県]立", "", s) if re.match(r"^.{2,3}[都道府県]立", s) else s
    s = FOUNDER.sub("", s, count=1)
    m = normalize_municipality(municipality) if municipality else ""
    if m and re.match(rf"^[^郡]+郡{re.escape(m)}", s):
        s = s[s.index("郡") + 1:]   # 「名西郡神山町広野小学校」
    if m and s.startswith(m) and len(s) > len(m):
        s = s[len(m):]        # 「徳島市内町小学校」のように「立」のない学校名
    s = TYPE_WORDS.sub("", s)
    s = re.sub(r"第(\d{1,2})", lambda x: "第" + kanji_number(int(x.group(1))), s)
    return s.replace("・", "").replace("(", "").replace(")", "")


def founder_of(name: str) -> str | None:
    """P29 の学校名（「札幌市立中央小学校」）の設置者（「札幌市」）。"""
    m = FOUNDER.match(normalize(name))
    return m.group(1) if m else None


@dataclass
class Point29:
    entity_id: str
    name: str
    school_type: str
    municipalities: set[str]   # 設置者・所在地の市区町村名（郡名なし。政令指定都市の区は市と区の両方）
    attrs: dict


def p29_points(conn: sqlite3.Connection, pref: str) -> list[Point29]:
    """都道府県の P29 の学校の点（位置だけの点として取り込んだもの）。"""
    names = {r["entity_id"]: (r["name"], r["region"]) for r in conn.execute(
        "SELECT entity_id, name, region FROM entities WHERE entity_type = 'municipality' AND entity_id LIKE ?",
        (f"muni-{pref}%",))}
    out = []
    for r in conn.execute(
            """SELECT e.entity_id, e.name, e.parent_id, a.attributes FROM entities e
               JOIN entity_attributes a ON a.entity_id = e.entity_id
               WHERE e.entity_type = 'school' AND e.entity_id LIKE 'school-B1%' AND e.parent_id LIKE ?""",
            (f"muni-{pref}%",)):
        attrs = json.loads(r["attributes"] or "{}")
        parent, region = names.get(r["parent_id"], ("", None))
        munis = {normalize_municipality(m) for m in (founder_of(r["name"]), region, parent) if m}
        out.append(Point29(r["entity_id"], r["name"], attrs.get("school_type", ""), munis, attrs))
    return out


class Matcher:
    """出典の学校を P29 の点に対応させる（同じ点に2校を対応させない）。"""

    def __init__(self, points: list[Point29]) -> None:
        self.by_id = {p.entity_id: p for p in points}
        self.full: dict[tuple, list[Point29]] = defaultdict(list)      # (市区町村, 種類, 名前)
        self.any_type: dict[tuple, list[Point29]] = defaultdict(list)  # (市区町村, 名前)
        self.no_muni: dict[tuple, list[Point29]] = defaultdict(list)   # (種類, 名前)
        for p in points:
            founder = founder_of(p.name) or ""
            cores = {core_name(p.name, m) for m in sorted(p.municipalities)} if not founder else \
                {core_name(p.name, founder), core_name(normalize(p.name)[len(founder):], "")}
            # 「小松島市立江小学校」（立江小）は「小松島市立」を除くと「江」になるので、市の名前だけを除いた
            # 「立江」でも引けるようにする
            for core in cores:
                for m in p.municipalities:
                    self.full[(m, p.school_type, core)].append(p)
                    self.any_type[(m, core)].append(p)
                self.no_muni[(p.school_type, core)].append(p)
        self.used: set[str] = set()

    def match_all(self, schools: list[SchoolCount]) -> list[Point29 | None]:
        """学校コード・種類まで同じ名前の対応を先に全校で決め、そのあとで種類の違う対応（小中学校が義務教育学校に
        なったなど）を探す。1校ずつ順に探すと、新しく開校した「蒲原小」が P29 の「蒲原中学校」の点を取ってしまうため。"""
        out: list[Point29 | None] = [None] * len(schools)
        for loose in (False, True):
            for i, s in enumerate(schools):
                if out[i] is None:
                    out[i] = self._match(s, loose)
        return out

    def match(self, s: SchoolCount) -> Point29 | None:
        """1校だけ探す（確かめる用。取り込みは match_all）。"""
        return self.match_all([s])[0]

    def _match(self, s: SchoolCount, loose: bool) -> Point29 | None:
        if not loose and s.code and (p := self.by_id.get(f"school-{s.code}")) and p.entity_id not in self.used:
            return self._take(p)
        muni = normalize_municipality(s.municipality) if s.municipality else ""
        core = core_name(s.name, muni)
        if not muni:   # 市区町村の分からない学校（都道府県立など）
            keys = [] if loose else [(self.no_muni, (s.school_type, core))]
        elif loose:    # 種類が違ってよいのは、どちらかが義務教育学校のときだけ
            keys = [(self.any_type, (muni, core))]
        else:
            keys = [(self.full, (muni, s.school_type, core))]
        for table, key in keys:
            hits = {p.entity_id: p for p in table.get(key, []) if p.entity_id not in self.used
                    and (not loose or "compulsory" in (p.school_type, s.school_type))}
            if len(hits) == 1:
                return self._take(next(iter(hits.values())))
        return None

    def _take(self, p: Point29) -> Point29:
        self.used.add(p.entity_id)
        return p


# --- 取り込み -------------------------------------------------------------------------------------------

def _founder_label(s: SchoolCount, p: Point29 | None) -> str:
    if s.founder == "都道府県立":
        return f"{PREFECTURES[s.pref]}立"
    if p and (founder := founder_of(p.name)):
        return f"{founder}立"
    return f"{normalize_municipality(s.municipality)}立" if s.municipality else "市区町村立"


def _display_name(s: SchoolCount) -> str:
    name = unicodedata.normalize("NFKC", s.name).strip()
    if re.search(r"(学校|学園|分校)$", name):
        return name
    return name + TYPES[s.school_type]


def _municipality_by_name(conn: sqlite3.Connection, pref: str) -> dict[str, str]:
    """市区町村名（郡名なし）→ 地域ID。政令指定都市の区は「川崎市中原区」でも引けるようにする。"""
    out = {}
    for r in conn.execute("SELECT entity_id, name, region FROM entities WHERE entity_type = 'municipality' "
                          "AND entity_id LIKE ?", (f"muni-{pref}%",)):
        name = normalize_municipality(r["name"])
        out[name] = r["entity_id"]
        if r["region"] and not name.startswith(normalize(r["region"])):
            out[normalize(r["region"]) + name] = r["entity_id"]
    return out


def ingest(conn: sqlite3.Connection, batches: list[tuple[list[SchoolCount], str]], indicator_id: str,
           definition: dict, boundary_version: str, gazetteers: dict[str, dict] | None = None) -> dict:
    """batches: [(出典の学校の一覧, source_id)]。gazetteers: 都道府県コード → {"block"|"oaza": (ファイル, source_id)}
    （位置参照情報。P29 にない学校の所在地から位置を求める）。"""
    gazetteers = gazetteers or {}
    by_pref: dict[str, list[tuple[SchoolCount, str]]] = defaultdict(list)
    for schools, source_id in batches:
        for s in schools:
            by_pref[s.pref].append((s, source_id))
    result: dict = {}
    index = None
    for pref, items in sorted(by_pref.items()):
        matcher = Matcher(p29_points(conn, pref))
        munis = _municipality_by_name(conn, pref)
        gz = gazetteers.get(pref, {})
        gaz = Gazetteer.read(gz["block"][0] if "block" in gz else None,
                             gz["oaza"][0] if "oaza" in gz else None) if gz else None
        r = {"schools": 0, "matched": 0, "located_by_address": 0, "not_located": 0, "closed_or_zero": 0,
             "no_municipality": 0, "unlisted": 0, "unmatched_examples": []}
        # 同じ学校の複数年度は同じ点に付ける（いちばん新しい年度の行で突き合わせる）
        groups: dict[tuple, list[tuple[SchoolCount, str]]] = defaultdict(list)
        for s, source_id in sorted(items, key=lambda x: -x[0].year):
            if s.total <= 0:
                r["closed_or_zero"] += 1   # 休校など。0人の値は作らない
                continue
            groups[(s.code or "", normalize_municipality(s.municipality), s.school_type,
                    core_name(s.name, s.municipality))].append((s, source_id))
        keys = list(groups)
        points = matcher.match_all([groups[k][0][0] for k in keys])
        covered: dict[str, tuple[int, str]] = {}   # 出典が扱う市区町村 → (年度, 出典)
        for key, p in zip(keys, points):
            s, source_id = groups[key][0]
            names = set(p.municipalities) if p else set()
            if s.municipality and s.founder != "都道府県立":
                names.add(normalize_municipality(s.municipality))
            for m in names:
                if s.year >= covered.get(m, (0, ""))[0]:
                    covered[m] = (s.year, source_id)
        for key, p in zip(keys, points):
            s = groups[key][0][0]
            if p:
                entity_id = p.entity_id
                attrs = {k: v for k, v in p.attrs.items() if k not in ("location_only", "as_of", "unlisted")}
                attrs["founder"] = _founder_label(s, p)
                if s.address and not attrs.get("address"):
                    attrs["address"] = s.address
                _set_attrs(conn, entity_id, attrs)
                r["matched"] += 1
            else:
                if index is None:
                    index = _municipality_index(conn, boundary_version)
                entity_id = _add_school(conn, s, munis, gaz, gz, index, r)
                if entity_id is None:
                    continue
            r["schools"] += 1
            for s, source_id in groups[key]:
                base = dict(entity_id=entity_id, indicator_id=indicator_id,
                            definition_version=definition["definition_version"],
                            period_start=f"{s.year}-05-01", period_end=f"{s.year}-05-01", period_kind="point",
                            source_id=source_id)
                insert_observation(conn, **base, value=float(s.total), status="observed")
                for g, v in s.grades.items():
                    insert_observation(conn, **base, dimension_key=g, value=float(v), status="observed")
        # 出典が扱う市区町村にあって一覧に見つからなかった P29 の学校（休校・閉校、学校名の違いなど）は、
        # 位置だけの点のまま、どの一覧に見つからなかったかを残す（画面で「公開データなし」と区別する）
        for p in matcher.by_id.values():
            hit = next((covered[m] for m in sorted(p.municipalities) if m in covered), None)
            if p.entity_id in matcher.used or hit is None:
                continue
            _set_attrs(conn, p.entity_id, {**p.attrs, "unlisted": {"year": hit[0], "source_id": hit[1]}})
            r["unlisted"] += 1
        r["p29_without_counts"] = sum(1 for p in matcher.by_id.values() if p.entity_id not in matcher.used)
        r["unmatched_examples"] = r["unmatched_examples"][:20]
        result[pref] = r
    return result


def _set_attrs(conn: sqlite3.Connection, entity_id: str, attrs: dict) -> None:
    conn.execute(
        """INSERT INTO entity_attributes (entity_id, attributes) VALUES (?, ?)
           ON CONFLICT(entity_id) DO UPDATE SET attributes = excluded.attributes""",
        (entity_id, json.dumps(attrs, ensure_ascii=False)))


def _add_school(conn, s: SchoolCount, munis: dict[str, str], gaz: Gazetteer | None, gz: dict, index,
                r: dict) -> str | None:
    """P29 に対応する点がない学校。所在地があれば位置を求め、市区町村は位置（なければ設置者の名前）から決める。"""
    muni_name = normalize_municipality(s.municipality) if s.municipality else ""
    geo = None
    by_address = None   # 所在地の先頭の市区町村（政令指定都市の区まで分かる）
    if s.address:
        a = normalize(s.address).removeprefix(PREFECTURES[s.pref])
        for m in sorted(munis, key=len, reverse=True):
            if a.startswith(m) or re.match(rf"^.+?郡{re.escape(m)}", a):
                by_address = munis[m]
                a = a[a.index(m) + len(m):]
                geo = gaz.locate(m, a) if gaz and a else None
                break
    muni = _municipality_of(Point(geo.lon, geo.lat), *index) if geo else None
    if muni is None:
        muni = by_address or munis.get(muni_name)
    if muni is None:
        r["no_municipality"] += 1
        r["unmatched_examples"].append(f"{s.municipality} {s.name}（市区町村が分からない）")
        return None
    digest = hashlib.sha1(f"{muni}|{s.school_type}|{core_name(s.name, muni_name)}".encode()).hexdigest()[:10]
    entity_id = f"school-{s.code}" if s.code else f"school-{s.pref}-{digest}"
    upsert_entity(conn, entity_id, "school", _display_name(s), parent_id=muni)
    attrs = {"school_type": s.school_type, "type_label": TYPES[s.school_type],
             "founder": _founder_label(s, None), "address": s.address}
    if geo:
        conn.execute(
            """INSERT INTO locations (location_id, entity_id, role, lon, lat, source_id)
               VALUES (?, ?, 'main', ?, ?, ?)
               ON CONFLICT(location_id) DO UPDATE SET lon = excluded.lon, lat = excluded.lat,
                 source_id = excluded.source_id""",
            (f"{entity_id}:main", entity_id, round(geo.lon, 6), round(geo.lat, 6), gz[geo.level][1]))
        attrs["precision"] = geo.precision
        r["located_by_address"] += 1
    else:
        r["not_located"] += 1
        r["unmatched_examples"].append(f"{s.municipality} {s.name}")
    _set_attrs(conn, entity_id, attrs)
    return entity_id
