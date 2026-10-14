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
from ..regions import PREFECTURES
from ..xlsx import read_sheet, sheet_names
from .mlit_stations import _municipality_index, _municipality_of

DIMENSIONS = ("all", "domestic", "international")
ZERO = {"-", "－", "―", "‐", "—", "–"}
MARKS = "☆◎○●◇◆△▲※*＊"
PORT_LOCATIONS = Path(__file__).resolve().parents[2] / "config" / "port_locations.toml"


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

def norm_airport(name: str) -> str:
    """空港名の比べ方。「東京国際空港」と「東京国際」、「新千歳空港」と「新千歳」を同じにする。"""
    s = re.sub(r"[(（].*?[)）]", "", _t(name))
    for w in ("国際空港", "空港", "飛行場", "国際"):
        s = s.replace(w, "")
    return s


def read_airports(path: Path) -> tuple[dict[str, dict[str, float | None]], list[str]]:
    """空港名 → {all, domestic, international}（年の乗降客数）と、調べた表の様子（ログ用）。"""
    notes: list[str] = []
    out: dict[str, dict[str, float | None]] = {}
    for sheet in sheet_names(path):
        rows = read_sheet(path, sheet)
        h = next((i for i, r in enumerate(rows[:30]) if any("乗降客" in _t(c) for c in r)), None)
        if h is None:
            continue
        c0 = next(j for j, c in enumerate(rows[h]) if "乗降客" in _t(c))
        end = next((j for j in range(c0 + 1, len(rows[h])) if _t(rows[h][j])), len(rows[h]))
        sub = rows[h:h + 4]
        label = {j: "".join(_t(r[j]) for r in sub if j < len(r)) for j in range(c0, end)}
        cols: dict[str, int] = {}
        for key, words in (("international", ("国際",)), ("domestic", ("国内",))):
            starts = [j for j in range(c0, end) if any(w in label[j] for w in words)]
            if not starts:
                continue
            s = starts[0]
            nxt = min([j for j in range(s + 1, end) if ("国際" in label[j] or "国内" in label[j]) and j not in starts]
                      + [end])
            span = [j for j in range(s, nxt)]
            tot = [j for j in span if label[j].endswith("計") and j != s] or [s]
            cols[key] = tot[-1] if len(span) > 1 and tot != [s] else s
        tot_cols = [j for j in range(c0, end) if label[j].endswith("計") and j not in cols.values()
                    and not any(w in label[j] for w in ("国際", "国内"))]
        if tot_cols:
            cols["all"] = tot_cols[-1]
        # 空港名の列: 見出しに「空港」とある乗降客数より左の列、なければ左端の文字の多い列
        name_col = next((j for j in range(c0) for r in rows[h:h + 4] if j < len(r) and "空港" in _t(r[j])), None)
        if name_col is None:
            counts = [sum(1 for r in rows[h + 1:] if j < len(r) and isinstance(r[j], str) and _t(r[j]))
                      for j in range(c0)]
            name_col = max(range(c0), key=lambda j: counts[j]) if c0 else 0
        notes.append(f"{path.name} シート「{sheet}」見出し{h}行 乗降客数の列{c0}〜{end - 1} 名前の列{name_col} 列{cols}")
        notes += _preview(rows, max(0, h - 1), 6)
        n0 = len(out)
        for r in rows[h + 1:]:
            name = _t(r[name_col]) if name_col < len(r) else ""
            if not name or "計" in name or re.fullmatch(r"[\d.]+", name):
                continue
            vals = {k: (_num(r[j]) if j < len(r) else None) for k, j in cols.items()}
            if not any(v is not None for v in vals.values()):
                continue
            if "all" not in vals and vals.get("domestic") is not None and vals.get("international") is not None:
                vals["all"] = vals["domestic"] + vals["international"]
            out.setdefault(name, {k: vals.get(k) for k in DIMENSIONS})
        notes.append(f"  空港 {len(out) - n0} か所: " + "、".join(list(out)[n0:n0 + 12]) + " …")
    return out, notes


