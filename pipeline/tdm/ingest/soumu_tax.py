"""総務省「市町村税課税状況等の調」〔市町村別内訳〕第11表（所得割納税義務者数・課税対象所得・所得割額）を取り込む。

形式（令和7年度 J51-25-b.xlsx を 2026-10-03 に GitHub Actions から取得して確認）: 1シートに全国の市区町村。
列名の行に「年度」「団体コード」「都道府県名」「団体名」「表側」「所得割の納税義務者数」…「課税対象所得」
「課税標準額」「所得割額（税額控除・減免後）」が並び、その下に記号の行・単位の行（人・千円）がある。
1つの市区町村に「表側」が「市町村民税」（特別区民税を含む）と「道府県民税」（都民税）の2行ある。
団体コードは6桁（末尾は検査数字）で、先頭5桁が地域コード。

指標（definition の tax_value で選ぶ）:
  income_levy: 所得割額（市町村民税＋道府県民税）÷ 所得割の納税義務者数（市町村民税の行）
  taxable_income: 課税対象所得（市町村民税の行）÷ 所得割の納税義務者数（同）
金額は千円単位なので円に直す（scale = 1000）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..db import insert_observation
from ..regions import TOKYO, municipality_entity_id, prefecture_entity_id
from ..xlsx import read_sheet

CITY, PREF = "市町村民税", "道府県民税"


def read_rows(path: Path, prefs: list[str] | None = None) -> dict[str, dict[str, dict[str, float]]]:
    """地域コード5桁 → 表側 → 列名 → 値（取り込む都道府県の行だけ。既定は東京都）。"""
    prefs = set(prefs or [TOKYO])
    rows = read_sheet(path)
    at = next(i for i, r in enumerate(rows) if "団体コード" in r and "表側" in r)
    header = [str(c).strip() if c is not None else "" for c in rows[at]]
    col = {h: i for i, h in enumerate(header) if h}
    out: dict[str, dict[str, dict[str, float]]] = {}
    for r in rows[at + 1:]:
        if len(r) <= col["表側"]:
            continue
        code = str(r[col["団体コード"]]).strip()[:5]
        if code[:2] not in prefs:
            continue
        out.setdefault(code, {})[str(r[col["表側"]]).strip()] = {
            h: r[i] for h, i in col.items() if i < len(r) and isinstance(r[i], float)}
    return out


def _column(values: dict[str, float], prefix: str) -> float | None:
    return next((v for h, v in values.items() if h.startswith(prefix)), None)


def _is_designated_city(conn: sqlite3.Connection, code: str) -> bool:
    """政令指定都市（例: 14100 横浜市）。地図の単位は区（14101〜）なので、市の行は地域にない。"""
    return conn.execute("SELECT 1 FROM entities WHERE entity_id LIKE ? AND entity_id != ?",
                        (f"muni-{code[:4]}_", f"muni-{code}")).fetchone() is not None


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict,
           period: tuple[str, str, str], prefs: list[str] | None = None) -> dict:
    data = read_rows(path, prefs)
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "soumu_tax"}
    result = {"municipalities": 0, "prefectures": 0, "designated_cities": [], "unmatched": []}
    # 都道府県の値は、政令指定都市を含む市町村の行を合計して出す（区の値がないため区市町村からは合計できない）
    by_pref: dict[str, list[dict]] = {}
    for code, sides in data.items():
        entity_id = municipality_entity_id(code)
        if not conn.execute("SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)).fetchone():
            # 政令指定都市は市全体の値しかない。区に割り振ると元データより細かくなるので、区には値を入れない
            designated = _is_designated_city(conn, code)
            result["designated_cities" if designated else "unmatched"].append(code)
            # 区の行も表にあるとき（東京都の特別区の計など）は二重に数えない
            if designated and not any(c[:4] == code[:4] and c != code for c in data):
                by_pref.setdefault(code[:2], []).append(sides)
            continue
        by_pref.setdefault(code[:2], []).append(sides)
        _insert(conn, entity_id, sides, targets, source_id, period)
        result["municipalities"] += 1
    for pref, rows in by_pref.items():
        total = {side: {} for side in (CITY, PREF)}
        for sides in rows:
            for side in (CITY, PREF):
                for h, v in sides.get(side, {}).items():
                    total[side][h] = total[side].get(h, 0) + v
        _insert(conn, prefecture_entity_id(pref), total, targets, source_id, period)
        result["prefectures"] += 1
    return result


def _insert(conn: sqlite3.Connection, entity_id: str, sides: dict, targets: dict, source_id: str,
            period: tuple[str, str, str]) -> None:
    city, pref = sides.get(CITY, {}), sides.get(PREF, {})
    taxpayers = _column(city, "所得割の納税義務者数")
    for indicator_id, d in targets.items():
        if d["tax_value"] == "income_levy":
            parts = [_column(city, "所得割額"), _column(pref, "所得割額")]
            numerator = None if None in parts else sum(parts)
        else:
            numerator = _column(city, "課税対象所得")
        obs = dict(entity_id=entity_id, indicator_id=indicator_id,
                   definition_version=d["definition_version"], period_start=period[0],
                   period_end=period[1], period_kind=period[2], source_id=source_id,
                   denominator_source_id=source_id, numerator=numerator, denominator=taxpayers)
        if numerator is None or not taxpayers:
            insert_observation(conn, value=None, status="missing", **obs)
        else:
            insert_observation(conn, value=numerator / taxpayers * d.get("scale", 1),
                               status="derived", **obs)
