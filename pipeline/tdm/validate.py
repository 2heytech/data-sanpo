"""SQLite に確定する前後の検証（設計書 第10章「検証」）。

errors は公開を止める問題、warnings は確認が必要な点。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

# 日本の範囲（与那国島・沖ノ鳥島・南鳥島・択捉島を含む）
JAPAN_BBOX = (122.9, 20.3, 154.0, 45.6)

# 観測値の番号の列と、その文字列があるべき表（schema.sql の旧 observations の外部キーと同じ）
_OBS_REFERENCES = (
    ("entity_k", "SELECT entity_id FROM entities"),
    ("source_k", "SELECT source_id FROM sources"),
    ("denominator_source_k", "SELECT source_id FROM sources"),
    ("boundary_k", "SELECT boundary_id FROM boundaries"),
)


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
    # 観測値（obs）は番号で持つので外部キーの制約がない。参照先があるかをここで確かめる
    for column, sql in _OBS_REFERENCES:
        for r in conn.execute(
                f"""SELECT k.key FROM (SELECT DISTINCT {column} AS x FROM obs) o
                    JOIN keys k ON k.key_id = o.x WHERE k.key NOT IN ({sql})"""):
            rep.errors.append(f"外部キー違反: obs.{column} = {r[0]}")
    for r in conn.execute(
            """SELECT ki.key, kd.key FROM (SELECT DISTINCT indicator_k, definition_version_k FROM obs) o
               JOIN keys ki ON ki.key_id = o.indicator_k JOIN keys kd ON kd.key_id = o.definition_version_k
               WHERE NOT EXISTS (SELECT 1 FROM indicators i WHERE i.indicator_id = ki.key
                                 AND i.definition_version = kd.key)"""):
        rep.errors.append(f"外部キー違反: 指標の定義がない観測値 {r[0]} {r[1]}")

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

    areas = _areas(conn)
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
            _check_sum(conn, indicator_id, rep, areas)
    return rep


def _check_sum(conn: sqlite3.Connection, indicator_id: str, rep: Report,
               areas: dict[str, tuple[str, str]] | None = None) -> None:
    """町丁・字等の合計と市区町村の公表値を比べる（秘匿の合算先を含めれば一致するはず）。
    観測値は指標ごとに1回だけ読み、Python で集計する（観測値のビューどうしを JOIN すると全国で遅い）。"""
    if areas is None:
        areas = _areas(conn)
    published: dict[tuple, float] = {}
    summed: dict[tuple, float] = {}
    for r in conn.execute(
            """SELECT entity_id, period_start, period_end, value FROM observations
               WHERE indicator_id = ?""", (indicator_id,)):
        a = areas.get(r["entity_id"])
        if a is None:
            continue
        if a[0] == "municipality":
            if r["value"] is not None:
                published[(r["entity_id"], r["period_start"], r["period_end"])] = r["value"]
        elif a[1] is not None:   # 町丁・字等は親の区市町村に足す（年計と複数年の合計は始まりが同じ）
            key = (a[1], r["period_start"], r["period_end"])
            summed[key] = summed.get(key, 0.0) + (r["value"] or 0)
    for key in sorted(published.keys() & summed.keys()):
        pub, total = published[key], summed[key]
        if pub and abs(total - pub) / pub > 0.005:
            muni, start, end = key
            rep.warnings.append(
                f"{indicator_id} {areas[muni][2]} {start}〜{end}: 町丁・字等の合計 {total:,.0f}"
                f" と市区町村の値 {pub:,.0f} が0.5%以上異なります")


def _areas(conn: sqlite3.Connection) -> dict[str, tuple[str, str | None, str]]:
    """区市町村と町丁・字等の (種類, 親, 名前)。"""
    return {r[0]: (r[1], r[2] if r[1] == "small_area" else None, r[3]) for r in conn.execute(
        """SELECT entity_id, entity_type, parent_id, name FROM entities
           WHERE entity_type IN ('municipality', 'small_area')""")}
