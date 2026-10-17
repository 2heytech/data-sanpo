"""こども家庭庁「保育所等関連状況取りまとめ」の（参考）定員・申込者の状況から、市区町村の保育の指標を取り込む
（docs/design-changes.md #138）。

形式（令和5〜8年4月1日の Excel を 2026-10-17 に取得して確認）: シート「定員の状況」と「申込者の状況」
（令和5年は申込者の状況だけで、シート名は「（参考）申込者の状況（令和5年4月1日）」）。3行目あたりに題名
「（参考）定員の状況（令和８年４月１日）」、見出しの行に「都道府県」「市区町村」と、施設の種類の列が並ぶ。
最初のまとまりが合計（その後ろは年齢別）。1行が1市区町村（全国1,741。政令指定都市は市全体の行だけで区の行はない）、
最後に「計」の行。
  定員の状況: 保育所, 幼保連携型認定こども園, 幼稚園型認定こども園等, 地域型保育事業, 特例保育等, 企業主導型保育事業,
    地方単独事業
  申込者の状況: 申込者数, 保育所を利用している者, 幼保連携型認定こども園を利用している者, …, 待機児童
国の「保育所等」の利用定員・利用児童数は、保育所・幼保連携型認定こども園・幼稚園型認定こども園等・地域型保育事業の合計
（取りまとめの資料の注記）なので、その4つの列を足す。特例保育等・企業主導型保育事業・地方単独事業は含めない。

指標（definition の cfa_value で選ぶ）:
  capacity: 保育所等の利用定員（人）
  users: 保育所等を利用している子どもの数（人）
  waiting: 待機児童数（人）。cfa_exclude_prefectures の都道府県（東京都は都の発表で2022年からある）は取り込まない
  occupancy: 利用している子どもの数 ÷ 利用定員 × 100（率は分子・分母から計算）
政令指定都市は市全体の値しかなく、区に割り振ると元データより細かくなるので、区には値を入れず注記を付ける。
都道府県の値は、県内の市区町村（政令指定都市は市全体）の合計から作る。
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

from ..db import insert_observation
from ..regions import PREFECTURES, prefecture_entity_id
from ..xlsx import read_sheet, sheet_names
from .isj_geocode import normalize_municipality

KINDS = ["保育所", "幼保連携型認定こども園", "幼稚園型認定こども園等", "地域型保育事業"]
WARD_NOTE = "政令指定都市は市全体の値だけが公表されているため、区の値はありません"
PREF_CODE = {name: code for code, name in PREFECTURES.items()}
ZEN = str.maketrans("０１２３４５６７８９", "0123456789")


def _label(cell) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(cell))) if cell is not None else ""


def _year(rows: list[list]) -> int | None:
    for r in rows[:6]:
        for c in r:
            if m := re.search(r"令和(\d+|元)年4月1日", _label(c).translate(ZEN)):
                return 2018 + (1 if m.group(1) == "元" else int(m.group(1)))
    return None


def read_tables(path: Path) -> tuple[int, dict[tuple[str, str], dict[str, float]]]:
    """(年, (都道府県名, 市区町村名) → {"capacity", "users", "waiting"})。表にない値は入れない。"""
    out: dict[tuple[str, str], dict[str, float]] = {}
    years = set()
    for name in sheet_names(path):
        rows = read_sheet(path, name)
        at = next((i for i, r in enumerate(rows) if len(r) > 3 and _label(r[2]) == "都道府県"), None)
        if at is None:
            continue
        years.add(_year(rows))
        head = [_label(c) for c in rows[at]]
        if "申込者数" in head:
            first = head.index("申込者数")
            cols = {"users": [head.index(f"{k}を利用している者", first) for k in KINDS],
                    "waiting": [head.index("待機児童", first)]}
        else:
            cols = {"capacity": [head.index(k) for k in KINDS]}
        for r in rows[at + 1:]:
            if len(r) < 4 or not isinstance(r[1], float):
                continue   # 合計（「計」）・空行
            key = (_label(r[2]), _label(r[3]))
            for k, idx in cols.items():
                vals = [r[i] if i < len(r) else None for i in idx]
                if all(isinstance(v, float) for v in vals):
                    out.setdefault(key, {})[k] = sum(vals)
    if len(years) != 1 or None in years:
        raise ValueError(f"{path.name}: 時点（令和◯年4月1日）が読めません: {years}")
    return years.pop(), out


def _municipalities(conn: sqlite3.Connection) -> tuple[dict, dict]:
    """((都道府県コード, 市区町村名) → 地域ID, (都道府県コード, 政令指定都市名) → 区の地域ID)。"""
    names, wards = {}, {}
    for r in conn.execute("SELECT entity_id, name, region FROM entities WHERE entity_type = 'municipality'"):
        pref = r["entity_id"][5:7]
        names[(pref, normalize_municipality(r["name"]))] = r["entity_id"]
        if r["region"] and pref != "13":
            wards.setdefault((pref, normalize_municipality(r["region"])), []).append(r["entity_id"])
    return names, wards


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict, year: int,
           prefs: list[str]) -> dict:
    got, data = read_tables(path)
    if got != year:
        raise ValueError(f"{path.name}: {got}年の表です（設定は {year}年）")
    targets = {k: d for k, d in catalog.items() if d.get("cfa_value")}
    names, wards = _municipalities(conn)
    period = dict(period_start=f"{year}-04-01", period_end=f"{year}-04-01", period_kind="point",
                  source_id=source_id)
    result = {"municipalities": 0, "designated_cities": 0, "unmatched": []}
    totals: dict[str, dict[str, float | None]] = {}
    for (pref_name, muni), values in sorted(data.items()):
        pref = PREF_CODE.get(pref_name)
        if pref is None or pref not in prefs:
            continue
        t = totals.setdefault(pref, {})
        for k in ("capacity", "users", "waiting"):
            t[k] = None if k not in values or (k in t and t[k] is None) else t.get(k, 0.0) + values[k]
        key = (pref, normalize_municipality(muni))
        if key in names:
            _insert(conn, names[key], values, targets, period, pref)
            result["municipalities"] += 1
        elif key in wards:
            for ward in wards[key]:
                for indicator_id, d in targets.items():
                    if _applies(d, pref, values):
                        insert_observation(conn, entity_id=ward, indicator_id=indicator_id,
                                           definition_version=d["definition_version"], value=None,
                                           status="not_applicable", method_note=WARD_NOTE, **period)
            result["designated_cities"] += 1
        else:
            result["unmatched"].append(f"{pref_name}{muni}")
    for pref, values in sorted(totals.items()):
        _insert(conn, prefecture_entity_id(pref), {k: v for k, v in values.items() if v is not None},
                targets, period, pref, note="県内の市区町村（政令指定都市は市全体）の合計")
    return result


def _applies(d: dict, pref: str, values: dict) -> bool:
    if pref in d.get("cfa_exclude_prefectures", []):
        return False
    need = ("users", "capacity") if d["cfa_value"] == "occupancy" else (d["cfa_value"],)
    return all(k in values for k in need)


def _insert(conn: sqlite3.Connection, entity_id: str, values: dict, targets: dict, period: dict, pref: str,
            note: str | None = None) -> None:
    for indicator_id, d in targets.items():
        if not _applies(d, pref, values):
            continue   # その年の表にない値（令和5年の定員）・都の発表を使う都道府県
        obs = dict(entity_id=entity_id, indicator_id=indicator_id, definition_version=d["definition_version"],
                   method_note=note, **period)
        if d["cfa_value"] == "occupancy":
            num, den = values["users"], values["capacity"]
            if den:
                insert_observation(conn, value=num / den * d.get("scale", 1), status="derived", numerator=num,
                                   denominator=den, denominator_source_id=period["source_id"], **obs)
            else:
                insert_observation(conn, value=None, status="not_applicable", numerator=num, denominator=den,
                                   **{**obs, "method_note": "利用定員が0のため算出しない"})
        else:
            insert_observation(conn, value=values[d["cfa_value"]], status="observed", **obs)