def read_airport_locations(files: list[Path]) -> tuple[dict[str, tuple[float, float, str]], list[str]]:
    """国土数値情報 C28 の空港 → 正規化した名前 → (経度, 緯度, 名前)。標点（点）があれば面より優先する。"""
    utf8 = [f for f in files if "utf" in str(f).lower()]
    out: dict[str, tuple[float, float, str, bool]] = {}
    notes = []
    for f in utf8 or files:
        try:
            feats = json.loads(f.read_text(encoding="utf-8")).get("features", [])
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        types = sorted({(ft.get("geometry") or {}).get("type", "") for ft in feats})
        notes.append(f"{f.name}: {len(feats)} 地物 {types} 例 {json.dumps(feats[0]['properties'], ensure_ascii=False)[:300] if feats else ''}")
        for ft in feats:
            names = [v for v in (ft.get("properties") or {}).values()
                     if isinstance(v, str) and re.search(r"(空港|飛行場)$", _t(v))]
            if not names or not ft.get("geometry"):
                continue
            g = shape(ft["geometry"])
            is_point = g.geom_type == "Point"
            p = g if is_point else g.representative_point()
            key = norm_airport(names[0])
            if key not in out or (is_point and not out[key][3]):
                out[key] = (p.x, p.y, _t(names[0]), is_point)
    return {k: v[:3] for k, v in out.items()}, notes


# --- 港 -------------------------------------------------------------------------

PREF_NAMES = {name: code for code, name in PREFECTURES.items()}
PORT_LABELS = {"外": "international", "内": "domestic", "計": "all"}


def _pref_in(text: str) -> str | None:
    """「北海道」「東京都合計」など、都道府県名で始まる文字の都道府県コード。"""
    return next((code for name, code in PREF_NAMES.items() if text.startswith(name)), None)


def port_name(text: str) -> str:
    return _t(text).strip(MARKS)


def norm_port(name: str) -> str:
    s = re.sub(r"[(（].*?[)）]", "", port_name(name))
    return s.removesuffix("港")


def read_ports(path: Path) -> tuple[dict[tuple[str, str], dict[str, float | None]], list[str]]:
    """(都道府県コード, 港名) → {all, domestic, international}。表は印刷向けで、1行に2つの都道府県の欄が
    並ぶことがあるので、「外・内・計」の文字の右に数が3つ（計・乗込・上陸）並ぶところを欄ごとに読む。"""
    out: dict[tuple[str, str], dict[str, float | None]] = {}
    notes = []
    for sheet in sheet_names(path):
        rows = read_sheet(path, sheet)
        notes.append(f"{path.name} シート「{sheet}」 {len(rows)} 行")
        notes += _preview(rows, 0, 14, 24)
        names: dict[int, str] = {}     # 欄（「外・内・計」の列）ごとの直前の港名
        prefs: dict[int, str] = {}     # 欄ごとの直前の都道府県
        for r in rows:
            for j, c in enumerate(r):
                lab = _t(c)
                if lab not in PORT_LABELS or j + 1 >= len(r) or not _is_num(r[j + 1]):
                    continue
                # 名前は同じ行の左の数個の列にある（ない行は同じ欄の直前の名前）
                left = [_t(r[k]) for k in range(max(0, j - 4), j) if isinstance(r[k], str) and _t(r[k])
                        and not _is_num(r[k]) and _t(r[k]) not in PORT_LABELS]
                if left:
                    text = left[-1]
                    pref = _pref_in(text)
                    if pref and (text in PREFECTURES.values() or text.endswith("計")):
                        prefs[j] = pref
                        names[j] = ""          # 都道府県の合計の行
                    elif "計" in text and len(text) <= 3:
                        names[j] = ""          # 総計
                    else:
                        names[j] = port_name(text)
                name = names.get(j, "")
                pref = prefs.get(j)
                if not name or not pref:
                    continue
                out.setdefault((pref, name), {k: None for k in DIMENSIONS})[PORT_LABELS[lab]] = _num(r[j + 1])
    for v in out.values():
        if v["all"] is None and (v["domestic"] is not None or v["international"] is not None):
            v["all"] = (v["domestic"] or 0) + (v["international"] or 0)   # 片方だけの港（もう片方は表に行がない＝該当なし）
    notes.append(f"  港 {len(out)} か所: " + "、".join(f"{PREFECTURES[p]}{n}" for p, n in list(out)[:15]) + " …")
    return out, notes


