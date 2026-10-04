"""SQLite に確定する前後の検証（設計書 第10章「検証」）。

errors は公開を止める問題、warnings は確認が必要な点。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

# 日本の範囲（与那国島・沖ノ鳥島・南鳥島・択捉島を含む）
JAPAN_BBOX = (122.9, 20.3, 154.0, 45.6)


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(conn: sqlite3.Connection, catalog: dict[str, dict]) -> Report:
    rep = Report()
    for row in conn.execute("PRAGMA foreign_key_check"):
        rep.errors.append(f"外部キー違反: {tuple(row)}")

    west, south, east, north = JAPAN_BBOX
    bad = conn.execute(
        """SELECT entity_id FROM boundaries
           WHERE bbox_west < ? OR bbox_south < ? OR bbox_east > ? OR bbox_north > ?""",
        (west, south, east, north)).fetchall()
    for r in bad:
        rep.errors.append(f"座標が日本の範囲外（緯度経度の取り違えの可能性）: {r[0]}")

    missing_boundary = conn.execute(
        """SELECT e.entity_id FROM entities e
           LEFT JOIN boundaries b ON b.entity_id = e.entity_id
           WHERE e.entity_type IN ('municipality', 'small_area') AND b.entity_id IS NULL"""
    ).fetchall()
    for r in missing_boundary:
        rep.errors.append(f"境界がない地域: {r[0]}")

    for indicator_id, d in catalog.items():
        # 割合（0〜scale）だけ範囲を確かめる。昼夜間人口比率のように100を超える比は unbounded = true
        if d["kind"] == "ratio" and d["unit"] == "%" and not d.get("unbounded"):
            scale = float(d.get("scale", 1))
            out = conn.execute(
                """SELECT entity_id, value FROM observations
                   WHERE indicator_id = ? AND value IS NOT NULL AND (value < 0 OR value > ?)""",
                (indicator_id, scale)).fetchall()
            for r in out:
                rep.errors.append(f"{indicator_id}: 割合が範囲外 {r[0]}={r[1]}")
        if d["kind"] != "change":  # 増減率は減少で負になる
            neg = conn.execute(
                "SELECT entity_id FROM observations WHERE indicator_id = ? AND value < 0",
                (indicator_id,)).fetchall()
            for r in neg:
                rep.errors.append(f"{indicator_id}: 負の値 {r[0]}")
        # 犯罪の件数は町丁目不明（以下不詳）の分だけ区市町村の値が大きい。取込時に合計を確かめている
        # 樹種の数のように足し合わせられない数（not_additive）も比べない
        if d["kind"] == "count" and d.get("source_kind") != "keishicho_crime" and not d.get("not_additive"):
            _check_sum(conn, indicator_id, rep)
    return rep


def _check_sum(conn: sqlite3.Connection, indicator_id: str, rep: Report) -> None:
    """町丁・字等の合計と市区町村の公表値を比べる（秘匿の合算先を含めれば一致するはず）。"""
    rows = conn.execute(
        """SELECT m.entity_id, m.name, mo.period_start, mo.period_end, mo.value AS published,
                  SUM(ao.value) AS summed
           FROM entities m
           JOIN observations mo ON mo.entity_id = m.entity_id AND mo.indicator_id = ?
           JOIN entities a ON a.parent_id = m.entity_id AND a.entity_type = 'small_area'
           JOIN observations ao ON ao.entity_id = a.entity_id AND ao.indicator_id = ?
                AND ao.period_start = mo.period_start AND ao.period_end = mo.period_end
           WHERE m.entity_type = 'municipality' AND mo.value IS NOT NULL
           GROUP BY m.entity_id, mo.period_start, mo.period_end""",   # 年計と複数年の合計は始まりが同じ
        (indicator_id, indicator_id)).fetchall()
    for r in rows:
        published, summed = r["published"], r["summed"] or 0
        if published and abs(summed - published) / published > 0.005:
            rep.warnings.append(
                f"{indicator_id} {r['name']} {r['period_start']}〜{r['period_end']}: 町丁・字等の合計 {summed:,.0f}"
                f" と市区町村の値 {published:,.0f} が0.5%以上異なります")
