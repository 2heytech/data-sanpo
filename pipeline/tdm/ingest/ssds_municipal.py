"""社会・人口統計体系「統計でみる市区町村のすがた」の基礎データ（総務省統計局、e-Stat の Excel）を取り込む（#206）。

形式（2026年版の B 自然環境・H 居住などの .xls を 2026-11-06 に GitHub Actions から取得して確認）:
  分野ごとに1ファイル・1シート。上の行に列の番号、6行目（0から数えて5）に項目名（「可住地面積」）、8行目に項目コード
  （「B1103」）、9行目に単位、10行目に調査年（「2024」）。11行目から1地域1行で、8列目（0から数えて7）が地域コード
  （都道府県は「01」、市区町村・政令指定都市の区は5桁。末尾に空白が付く）。全国の行はない。
  「...」「…」は値なし（調査の対象外。人口1万5千人未満の町村の住宅・土地統計調査の値など）、「-」は該当なし（0）。
指標（definition の ssds_item で項目コードを選ぶ）の値をそのまま入れる。時点は出典の period。
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from ..db import insert_observation

KIND = "ssds_municipal"
MISSING = {"...", "…", "***", "X", "x", ""}
ZERO = {"-", "－"}


def _rows(path: Path) -> list[list[str]]:
    if path.suffix.lower() == ".xlsx":   # 見本（fixture）
        from ..xlsx import read_sheet
        return [["" if v is None else str(v).strip() for v in r] for r in read_sheet(path)]
    import xlrd   # 旧形式の Excel（.xls）
    sheet = xlrd.open_workbook(str(path)).sheet_by_index(0)
    out = []
    for i in range(sheet.nrows):
        out.append(["" if v is None else str(v).strip() for v in sheet.row_values(i)])
    return out


def _value(cell: str) -> float | None:
    s = cell.strip()
    if s in ZERO:
        return 0.0
    if s in MISSING:
        return None
    return float(s.replace(",", ""))


def read_table(path: Path, items: list[str]) -> dict[str, dict[str, float | None]]:
    """地域コード（都道府県は2桁、市区町村は5桁）→ 項目コード → 値。"""
    rows = _rows(path)
    at = next((i for i, r in enumerate(rows[:30]) if any(c in items for c in r)), None)
    if at is None:
        raise KeyError(f"{path.name}: 項目 {items} が見つかりません")
    cols = {}
    for item in items:
        if item not in rows[at]:
            raise KeyError(f"{path.name}: 項目 {item} が見つかりません（{[c for c in rows[at] if c]}）")
        cols[item] = rows[at].index(item)
    out: dict[str, dict[str, float | None]] = {}
    for r in rows[at + 1:]:
        if len(r) < 8:
            continue
        code = r[7].strip()
        if not re.fullmatch(r"\d{2}|\d{5}", code):
            continue
        out[code] = {item: _value(r[j]) for item, j in cols.items()}
    return out


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict,
           period: tuple[str, str, str]) -> dict:
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == KIND}
    data = read_table(path, sorted({d["ssds_item"] for d in targets.values()}))
    result = {"municipalities": 0, "prefectures": 0}
    for code, values in data.items():
        entity_id = f"pref-{code}" if len(code) == 2 else f"muni-{code}"
        if not conn.execute("SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)).fetchone():
            continue   # 対象外の都道府県、政令指定都市の市全体の行（区ごとの行を使う）
        for indicator_id, d in targets.items():
            v = values[d["ssds_item"]]
            insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                               definition_version=d["definition_version"], value=v,
                               status="observed" if v is not None else "missing",
                               period_start=period[0], period_end=period[1], period_kind=period[2],
                               source_id=source_id)
        result["prefectures" if len(code) == 2 else "municipalities"] += 1
    return result