def read_wikidata_ports(path: Path) -> dict[tuple[str, str], tuple[float, float, str]]:
    """Wikidata の港 → (都道府県コード, 正規化した名前) → (経度, 緯度, QID)。同じ名前が複数あれば番号の小さい項目。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], tuple[float, float, str]] = {}
    for b in data.get("results", {}).get("bindings", []):
        pref = PREF_NAMES.get(b.get("prefLabel", {}).get("value", ""))
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", b.get("coord", {}).get("value", ""))
        if not pref or not m:
            continue
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        key = (pref, norm_port(b["label"]["value"]))
        if key not in out or int(qid[1:]) < int(out[key][2][1:]):
            out[key] = (float(m.group(1)), float(m.group(2)), qid)
    return out


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
                    prefs: list[str]) -> dict:
    found = _def(catalog, "mlit_airports")
    result = {"airports": 0, "no_location": 0, "outside": 0, "observations": 0}
    if not found or not locations:
        return result
    indicator_id, d = found
    locs, notes = read_airport_locations(locations[0])
    for line in notes[:6]:
        progress(f"空港の位置: {line}")
    by_name: dict[str, dict[int, tuple[dict, str]]] = {}
    shown: dict[str, str] = {}
    for year, path, src in sorted(tables, key=lambda t: t[0]):
        table, notes = read_airports(path)
        for line in notes[:40] if year == max(t[0] for t in tables) or not table else notes[:2]:
            progress(f"空港の表: {line}")
        for name, vals in table.items():
            key = norm_airport(name)
            by_name.setdefault(key, {})[year] = (vals, src)
            shown[key] = name                    # 新しい年の表の名前
    munis = _municipality_index(conn, boundary_version, prefs)
    missing = []
    for key, series in by_name.items():
        loc = locs.get(key)
        if loc is None:
            missing.append(shown[key])
            result["no_location"] += 1
            continue
        muni = _municipality_of(Point(loc[0], loc[1]), *munis)
        if muni is None:
            result["outside"] += 1
            continue
        eid = f"airport-{hashlib.sha1(key.encode()).hexdigest()[:8]}"
        result["observations"] += _store(conn, eid, "airport", shown[key], muni, loc[0], loc[1], locations[1],
                                         {"official_name": loc[2]}, series, indicator_id, d)
        result["airports"] += 1
    if missing:
        progress("位置の分からない空港: " + "、".join(missing))
    return result


def ingest_ports(conn: sqlite3.Connection, tables: list[tuple[int, list[Path], str]],
                 wikidata: tuple[Path, str] | None, catalog: dict, boundary_version: str,
                 prefs: list[str]) -> dict:
    found = _def(catalog, "mlit_ports")
    result = {"ports": 0, "no_location": 0, "outside": 0, "no_passengers": 0, "observations": 0}
    if not found:
        return result
    indicator_id, d = found
    wd = read_wikidata_ports(wikidata[0]) if wikidata else {}
    manual = read_port_overrides()
    progress(f"港の位置: Wikidata {len(wd)} 件、手で付けた位置 {len(manual)} 件")
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
    missing = []
    for (pref, name), series in sorted(by_port.items()):
        if not any(v.get("all") for v, _ in series.values()):
            result["no_passengers"] += 1      # 旅客の乗り降りのない港（どの年も0）
            continue
        if (pref, name) in manual:
            lon, lat = manual[(pref, name)]
            loc_src, qid = (wikidata[1] if wikidata else ""), None   # TODO: 手で付けた位置の出典
        elif (pref, norm_port(name)) in wd:
            lon, lat, qid = wd[(pref, norm_port(name))]
            loc_src = wikidata[1]
        else:
            missing.append(f"{PREFECTURES[pref]}/{name}")
            result["no_location"] += 1
            continue
        muni = _municipality_of(Point(lon, lat), *munis)
        if muni is None:
            result["outside"] += 1
            continue
        eid = f"port-{pref}-{hashlib.sha1(name.encode()).hexdigest()[:8]}"
        result["observations"] += _store(conn, eid, "port", name, muni, lon, lat, loc_src,
                                         {"wikidata": qid} if qid else {}, series, indicator_id, d)
        result["ports"] += 1
    if missing:
        progress(f"位置の分からない港 {len(missing)}: " + "、".join(missing))
    return result
