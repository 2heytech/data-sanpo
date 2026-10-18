"""道の駅の位置と、市区町村ごとの道の駅の数を取り込む（docs/design-changes.md #149）。

1. 国土交通省「道の駅」一覧（kind = mlit_michi_no_eki、list.xlsx）
   形式（2026-09-04 更新のファイルを 2026-10-18 に取得して確認）: シート「List」1枚。1行目が列名「県名」「駅 名」
   「登録回」「登録年月」「所在地」「ホームページアドレス」、2行目から1駅1行（1,234駅）。シートの範囲は65536行まであり、
   空の行が続く。所在地は市区町村名だけ（町村は郡付き、政令指定都市は区のない市の名前）。2つの市にまたがる駅は
   「静岡市・藤枝市」、都道府県名だけの行（「奈良県」）もある。登録年月は「H5.4」「R8.9」の形（全角の文字や空白が混じる）。
   駅名に「道の駅」は付かない。空白（全角・半角）・全角英数字・記号の表記ゆれがある。
2. 国土地理院の地名検索（kind = gsi_michi_no_eki、「道の駅」で引いた1回の結果）
   道の駅の点（2026-10-18 は1,232件）。題名は「道の駅「◯◯」」（後ろに「上り線」「下り線」が付くもの、
   「道の駅 「◯◯」」と空白の入るもの、宇津ノ谷峠は「「宇津ノ谷峠　静岡側」」「…藤枝側」の2点）。
   addressCode は市区町村コード（先頭の0がない数字。政令指定都市は区のコード）。
3. Wikidata（kind = wikidata_michi_no_eki、日本の道の駅 Q1187691 の項目のラベル・別名・座標）。地名検索にない駅に使う。
4. pipeline/config/michi_no_eki_locations.toml: どちらにもない駅（新しく登録された駅）の所在地と位置（手で書いた表）。

位置は、国土地理院の地名（名前が同じで、市区町村が一覧と同じもの。なければ県内で名前が1つだけのもの）、
なければ Wikidata（名前が同じで、位置が一覧の市区町村の中か近くにあるもの）、なければ手で書いた表の順に使う。
上り線・下り線などで点が2つある駅は、1つ目の点を地図に出す。

市区町村の数は一覧の所在地で数える（位置で数え直さない）。政令指定都市は、位置のある区で数える（位置がなければ
区は決めず、都道府県の数にだけ入れる）。2つの市にまたがる駅は両方の市で数え、都道府県の数は駅の数（重ねて数えない）。
一覧は全国の道の駅のすべてなので、一覧にない市区町村は0（道の駅がない）。
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tomllib
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import Point

from ..db import insert_observation, upsert_entity
from ..progress import progress
from ..regions import PREFECTURES
from ..xlsx import iter_sheet_rows
from .cfa_childcare import _municipalities
from .isj_geocode import normalize_municipality
from .mlit_stations import _municipality_index

ENTITY_TYPE = "roadside_station"
LOCATIONS = Path(__file__).resolve().parents[2] / "config" / "michi_no_eki_locations.toml"
MANUAL_SOURCE = {   # 手で付けた位置の出典（sources.json に載せる）
    "title": "道の駅の位置（新しく登録された駅。データさんぽで作成）", "provider": "データさんぽ",
    "url": "https://github.com/2heytech/data-sanpo/blob/main/pipeline/config/michi_no_eki_locations.toml",
    "license": "クリエイティブ・コモンズ 表示 4.0 国際", "license_url": "https://creativecommons.org/licenses/by/4.0/deed.ja",
    "attribution": "道の駅の位置：データさんぽ（国土交通省の登録の発表資料の所在地を国土地理院の地名検索で位置にしたもの）",
    "modification_note": "国土交通省の「道の駅」登録の発表資料にある所在地を、国土地理院の地名検索で位置にして作成",
    "redistributable": True,
}
NEAR_DEGREES = 0.05   # 約5km（Wikidata の位置が一覧の市区町村の外にあっても、この距離までは使う）
PREF_BY_NAME = {name: code for code, name in PREFECTURES.items()}
ERAS = {"H": 1988, "R": 2018}
VARIANTS = str.maketrans({"澤": "沢", "濱": "浜", "邊": "辺", "邉": "辺", "﨑": "崎", "髙": "高", "櫻": "桜", "國": "国",
                          "龍": "竜", "瀧": "滝", "廣": "広", "嶋": "島", "曾": "曽", "舘": "館", "冨": "富",
                          "ヶ": "ケ", "ヵ": "カ"})
BRACKETS = "()（）「」『』【】［］[]〈〉《》<>＜＞"
DASHES = "ー~〜～‐‑‒–—―−－-ｰ・･·．.,、。!！?？☆★♪♡"


@dataclass
class Station:
    pref: str                      # 都道府県コード2桁
    name: str                      # 一覧の駅名（_display でそろえたもの）
    address: str                   # 一覧の所在地（「足柄上郡松田町」など）
    round: int | None              # 登録回
    registered: str | None         # 登録年月（「1993年4月」）
    url: str | None
    munis: list[str] = field(default_factory=list)   # 所在地の市区町村の地域ID（政令指定都市は市の名前で wards から）
    cities: list[str] = field(default_factory=list)  # 所在地のうち政令指定都市の名前
    points: list[tuple[float, float]] = field(default_factory=list)
    loc_source: str = ""
    loc_note: str = ""            # 位置の注記（手で書いた表の位置だけ。おおよその位置など）


def _nfkc(s) -> str:
    return unicodedata.normalize("NFKC", str(s or "")).strip()


def _display(s) -> str:
    """表示する駅名・所在地。全角英数字は半角に、半角カナは全角にし（その文字だけ NFKC）、括弧や「～」「！」は
    一覧のままにする。空白は全角1つにそろえる。"""
    s = re.sub(r"[０-９Ａ-Ｚａ-ｚ\uff61-\uff9f]+", lambda m: unicodedata.normalize("NFKC", m.group()), str(s or ""))
    return re.sub(r"\s+", "　", s.strip())


def name_key(name: str, tier: int = 0) -> str:
    """駅名を照らし合わせるための鍵。「道の駅」・空白・括弧の記号を除き、旧字をそろえる。
    tier 1 は括弧を中身ごと除く（「はなやか(葉菜野花)小清水」と地名の「はなやか小清水」）。
    tier 2・3 は tier 0・1 からさらに長音・記号を除き、ひらがなをカタカナにする（「ゆ〜ゆ」と「ゆーゆ」など）。"""
    s = re.sub(r"\s+", "", _nfkc(name).lower()).translate(VARIANTS).replace("道の駅", "")
    if tier in (1, 3):
        s = re.sub(r"[(（「『【［\[〈《<＜][^)）」』】］\]〉》>＞]*[)）」』】］\]〉》>＞]", "", s)
    s = re.sub("[" + re.escape(BRACKETS) + "]", "", s)
    if tier >= 2:
        s = "".join(c for c in s if c not in DASHES and unicodedata.category(c)[0] in "LN")
        s = "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)
    return s


TIERS = range(4)


def _keys(names: list[str]) -> list[set[str]]:
    return [{k for n in names if (k := name_key(n, t))} for t in TIERS]


def _registered(cell) -> str | None:
    """「H5.4」「R8.9」→「1993年4月」。"""
    m = re.fullmatch(r"([HR])(\d+)\.(\d+)", re.sub(r"\s", "", _nfkc(cell)).upper())
    return f"{ERAS[m.group(1)] + int(m.group(2))}年{int(m.group(3))}月" if m else None


def read_list(path: Path) -> list[Station]:
    rows = iter_sheet_rows(path)
    head = [re.sub(r"\s", "", _nfkc(c)) for c in next(rows)]
    col = {name: head.index(name) for name in ("県名", "駅名", "登録回", "登録年月", "所在地", "ホームページアドレス")}
    out = []
    for r in rows:
        cell = lambda name: r[col[name]] if col[name] < len(r) else None   # noqa: E731
        pref = PREF_BY_NAME.get(re.sub(r"\s", "", _nfkc(cell("県名"))))
        name = _display(cell("駅名"))
        if not pref or not name:
            continue   # 空の行
        # 登録回は数値のセル（1.0）か文字（「第１回」）
        c = cell("登録回")
        m = re.search(r"\d+", _nfkc(c)) if not isinstance(c, (int, float)) else None
        rnd = str(int(c)) if isinstance(c, (int, float)) else m.group() if m else ""
        urls = re.findall(r"https?://\S+", _nfkc(cell("ホームページアドレス")))
        out.append(Station(pref=pref, name=name, address=re.sub(r"\s", "", _display(cell("所在地"))),
                           round=int(rnd) if rnd else None, registered=_registered(cell("登録年月")),
                           url=urls[0] if urls else None))
    return out


def read_gsi(path: Path) -> list[dict]:
    """国土地理院の地名検索の結果 → [{name, code, lon, lat}]。code は市区町村コード5桁（分からなければ空）。"""
    out = []
    for f in json.loads(path.read_text(encoding="utf-8")):
        title = (f.get("properties") or {}).get("title", "")
        m = re.match(r"^道の駅\s*「(.+?)」(.*)$", title)
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if not m or len(coords) != 2:
            continue
        code = str((f.get("properties") or {}).get("addressCode") or "")
        name = re.sub(r"[\s　]+(静岡側|藤枝側)$", "", m.group(1))   # 宇津ノ谷峠は両側に1点ずつ
        out.append({"name": name, "code": code.zfill(5) if code.isdigit() else "",
                    "lon": float(coords[0]), "lat": float(coords[1]),
                    "keys": _keys([name])})
    return out


def read_wikidata(path: Path) -> list[dict]:
    """Wikidata の道の駅 → [{names, lon, lat, qid}]。ラベルと別名（「|」区切り）を名前の候補にする。"""
    out = []
    for b in json.loads(path.read_text(encoding="utf-8")).get("results", {}).get("bindings", []):
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", b.get("coord", {}).get("value", ""))
        if not m:
            continue
        # ラベル・別名と、日本語版ウィキペディアの記事名（改名した駅は記事名が新しい名前のことがある）
        names = ([b.get(k, {}).get("value", "") for k in ("label", "jawiki")]
                 + b.get("alts", {}).get("value", "").split("|"))
        names = [n for n in names if n]
        out.append({"names": names, "lon": float(m.group(1)), "lat": float(m.group(2)),
                    "qid": b["item"]["value"].rsplit("/", 1)[-1],
                    "keys": _keys(names)})
    return out


def read_locations(path: Path = LOCATIONS) -> dict[tuple[str, str], dict]:
    """手で書いた位置（「都道府県名/駅名」→ {address, coord, note}）。"""
    if not path.exists():
        return {}
    out = {}
    for key, v in tomllib.loads(path.read_text(encoding="utf-8")).get("stations", {}).items():
        pref, name = key.split("/", 1)
        out[(PREF_BY_NAME[pref], name_key(name))] = v
    return out


def _resolve_municipalities(st: Station, names: dict, wards: dict) -> None:
    """所在地 → 市区町村の地域ID（政令指定都市は cities に市の名前）。"""
    if st.address in PREF_BY_NAME:
        return   # 都道府県名だけの行（位置の市区町村で決める）
    for part in re.split(r"[・、,/／]", st.address):
        key = (st.pref, normalize_municipality(part))
        if key in names:
            st.munis.append(names[key])
        elif key in wards:
            st.cities.append(normalize_municipality(part))


def _codes(st: Station, wards: dict) -> set[str]:
    """所在地の市区町村コード（政令指定都市は区のコード）。"""
    out = {m[5:] for m in st.munis}
    for city in st.cities:
        out |= {w[5:] for w in wards[(st.pref, city)]}
    return out


def _match_gsi(st: Station, places: list[dict], wards: dict) -> list[dict]:
    codes = _codes(st, wards)
    for t in TIERS:
        key = name_key(st.name, t)
        hit = [p for p in places if key in p["keys"][t]]
        same = [p for p in hit if p["code"] in codes]
        if same:
            return same
        # 市区町村が一覧と違う（境界の近くの駅など）・所在地が都道府県だけの行: 県内で同じ名前が1か所だけなら使う
        in_pref = [p for p in hit if p["code"][:2] == st.pref]
        if in_pref and len({p["name"] for p in in_pref}) == 1:
            return in_pref
    return []


def _near(point: Point, ids: list[str], index) -> bool:
    all_ids, geoms, tree = index
    want = set(ids)
    return any(all_ids[i] in want for i in tree.query(point.buffer(NEAR_DEGREES), predicate="intersects"))


def _match_wikidata(st: Station, items: list[dict], index, wards: dict) -> dict | None:
    ids = st.munis + [w for c in st.cities for w in wards[(st.pref, c)]]
    for t in TIERS:
        key = name_key(st.name, t)
        for it in items:
            if key in it["keys"][t] and ids and _near(Point(it["lon"], it["lat"]), ids, index):
                return it
    return None


def _ward_of(point: tuple[float, float], candidates: list[str], index) -> str | None:
    all_ids, geoms, tree = index
    p = Point(*point)
    want = set(candidates)
    hits = [i for i in tree.query(p, predicate="intersects") if all_ids[i] in want]
    if hits:
        return all_ids[hits[0]]
    near = [i for i in tree.query(p.buffer(NEAR_DEGREES), predicate="intersects") if all_ids[i] in want]
    return all_ids[min(near, key=lambda i: geoms[i].distance(p))] if near else None


def ingest(conn: sqlite3.Connection, list_file: tuple[Path, str], gsi_files: list[tuple[Path, str]],
           wikidata_files: list[tuple[Path, str]], manual_src: str, catalog: dict, period: str,
           boundary_version: str, prefs: list[str]) -> dict:
    stations = [s for s in read_list(list_file[0]) if s.pref in prefs]
    names, wards = _municipalities(conn)
    index = _municipality_index(conn, boundary_version, prefs)
    places = [(p, src) for path, src in gsi_files for p in read_gsi(path)]
    items = [(it, src) for path, src in wikidata_files for it in read_wikidata(path)]
    manual = read_locations()
    result = {"stations": len(stations), "gsi": 0, "wikidata": 0, "manual": 0, "no_location": 0, "unresolved": []}
    for st in stations:
        _resolve_municipalities(st, names, wards)
        got = _match_gsi(st, [p for p, _ in places], wards)
        if got:
            st.points = [(p["lon"], p["lat"]) for p in got]
            st.loc_source = next(src for p, src in places if p is got[0])
            if not st.munis and not st.cities:   # 所在地が都道府県だけの行は、地名の市区町村で数える
                code = got[0]["code"]
                st.munis = [f"muni-{code}"] if f"muni-{code}" in index[0] else []
            result["gsi"] += 1
        elif (it := _match_wikidata(st, [i for i, _ in items], index, wards)) is not None:
            st.points = [(it["lon"], it["lat"])]
            st.loc_source = next(src for i, src in items if i is it)
            result["wikidata"] += 1
        elif (m := manual.get((st.pref, name_key(st.name)))) is not None:
            st.points = [tuple(m["coord"])]
            st.loc_source = manual_src
            st.loc_note = m.get("note", "所在地から求めた位置")
            result["manual"] += 1
        else:
            result["no_location"] += 1
            progress(f"道の駅の位置が分かりません: {PREFECTURES[st.pref]} {st.name}（{st.address}）")
        # 政令指定都市は位置の区で数える
        for city in st.cities:
            ward = next((w for pt in st.points if (w := _ward_of(pt, wards[(st.pref, city)], index))), None)
            if ward:
                st.munis.append(ward)
        if not st.munis:
            result["unresolved"].append(f"{st.name}（{st.address}）")
    if result["unresolved"]:
        progress("市区町村の決まらない道の駅（都道府県の数にだけ入れる）: " + "、".join(result["unresolved"]))

    for st in stations:
        eid = "michi-" + hashlib.sha1(f"{st.pref}/{name_key(st.name)}".encode()).hexdigest()[:10]
        upsert_entity(conn, eid, ENTITY_TYPE, st.name, parent_id=st.munis[0] if st.munis else None)
        if st.points:
            conn.execute(
                """INSERT INTO locations (location_id, entity_id, role, lon, lat, source_id)
                   VALUES (?, ?, 'main', ?, ?, ?)
                   ON CONFLICT(location_id) DO UPDATE SET lon = excluded.lon, lat = excluded.lat,
                     source_id = excluded.source_id""",
                (f"{eid}:main", eid, round(st.points[0][0], 6), round(st.points[0][1], 6), st.loc_source))
        attrs = {"prefecture": st.pref, "address": st.address, "round": st.round, "registered": st.registered,
                 "url": st.url, "municipalities": st.munis, "location_note": st.loc_note or None,
                 "source_id": list_file[1], "as_of": period}
        conn.execute(
            """INSERT INTO entity_attributes (entity_id, attributes) VALUES (?, ?)
               ON CONFLICT(entity_id) DO UPDATE SET attributes = excluded.attributes""",
            (eid, json.dumps(attrs, ensure_ascii=False)))

    # 市区町村・都道府県の数（一覧にない市区町村は0）
    by_muni: dict[str, int] = defaultdict(int)
    by_pref: dict[str, int] = defaultdict(int)
    for st in stations:
        for m in dict.fromkeys(st.munis):
            by_muni[m] += 1
        by_pref[st.pref] += 1
    for indicator_id, d in catalog.items():
        if d.get("source_kind") != "mlit_michi_no_eki":
            continue
        base = dict(indicator_id=indicator_id, definition_version=d["definition_version"], period_start=period,
                    period_end=period, period_kind="point", source_id=list_file[1], status="observed")
        for muni in index[0]:
            insert_observation(conn, entity_id=muni, value=float(by_muni.get(muni, 0)), **base)
        for pref in sorted({m[5:7] for m in index[0]}):
            insert_observation(conn, entity_id=f"pref-{pref}", value=float(by_pref.get(pref, 0)), **base)
    return result
