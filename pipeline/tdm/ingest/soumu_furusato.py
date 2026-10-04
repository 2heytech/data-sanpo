"""総務省「ふるさと納税に関する現況調査結果」の各自治体の受入額・受入件数（xlsx）を取り込む。

形式（令和8年度調査 main_content/001084990.xlsx を 2026-10-03 に GitHub Actions から取得して確認）:
  シート「各団体一覧」。2行目に「団体名」と年度（「平成20年度」〜「令和７年度」）が2列おきに並び、
  4行目に「金額」「件数」。5行目から1行に1団体で、1列目が都道府県名、2列目が市区町村名
  （都道府県自身の行は2列目が空）。金額は千円、件数は件。最後に「全国合計」の行がある。
  団体コードはないので、都道府県名と市区町村名で地域に結びつける（政令指定都市は市全体の行）。

都道府県の行は都道府県（庁）自身が受け入れた額で、県内の市区町村の合計ではない。地図の都道府県の値は
「都道府県内の合計」とし、都道府県（庁）自身の行と県内の全市区町村の行（政令指定都市は市全体の行）を足して出す。
政令指定都市は市全体の行しかなく、区に割り振ると元データより細かくなるので、区には値を入れない。
空欄は値なし（0 にしない）。0 と書かれた年度は受入がなかったので 0。合計に空欄が1つでも含まれれば値なし。
指標（definition の furusato_value で選ぶ）: amount（受入額）、count（受入件数）。
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

from ..db import insert_observation
from ..regions import PREFECTURES, prefecture_entity_id
from ..xlsx import read_sheet

SHEET = "各団体一覧"
ERAS = {"平成": 1988, "令和": 2018}


def _text(cell) -> str:
    return unicodedata.normalize("NFKC", str(cell)).replace(" ", "").strip() if cell is not None else ""


def fiscal_year(label: str) -> int | None:
    """「令和７年度」→ 2025、「令和元年度」→ 2019。"""
    m = re.fullmatch(r"(平成|令和)(元|\d+)年度", _text(label))
    if not m:
        return None
    return ERAS[m.group(1)] + (1 if m.group(2) == "元" else int(m.group(2)))


def read_table(path: Path) -> dict[tuple[str, str], dict[int, tuple[float | None, float | None]]]:
    """(都道府県名, 市区町村名 または "") → 年度 → (受入額（千円）, 受入件数)。"""
    rows = read_sheet(path, SHEET)
    at = next(i for i, r in enumerate(rows) if r and _text(r[0]) == "団体名")
    years = {j: y for j, c in enumerate(rows[at]) if (y := fiscal_year(c))}
    out: dict[tuple[str, str], dict[int, tuple[float | None, float | None]]] = {}
    for r in rows[at + 1:]:
        pref = _text(r[0]) if r else ""
        if pref not in PREFECTURES.values():
            continue   # 見出し・空行・全国合計
        muni = _text(r[1]) if len(r) > 1 else ""

        def num(j: int) -> float | None:
            v = r[j] if j < len(r) else None
            return float(v) if isinstance(v, (int, float)) else None
        out[(pref, muni)] = {y: (num(j), num(j + 1)) for j, y in years.items()}
    return out


def _entities(conn: sqlite3.Connection) -> dict[tuple[str, str], str]:
    """(都道府県名, 市区町村名) → 地域ID。都道府県は市区町村名を "" にする。"""
    out = {}
    for r in conn.execute("SELECT entity_id, entity_type, name FROM entities "
                          "WHERE entity_type IN ('prefecture', 'municipality')"):
        pref = PREFECTURES.get(r["entity_id"].split("-", 1)[1][:2])
        if pref:
            out[(pref, "" if r["entity_type"] == "prefecture" else unicodedata.normalize("NFKC", r["name"]))] = r["entity_id"]
    return out


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict) -> dict:
    table = read_table(path)
    entities = _entities(conn)
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "soumu_furusato"}
    result = {"rows": len(table), "matched": 0, "prefectures": 0, "years": [], "unmatched_entities": []}
    code_of = {name: code for code, name in PREFECTURES.items()}
    totals: dict[str, dict[int, list]] = {}   # 都道府県コード → 年度 → [受入額, 件数]（None は欠け）
    for (pref, muni), by_year in table.items():
        t = totals.setdefault(code_of[pref], {})
        for y, pair in by_year.items():
            acc = t.setdefault(y, [0.0, 0.0])
            for i, v in enumerate(pair):
                acc[i] = None if (acc[i] is None or v is None) else acc[i] + v
        if not muni:
            continue   # 都道府県（庁）自身の行は、下の都道府県内の合計にだけ使う
        entity_id = entities.get((pref, muni))
        if entity_id is None:
            continue   # この公開版で扱っていない地域・政令指定都市（地図の単位は区）
        result["matched"] += 1
        _insert(conn, entity_id, by_year, targets, source_id)
    for code, by_year in totals.items():
        entity_id = prefecture_entity_id(code)
        if not conn.execute("SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)).fetchone():
            continue
        _insert(conn, entity_id, {y: tuple(v) for y, v in by_year.items()}, targets, source_id,
                note="都道府県（庁）と県内の市区町村の受入の合計")
        result["prefectures"] += 1
    result["years"] = sorted({y for by_year in table.values() for y in by_year})
    result["years"] = [result["years"][0], result["years"][-1]] if result["years"] else []
    seen = set(table)
    result["unmatched_entities"] = sorted(eid for k, eid in entities.items() if k not in seen and k[1])[:30]
    return result


def _insert(conn: sqlite3.Connection, entity_id: str, by_year: dict, targets: dict, source_id: str,
            note: str | None = None) -> None:
    for y, (amount, count) in by_year.items():
        for indicator_id, d in targets.items():
            v = amount if d["furusato_value"] == "amount" else count
            insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                               definition_version=d["definition_version"],
                               period_start=f"{y}-04-01", period_end=f"{y + 1}-03-31",
                               period_kind="fiscal_year", source_id=source_id,
                               value=None if v is None else v * d.get("scale", 1),
                               status="observed" if v is not None else "missing",
                               method_note=note)
