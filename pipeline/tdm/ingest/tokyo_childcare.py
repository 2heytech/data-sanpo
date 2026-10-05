"""東京都の報道発表「都内の保育サービスの状況について」表4（区市町村別の状況）を取り込む。

形式（令和8年4月1日分の Excel を 2026-10-03 に GitHub Actions から取得して確認）: 1シート「表４」。
3行目に「区市町村名」と時点（その年・前年の4月1日。日付のセル）と「増減」、4行目に各時点の
「就学前児童人口（a）」「保育サービス利用児童数（b）」「保育サービス利用率（b/a）」「待機児童数」が並ぶ
（列名にセル内の改行がある）。各行の先頭が区市町村名で、区部計・市部計などの行もある。
1つのファイルに2時点あるので、取り込む年は出典ごとに years で指定する（その年の発表を優先し、
発表が見つからない年だけ翌年の発表の前年の列を使う）。

指標（definition の childcare_value で選ぶ）:
  waiting: 待機児童数（人）
  usage_rate: 保育サービス利用児童数 ÷ 就学前児童人口（率は分子・分母から計算し、公表の利用率は使わない）
"""
from __future__ import annotations

import datetime as dt
import re
import sqlite3
from pathlib import Path

from ..db import insert_observation
from ..xlsx import read_sheet

EXCEL_EPOCH = dt.date(1899, 12, 30)


def _year_of(cell) -> int | None:
    if isinstance(cell, float) and 20000 < cell < 80000:     # Excel の日付（シリアル値）
        return (EXCEL_EPOCH + dt.timedelta(days=int(cell))).year
    if isinstance(cell, str):
        s = cell.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        if m := re.search(r"(20\d\d)", s):
            return int(m.group(1))
        if m := re.search(r"令和\s*(\d+|元)\s*年", s):
            return 2018 + (1 if m.group(1) == "元" else int(m.group(1)))
    return None


def _label(cell) -> str:
    return re.sub(r"\s+", "", str(cell or ""))


def read_table(path: Path) -> dict[int, dict[str, dict[str, float | None]]]:
    """年 → 区市町村名 → {"children", "users", "waiting"}。"""
    rows = read_sheet(path)
    at = next(i for i, r in enumerate(rows) if any(_label(c) == "区市町村名" for c in r))
    head, sub = rows[at], rows[at + 1]
    starts = [(i, _year_of(c)) for i, c in enumerate(head) if _year_of(c)]
    name_col = next(i for i, c in enumerate(head) if _label(c) == "区市町村名")
    out: dict[int, dict[str, dict[str, float | None]]] = {}
    for k, (start, year) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else start + 4
        span = {_label(sub[i]): i for i in range(start, min(end, len(sub)))}

        def col(prefix: str) -> int:
            return next(i for lab, i in span.items() if lab.startswith(prefix))

        cols = {"children": col("就学前"), "users": col("保育サービス利用児童数"), "waiting": col("待機")}
        table = out.setdefault(year, {})
        for r in rows[at + 2:]:
            name = _label(r[name_col] if name_col < len(r) else "")
            if not name:
                continue
            table[name] = {k2: (r[i] if i < len(r) and isinstance(r[i], float) else None)
                           for k2, i in cols.items()}
    return out


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict, years: list[int]) -> dict:
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "tokyo_childcare"}
    by_name = {r["name"]: r["entity_id"] for r in conn.execute(
        "SELECT entity_id, name FROM entities WHERE entity_type = 'municipality' "
        "AND entity_id LIKE 'muni-13%'")}   # 東京都だけ。府中市（広島県）など同じ名前の市区町村が他県にもある
    data = read_table(path)
    result: dict = {"unmatched": []}
    for year in years:
        if year not in data:
            raise KeyError(f"{path.name}: {year}年の列がありません（{sorted(data)}）")
        period = (f"{year}-04-01", f"{year}-04-01", "point")
        n = 0
        for name, v in data[year].items():
            entity_id = by_name.get(name)
            if entity_id is None:
                if year == years[0]:
                    result["unmatched"].append(name)   # 区部計・市部計・合計など
                continue
            for indicator_id, d in targets.items():
                obs = dict(entity_id=entity_id, indicator_id=indicator_id,
                           definition_version=d["definition_version"], period_start=period[0],
                           period_end=period[1], period_kind=period[2], source_id=source_id)
                if d["childcare_value"] == "waiting":
                    insert_observation(conn, value=v["waiting"],
                                       status="observed" if v["waiting"] is not None else "missing", **obs)
                else:
                    num, den = v["users"], v["children"]
                    ok = num is not None and den
                    insert_observation(conn, value=num / den * d.get("scale", 1) if ok else None,
                                       status="derived" if ok else "missing", numerator=num,
                                       denominator=den, denominator_source_id=source_id, **obs)
            n += 1
        result[year] = n
    return result
