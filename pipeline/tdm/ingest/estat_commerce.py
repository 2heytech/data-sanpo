"""令和3年経済センサス‐活動調査 産業別集計「卸売業，小売業」産業編（市区町村表）の第1表・第2表を取り込む。

形式（e-Stat の f3_001.xlsx・f3_002.xlsx を 2026-10-14 に GitHub Actions から取得して確認）:
  1シート。8行目に産業分類（「I_合計」「I1_卸売業計」「I2_小売業計」「56_各種商品小売業」…）、9行目に項目
  （事業所数・従業者数_合計・年間商品販売額・売場面積）、10行目に単位（事業所・人・百万円・m2）、12行目から
  1行に1地域。1列目が地域の種類（a=全国・都道府県、b=区部・市部・郡部などの計、1=政令指定都市と特別区部の全体、
  0=区、2=市、3=町村）、2列目が「13101_千代田区」のようなコードと名前。
  第1表（f3_001）は全国・都道府県・市区、第2表（f3_002）は全国・都道府県・政令指定都市・町村の行がある。
  値は数値か「x」（秘匿）「-」（該当なし）。年間商品販売額は2020年1年間、事業所数・従業者数は2021年6月1日現在。

区・市・町村（種類 0・2・3）を市区町村に、都道府県（種類 a）を都道府県に入れる。政令指定都市の全体・区部全体・
計の行は使わない。「x」は秘匿（0にしない）、「-」は該当なしで0。
指標は definition の commerce_column = [産業分類, 項目]（例: ["I2_小売業計", "年間商品販売額"]）で選ぶ。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..db import insert_observation
from ..regions import prefecture_entity_id
from ..xlsx import read_sheet

KIND = "estat_commerce"
LEVELS_MUNI = {"0", "2", "3"}


def _text(c) -> str:
    return "" if c is None else str(c).strip()


def read_table(path: Path) -> dict[tuple[str, str], dict[tuple[str, str], float | None]]:
    """(種類, コード5桁) → (産業分類, 項目) → 値（秘匿は None）。"""
    rows = read_sheet(path)
    at = next(i for i, r in enumerate(rows) if _text(r[0] if r else None) == "地域識別コード")
    industry, item = rows[at - 3], rows[at - 2]
    cols = {(_text(industry[j]), _text(item[j])): j for j in range(2, min(len(industry), len(item)))
            if _text(industry[j]) and _text(item[j])}
    out = {}
    for r in rows[at + 1:]:
        if len(r) < 2 or not _text(r[1]):
            continue
        level, code = _text(r[0]), _text(r[1]).split("_")[0]
        vals = {}
        for key, j in cols.items():
            v = r[j] if j < len(r) else None
            vals[key] = v if isinstance(v, float) else (0.0 if _text(v) == "-" else None)
        out[(level, code)] = vals
    return out


def ingest(conn: sqlite3.Connection, files: list[Path], source_id: str, catalog: dict, year: int) -> dict:
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == KIND}
    known = {r[0] for r in conn.execute(
        "SELECT entity_id FROM entities WHERE entity_type IN ('municipality', 'prefecture')")}
    rows: dict[str, dict] = {}
    for path in sorted(files):
        for (level, code), vals in read_table(path).items():
            if level in LEVELS_MUNI:
                rows[f"muni-{code}"] = vals
            elif level == "a" and code.endswith("000") and code != "00000":
                rows[prefecture_entity_id(code[:2])] = vals
    result = {"rows": len(rows), "matched": 0, "suppressed": 0,
              "unmatched": sorted(e for e in rows if e not in known)[:30]}
    for entity_id, vals in rows.items():
        if entity_id not in known:
            continue
        result["matched"] += 1
        for indicator_id, d in targets.items():
            v = vals.get(tuple(d["commerce_column"]))
            base = dict(entity_id=entity_id, indicator_id=indicator_id, definition_version=d["definition_version"],
                        period_start=f"{year}-01-01", period_end=f"{year}-12-31", period_kind="calendar_year",
                        source_id=source_id)
            if v is None:
                result["suppressed"] += 1
                insert_observation(conn, value=None, status="suppressed", method_note="秘匿", **base)
            else:
                insert_observation(conn, value=v * float(d.get("scale", 1)), status="observed", **base)
    return result
