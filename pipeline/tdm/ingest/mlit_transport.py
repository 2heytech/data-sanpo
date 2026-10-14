"""空港の乗降客数（国土交通省「空港管理状況調書」）と港の船舶乗降人員（「港湾統計（年報）」第2表）を取り込む。

どちらも空港・港ごとの年の値で、位置は別の出典から付ける（空港は国土数値情報 C28、港は Wikidata と
pipeline/config/port_locations.toml）。空港・港1か所の値なので、市区町村・都道府県には割り振らない
（空港・港のない市区町村が大半で、港は複数の市町村にまたがるものもある）。市区町村は一覧・地図の都道府県分けに使う。

内訳（dimension_key）: all（合計）、domestic（国内線・国内航路）、international（国際線・外国航路）。
表の「-」（該当なし）は 0 とし、読めない値は値なしにする（0 にしない）。
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tomllib
import unicodedata
from pathlib import Path

from shapely.geometry import Point, shape

from ..db import insert_observation, upsert_entity
from ..progress import progress
from ..sources import register_source
from ..regions import PREFECTURES
from ..xlsx import read_sheet, sheet_names
from .mlit_stations import _municipality_index, _municipality_of

DIMENSIONS = ("all", "domestic", "international")
PORT_NEAR_DEGREES = 0.05   # 約5km
ZERO = {"-", "－", "―", "‐", "—", "–"}
MARKS = "☆◎○●◇◆△▲※*＊"
PORT_LOCATIONS = Path(__file__).resolve().parents[2] / "config" / "port_locations.toml"
MANUAL_SOURCE = {   # 手で付けた港の位置の出典（sources.json に載せる）
    "title": "港の代表地点（データさんぽで作成）", "provider": "データさんぽ",
    "url": "https://github.com/2heytech/data-sanpo/blob/main/pipeline/config/port_locations.toml",
    "license": "クリエイティブ・コモンズ 表示 4.0 国際", "license_url": "https://creativecommons.org/licenses/by/4.0/deed.ja",
    "attribution": "港の位置：データさんぽ（Wikidata にない港）", "redistributable": True,
}


def _t(cell) -> str:
    return re.sub(r"\s", "", unicodedata.normalize("NFKC", str(cell))) if cell is not None else ""


def _num(cell) -> float | None:
    if isinstance(cell, (int, float)):
        return float(cell)
    s = _t(cell).replace(",", "")
    if s in ZERO:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


def _is_num(cell) -> bool:
    return _num(cell) is not None


def _preview(rows: list[list], start: int, n: int, width: int = 18) -> list[str]:
    return [f"  {i}: " + " | ".join(_t(c)[:12] for c in r[:width]) for i, r in enumerate(rows[start:start + n], start)]


# --- 空港 -----------------------------------------------------------------------

AIRPORT_ALIASES = {"石垣": "新石垣"}   # 調書と国土数値情報で名前が違う空港（調書 → 国土数値情報）


def norm_airport(name: str) -> str:
    """空港名の比べ方。「東京国際空港」と「東京国際」、「新千歳空港」と「新千歳」を同じにする。"""
    s = re.sub(r"[(（].*?[)）]", "", _t(name))
    for w in ("国際空港", "空港", "飛行場", "国際"):
        s = s.replace(w, "")
    return AIRPORT_ALIASES.get(s, s)


MONTHS = [f"{m}月" for m in range(1, 13)]


def _airport_columns(rows: list[list], h: int) -> dict[str, int]:
    """見出し（h 行目から3行）の列。乗降客数の下に「国際線（乗客・降客・通過客・小計）」「国内線（乗客・降客・小計）」
    「合計」が並ぶので、乗降客数より右で次の項目（航空燃料供給量）より左の「小計」を国際線・国内線、「合計」を合計にする。"""
    c0 = next(j for j, c in enumerate(rows[h]) if "乗降客" in _t(c))
    end = next((j for j in range(c0 + 1, len(rows[h])) if _t(rows[h][j])), max(len(r) for r in rows[h:h + 4]))
    found: dict[str, list[int]] = {"小計": [], "合計": []}
    for r in rows[h + 1:h + 4]:
        for j in range(c0, min(end, len(r))):
            if _t(r[j]) in found:
                found[_t(r[j])].append(j)
    sub = sorted(set(found["小計"]))
    cols = {}
    if len(sub) >= 2:
        cols["international"], cols["domestic"] = sub[0], sub[1]
    if found["合計"]:
        cols["all"] = max(found["合計"])
    return cols


def read_airports(path: Path) -> tuple[dict[str, dict[str, float | None]], list[str], bool]:
    """空港名 → {all, domestic, international}（1年の乗降客数）、調べた表の様子（ログ用）、年度の表か。

    形式（2016〜2025年分を 2026-10-14 に GitHub Actions から取得して確認）: 1シートに空港ごとの欄が縦に並ぶ。
    欄の1行目に「空港名:」と空港名（例「成田国際(会社管理)」）、続く3行が見出し（項目／着陸回数(回)・乗降客数(人)・
    航空燃料供給量(KL)…）、その下に1月〜12月の行。乗降客数は国際線（乗客・降客・通過客・小計）・国内線（乗客・降客・小計）・合計。
    年の値は「計」「合計」の行があればその値、なければ12か月の合計（どれかの月が空なら値なし）。"""
    notes: list[str] = []
    out: dict[str, dict[str, float | None]] = {}
    fiscal = False
    for sheet in sheet_names(path):
        rows = read_sheet(path, sheet)
        starts = [i for i, r in enumerate(rows) if any(_t(c).startswith("空港名") for c in r)]
        if not starts:
            continue
        notes.append(f"{path.name} シート「{sheet}」 空港の欄 {len(starts)}")
        notes += _preview(rows, starts[0], 6)
        for n, i in enumerate(starts):
            r = rows[i]
            k = next(j for j, c in enumerate(r) if _t(c).startswith("空港名"))
            name = next((_t(c) for c in r[k + 1:] if _t(c)), "")
            name = re.sub(r"[(（].*?[)）]$", "", name) or name
            block = rows[i:starts[n + 1] if n + 1 < len(starts) else len(rows)]
            h = next((x for x, b in enumerate(block[:6]) if any("乗降客" in _t(c) for c in b)), None)
            if not name or h is None or "計" in name:   # 会社管理空港計・全空港計などの合計の欄
                continue
            cols = _airport_columns(block, h)
            if not cols:
                continue
            months: dict[str, list] = {}
            year_row = None
            for b in block[h + 1:]:
                labels = [_t(c) for c in b[:min(cols.values())] if isinstance(c, str) and _t(c)]
                lab = labels[-1] if labels else ""
                if lab in MONTHS:
                    if lab in months:      # 同じ欄の下の表（貨物・郵便など）の月の行
                        break
                    months[lab] = b
                elif lab in ("計", "合計", "年計", "年間計") and year_row is None:
                    year_row = b
            if months:
                first = next(lab for lab in (_t(c) for b in block[h + 1:] for c in b if isinstance(c, str))
                             if lab in MONTHS)
                fiscal = fiscal or first == "4月"
            vals: dict[str, float | None] = {}
            for key, j in cols.items():
                if year_row is not None:
                    vals[key] = _num(year_row[j]) if j < len(year_row) else None
                else:
                    ms = [_num(m[j]) if j < len(m) else None for m in months.values()]
                    vals[key] = sum(ms) if len(ms) == 12 and all(v is not None for v in ms) else None
            if n == 0:
                notes.append(f"  列 {cols} 年の行 {'あり' if year_row is not None else 'なし（12か月の合計）'}")
            out.setdefault(name, {d: vals.get(d) for d in DIMENSIONS})
    notes.append(f"  空港 {len(out)} か所{'（年度の表）' if fiscal else ''}: " + "、".join(
        f"{k} {v['all']:,.0f}" if v["all"] is not None else k for k, v in list(out.items())[:8]) + " …")
    return out, notes, fiscal


def read_airport_locations(files: list[Path]) -> tuple[dict[str, tuple[float, float, str]], list[str]]:
    """国土数値情報 C28 → 正規化した空港名 → (経度, 緯度, 名前)。

    形式（C28-21 を 2026-10-14 に GitHub Actions から取得して確認）: UTF-8/C28-21_Airport.geojson が空港の範囲（面）で
    C28_005 が名前、C28_101 が空港標点の参照（「#cf03_00001」）。C28-21_AirportReferencePoint.geojson が標点（点）で
    C28_000 がその番号。標点があればその位置、なければ範囲の中の1点にする。"""
    utf8 = [f for f in files if "utf" in str(f).lower()] or files
    points: dict[str, tuple[float, float]] = {}
    areas = []
    notes = []
    for f in utf8:
        try:
            feats = json.loads(f.read_text(encoding="utf-8")).get("features", [])
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        notes.append(f"{f.name}: {len(feats)} 地物")
        for ft in feats:
            p, g = ft.get("properties") or {}, ft.get("geometry")
            if not g:
                continue
            if g["type"] == "Point" and p.get("C28_000"):
                points[p["C28_000"]] = tuple(g["coordinates"][:2])
            elif p.get("C28_005"):
                areas.append((_t(p["C28_005"]), str(p.get("C28_101") or "").lstrip("#"), shape(g)))
    out: dict[str, tuple[float, float, str]] = {}
    for name, ref, geom in areas:
        key = norm_airport(name)
        if ref in points:
            out[key] = (*points[ref], name)
        elif key not in out:
            c = geom.representative_point()
            out[key] = (c.x, c.y, name)
    notes.append(f"空港 {len(out)} か所（標点 {len(points)}）")
    return out, notes


# --- 港 -------------------------------------------------------------------------

PREF_NAMES = {name: code for code, name in PREFECTURES.items()}
PORT_LABELS = {"外": "international", "内": "domestic", "計": "all"}


SHORT_PREFS = {(n if n == "北海道" else n[:-1]): c for n, c in PREF_NAMES.items()}


def _pref_of(text: str) -> str | None:
    """「北海道」「千葉」「東京都」など、都道府県名（「都・府・県」のない形も）の都道府県コード。"""
    return PREF_NAMES.get(text) or SHORT_PREFS.get(text)


def port_name(text: str) -> str:
    return _t(text).strip(MARKS)


def norm_port(name: str) -> str:
    s = re.sub(r"[(（].*?[)）]", "", port_name(name))
    return s.removesuffix("港")


def read_ports(path: Path) -> tuple[dict[tuple[str, str], dict[str, float | None]], list[str]]:
    """(都道府県コード, 港名) → {all, domestic, international}。

    形式（2020〜2024年の甲種港湾 2-2・乙種港湾 3-2 を 2026-10-14 に GitHub Actions から取得して確認）: シート「2-2」「3-2」が
    印刷向けで、1行に左右2つの欄（都道府県・港湾の印・港湾名・種別・計・乗込人員・上陸人員）が並ぶ。都道府県は「千葉」のように
    「県」を付けない名前で、都道府県の最初の行に「合計」と一緒に出る。種別は「計」「外」（外国航路）「内」（国内航路）で、
    外国航路のない港は「内」の行だけ。港名の前の ☆◎○ は港湾の種類の印。総計・国際戦略港湾計などの行も同じ欄にある。"""
    out: dict[tuple[str, str], dict[str, float | None]] = {}
    notes = []
    for sheet in sheet_names(path):
        rows = read_sheet(path, sheet)
        names: dict[int, str] = {}     # 欄（「外・内・計」の列）ごとの直前の港名
        prefs: dict[int, str] = {}     # 欄ごとの直前の都道府県
        n0 = len(out)
        for r in rows:
            for j, c in enumerate(r):
                lab = _t(c)
                if lab not in PORT_LABELS or j + 1 >= len(r) or not _is_num(r[j + 1]):
                    continue
                # 都道府県は「種別」の4つ左の列、港名はその間の列（港名と同じ名前の都道府県もある: 千葉港・東京港など）
                if j >= 4 and _pref_of(port_name(r[j - 4])):
                    prefs[j] = _pref_of(port_name(r[j - 4]))
                left = [port_name(r[k]) for k in range(max(0, j - 3), j)
                        if isinstance(r[k], str) and port_name(r[k]) and not _is_num(r[k])]
                if left or (j >= 4 and _t(r[j - 4])):
                    names[j] = "" if not left or "計" in left[-1] else left[-1]   # 合計・総計の行は港ではない
                name, pref = names.get(j, ""), prefs.get(j)
                if not name or not pref:
                    continue
                out.setdefault((pref, name), {k: None for k in DIMENSIONS})[PORT_LABELS[lab]] = _num(r[j + 1])
        if len(out) > n0:
            notes.append(f"{path.name} シート「{sheet}」 港 {len(out) - n0}")
    for v in out.values():
        if v["all"] is None and (v["domestic"] is not None or v["international"] is not None):
            v["all"] = (v["domestic"] or 0) + (v["international"] or 0)   # 片方だけの港（もう片方は表に行がない＝該当なし）
    notes.append(f"  港 {len(out)} か所: " + "、".join(
        f"{PREFECTURES[p]}{n} {v['all']:,.0f}" for (p, n), v in list(out.items())[:10]) + " …")
    return out, notes


def read_wikidata_ports(path: Path) -> dict[tuple[str | None, str], tuple[float, float, str]]:
    """Wikidata の港 → (都道府県コード, 正規化した名前) → (経度, 緯度, QID)。同じ名前が複数あれば番号の小さい項目。
    ラベル（label）か日本語版ウィキペディアの記事名（title、「大島港 (香川県)」など）で名前を取る。
    都道府県の分からない項目（所在地 P131 がない）は都道府県を None にし、位置の市区町村で確かめてから使う。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[tuple[str | None, str], tuple[float, float, str]] = {}
    for b in data.get("results", {}).get("bindings", []):
        name = (b.get("label") or b.get("title") or {}).get("value", "")
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", b.get("coord", {}).get("value", ""))
        if not name or not m:
            continue
        paren = re.search(r"[(（](.+?)[)）]", name)
        pref = PREF_NAMES.get(b.get("prefLabel", {}).get("value", "")) or (paren and PREF_NAMES.get(paren.group(1)))
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        key = (pref or None, norm_port(name))
        if key not in out or int(qid[1:]) < int(out[key][2][1:]):
            out[key] = (float(m.group(1)), float(m.group(2)), qid)
    return out


def _gsi_places(path: Path, want: str) -> list[tuple[float, float, str]]:
    """国土地理院の地名検索の結果のうち、名前が want で終わる地名の (経度, 緯度, 名前)。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return []
    out = []
    for f in data if isinstance(data, list) else []:
        title = (f.get("properties") or {}).get("title", "")
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if title.endswith(want) and len(coords) == 2:
            out.append((float(coords[0]), float(coords[1]), title))
    return out


def read_gsi_ports(path: Path) -> dict[tuple[str | None, str], list[tuple[float, float, str | None]]]:
    """国土地理院の地名検索の結果（ファイル名「<都道府県コード>_<港名>.json」に「港名＋港」で引いた結果）
    → (都道府県コード, 正規化した名前) → 位置の候補。名前が「港名＋港」で終わる地名だけを使う。
    港湾統計と地名で港の名前が違うときは「<都道府県コード>_<港名>@<地名>.json」に地名で引いた結果を置き、
    名前がその地名で終わるものを使う（例: 青ヶ島 → 三宝港）。
    同じ名前の地名がほかの都道府県にもあるので、取り込みで位置の都道府県を確かめる。"""
    stem, _, alias = path.stem.partition("@")
    pref, _, name = stem.partition("_")
    cands = [(lon, lat, None) for lon, lat, _ in _gsi_places(path, alias or f"{name}港")]
    return {(pref, norm_port(name)): cands} if cands else {}


def read_gsi_airports(path: Path) -> dict[str, list[tuple[float, float, str]]]:
    """国土地理院の地名検索の結果（ファイル名「<調書の空港名>@<地名>.json」）→ 正規化した空港名 → 位置の候補。
    国土数値情報 C28 にないヘリポートなどに使う。名前がその地名で終わるものだけを使う。"""
    name, _, query = path.stem.partition("@")
    cands = _gsi_places(path, query or name)
    return {norm_airport(name): cands} if cands else {}


def read_port_overrides(path: Path = PORT_LOCATIONS) -> dict[tuple[str, str], tuple[float, float]]:
    """手で付けた港の位置（「都道府県名/港名」= [経度, 緯度]）。Wikidata にない・違う港に使う。"""
    if not path.exists():
        return {}
    out = {}
    for key, (lon, lat) in tomllib.loads(path.read_text(encoding="utf-8")).get("ports", {}).items():
        pref, name = key.split("/", 1)
        out[(PREF_NAMES[pref], port_name(name))] = (float(lon), float(lat))
    return out


# --- 取り込み ---------------------------------------------------------------------

def _period(year: int) -> tuple[str, str, str]:
    return (f"{year}-01-01", f"{year}-12-31", "calendar_year")


def _store(conn, entity_id: str, entity_type: str, name: str, muni: str, lon: float, lat: float,
           loc_source: str, attrs: dict, series: dict[int, tuple[dict, str]], indicator_id: str, d: dict) -> int:
    upsert_entity(conn, entity_id, entity_type, name, parent_id=muni)
    conn.execute(
        """INSERT INTO locations (location_id, entity_id, role, lon, lat, source_id)
           VALUES (?, ?, 'main', ?, ?, ?)
           ON CONFLICT(location_id) DO UPDATE SET lon = excluded.lon, lat = excluded.lat,
             source_id = excluded.source_id""",
        (f"{entity_id}:main", entity_id, round(lon, 5), round(lat, 5), loc_source))
    conn.execute(
        """INSERT INTO entity_attributes (entity_id, attributes) VALUES (?, ?)
           ON CONFLICT(entity_id) DO UPDATE SET attributes = excluded.attributes""",
        (entity_id, json.dumps(attrs, ensure_ascii=False)))
    n = 0
    for year, (vals, src) in series.items():
        start, end, kind = _period(year)
        for dim in DIMENSIONS:
            v = vals.get(dim)
            if v is None:
                continue
            insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                               definition_version=d["definition_version"], period_start=start, period_end=end,
                               period_kind=kind, dimension_key=dim, value=v, status="observed", source_id=src)
            n += 1
    return n


def _def(catalog: dict, kind: str) -> tuple[str, dict] | None:
    return next(((i, d) for i, d in catalog.items() if d.get("source_kind") == kind), None)


def ingest_airports(conn: sqlite3.Connection, tables: list[tuple[int, Path, str]],
                    locations: tuple[list[Path], str] | None, catalog: dict, boundary_version: str,
                    prefs: list[str], extra: list[tuple[Path, str]] | None = None) -> dict:
    """extra: C28 にない空港（ヘリポートなど）の位置。国土地理院の地名検索の結果。"""
    found = _def(catalog, "mlit_airports")
    result = {"airports": 0, "no_location": 0, "outside": 0, "no_passengers": 0, "observations": 0}
    if not found or not locations:
        return result
    indicator_id, d = found
    c28, notes = read_airport_locations(locations[0])
    for line in notes:
        progress(f"空港の位置: {line}")
    locs = {k: (*v, locations[1]) for k, v in c28.items()}
    for path, src in extra or []:
        for key, cands in read_gsi_airports(path).items():
            if key not in locs:
                locs[key] = (*cands[0], src)
                progress(f"空港の位置（国土地理院の地名）: {key} → {cands[0][2]} {cands[0][0]:.3f},{cands[0][1]:.3f}")
    by_name: dict[str, dict[int, tuple[dict, str]]] = {}
    shown: dict[str, str] = {}
    latest = max(t[0] for t in tables)
    for year, path, src in sorted(tables, key=lambda t: t[0]):
        table, notes, fiscal = read_airports(path)
        for line in notes if year == latest or not table else notes[-1:]:
            progress(f"空港の表 {year}: {line}")
        if fiscal:   # 年度（4月〜翌3月）の表は暦年の値と並べられないので使わない
            progress(f"空港の表 {year}: 年度の表のため使いません")
            continue
        for name, vals in table.items():
            key = norm_airport(name)
            by_name.setdefault(key, {})[year] = (vals, src)
            shown[key] = name                    # 新しい年の表の名前
    munis = _municipality_index(conn, boundary_version, prefs)
    missing = []
    for key, series in by_name.items():
        if not any(v.get("all") for v, _ in series.values()):
            result["no_passengers"] += 1      # どの年も乗り降りのない空港・ヘリポート
            continue
        loc = locs.get(key)
        if loc is None:
            last = series[max(series)][0].get("all")
            missing.append(f"{shown[key]}（{max(series)}年 {last:,.0f}人）" if last is not None else shown[key])
            result["no_location"] += 1
            continue
        muni = _municipality_of(Point(loc[0], loc[1]), *munis)
        if muni is None:
            result["outside"] += 1
            continue
        eid = f"airport-{hashlib.sha1(key.encode()).hexdigest()[:8]}"
        result["observations"] += _store(conn, eid, "airport", shown[key], muni, loc[0], loc[1], loc[3],
                                         {"official_name": loc[2]}, series, indicator_id, d)
        result["airports"] += 1
    if missing:
        progress("位置の分からない空港: " + "、".join(missing))
    return result


def _port_municipality(point: Point, pref: str, ids, geoms, tree) -> str | None:
    """港の位置の市区町村。港の位置は海の上のこともあるので、同じ都道府県の約5km以内の市区町村まで探す。"""
    hits = [i for i in tree.query(point, predicate="intersects") if ids[i].startswith(f"muni-{pref}")]
    if hits:
        return ids[hits[0]]
    near = [i for i in tree.query(point.buffer(PORT_NEAR_DEGREES), predicate="intersects")
            if ids[i].startswith(f"muni-{pref}")]
    return ids[min(near, key=lambda i: geoms[i].distance(point))] if near else None


def ingest_ports(conn: sqlite3.Connection, tables: list[tuple[int, list[Path], str]],
                 locations: list[tuple[Path, str, str]] | None, catalog: dict, boundary_version: str,
                 prefs: list[str]) -> dict:
    found = _def(catalog, "mlit_ports")
    result = {"ports": 0, "no_location": 0, "wrong_location": 0, "outside": 0, "no_passengers": 0, "observations": 0}
    if not found:
        return result
    indicator_id, d = found
    # 位置の候補: (都道府県コード or None, 正規化した名前) → [(経度, 緯度, QID, 出典)]。Wikidata を先に、国土地理院の地名を後に
    cands: dict = {}
    counts = {"wikidata_ports": 0, "gsi_ports": 0}
    for path, src, kind in sorted(locations or [], key=lambda t: t[2] != "wikidata_ports"):
        if kind == "gsi_ports":
            found_locs = read_gsi_ports(path)
        else:
            found_locs = {k: [v] for k, v in read_wikidata_ports(path).items()}
        for key, vs in found_locs.items():
            cands.setdefault(key, []).extend((*v, src) for v in vs)
            counts[kind] += 1
    manual = read_port_overrides()
    progress(f"港の位置: Wikidata {counts['wikidata_ports']} 件、国土地理院の地名 {counts['gsi_ports']} 件、"
             f"手で付けた位置 {len(manual)} 件")
    manual_src = register_source(conn, "port_locations", MANUAL_SOURCE, [PORT_LOCATIONS]) if manual else ""
    by_port: dict[tuple[str, str], dict[int, tuple[dict, str]]] = {}
    latest = max((t[0] for t in tables), default=0)
    for year, paths, src in sorted(tables, key=lambda t: t[0]):
        for path in paths:
            table, notes = read_ports(path)
            for line in notes if year == latest or not table else notes[-1:]:
                progress(f"港の表: {line}")
            for key, vals in table.items():
                by_port.setdefault(key, {})[year] = (vals, src)
    munis = _municipality_index(conn, boundary_version, prefs)
    missing, wrong = [], []
    for (pref, name), series in sorted(by_port.items()):
        if not any(v.get("all") for v, _ in series.values()):
            result["no_passengers"] += 1      # 旅客の乗り降りのない港（どの年も0）
            continue
        norm = norm_port(name)
        if (pref, name) in manual:
            options = [(*manual[(pref, name)], None, manual_src)]
        else:
            options = cands.get((pref, norm), []) + cands.get((None, norm), [])
        if not options:
            missing.append(f"{PREFECTURES[pref]}/{name}")
            result["no_location"] += 1
            continue
        if pref not in prefs:
            result["outside"] += 1
            continue
        # 候補のうち、位置が港湾統計の都道府県の中（か近く）にある最初のもの
        hit = next(((lon, lat, qid, loc_src, muni) for lon, lat, qid, loc_src in options
                    if (muni := _port_municipality(Point(lon, lat), pref, *munis)) is not None), None)
        if hit is None:   # 位置が都道府県から離れている（同じ名前の別の港など）
            lon, lat, qid, _ = options[0]
            wrong.append(f"{PREFECTURES[pref]}/{name}（{qid or '位置'} {lon:.3f},{lat:.3f}）")
            result["wrong_location"] += 1
            continue
        lon, lat, qid, loc_src, muni = hit
        eid = f"port-{pref}-{hashlib.sha1(name.encode()).hexdigest()[:8]}"
        result["observations"] += _store(conn, eid, "port", name, muni, lon, lat, loc_src,
                                         {"wikidata": qid} if qid else {}, series, indicator_id, d)
        result["ports"] += 1
    if missing:
        progress(f"位置の分からない港 {len(missing)}: " + "、".join(missing))
    if wrong:
        progress(f"位置が都道府県と合わない港 {len(wrong)}: " + "、".join(wrong))
    return result
