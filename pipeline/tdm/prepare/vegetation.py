"""環境省 生物多様性センター「現存植生図2024」から、町丁・字等ごとの植生の区分別の面積を出す（docs/design-changes.md #124）。

現存植生図2024 は、1/25,000 の植生図（調査は地域により2000〜2023年度）を全国でつないだもの。地域ブロックごとの
GeoPackage（全国で12ファイル・約8.8GB、JGD2011 の経度・緯度）を取得して使う。
町丁・字等の形と植生図の面（ポリゴン）の重なりの面積を、区分ごとに足す。
区分（COLUMNS）:
  自然林 = 植生自然度 9、二次林 = 植生自然度 7・8（自然林に近い二次林を含む）、
  植林地 = 凡例の大区分 54（スギ・ヒノキ・サワラ植林、アカマツ植林など）、竹林 = 凡例の大区分 55、
  その他 = それ以外（市街地・農耕地・草原・自然裸地・開放水域など）。
植生図の範囲外（GAP）は、町丁・字等の面積のうち植生図の面がない部分（1/25,000 の植生図がまだない範囲など）。
面積は経度・緯度での図形の面積に、町丁・字等の中の点の緯度での1度あたりの長さ（南北×東西、GRS80）を掛けて㎡にし、
ha で書く。
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import numpy as np
import shapely

from ..fetch import download
from ..progress import progress
from .land_use import write_counts
from .towns import Towns

COLUMNS = ["自然林", "二次林", "植林地", "竹林", "その他"]
GAP = "植生図の範囲外"
OTHER = len(COLUMNS) - 1


def category(naturalness: str | None, legend: str | None) -> int:
    """植生自然度・凡例コード（6桁）→ COLUMNS の番号。"""
    major = (legend or "")[:2]
    if major == "55":
        return 3
    if major == "54":
        return 2
    nat = int(naturalness) if (naturalness or "").strip().isdigit() else 0
    return 0 if nat == 9 else 1 if nat in (7, 8) else OTHER


def m2_per_deg2(lat: np.ndarray) -> np.ndarray:
    """緯度 lat の所の、経度1度×緯度1度の面積（㎡、GRS80）。"""
    a, f = 6378137.0, 1 / 298.257222101
    e2 = f * (2 - f)
    s = np.sin(np.radians(lat))
    w = np.sqrt(1 - e2 * s * s)
    return (np.pi / 180) ** 2 * (a * (1 - e2) / w ** 3) * (a / w) * np.cos(np.radians(lat))


def gpkg_wkb(blob: bytes) -> bytes:
    """GeoPackage の図形（ヘッダー＋WKB）から WKB を取り出す。"""
    envelope = (0, 32, 48, 48, 64)[(blob[3] >> 1) & 7]
    return blob[8 + envelope:]


def read_polygons(path: Path, boxes: list[tuple[float, float, float, float]]) -> tuple[np.ndarray, np.ndarray]:
    """GeoPackage のうち、boxes（西・南・東・北）のどれかにかかる面と、その区分の番号。"""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        table, column = con.execute("SELECT table_name, column_name FROM gpkg_geometry_columns").fetchone()
        pk = next(r[1] for r in con.execute(f'PRAGMA table_info("{table}")') if r[5])
        ids: set[int] = set()
        for west, south, east, north in boxes:
            ids.update(r[0] for r in con.execute(
                f'SELECT id FROM "rtree_{table}_{column}" WHERE maxx >= ? AND minx <= ? AND maxy >= ? AND miny <= ?',
                (west, east, south, north)))
        con.execute("CREATE TEMP TABLE wanted (id INTEGER PRIMARY KEY)")
        con.executemany("INSERT INTO wanted VALUES (?)", ((i,) for i in ids))
        rows = con.execute(f'SELECT t."{column}", t."植生自然度", t."凡例コード" FROM "{table}" t '
                           f'JOIN wanted w ON w.id = t."{pk}"').fetchall()
    finally:
        con.close()
    geoms = shapely.from_wkb([gpkg_wkb(r[0]) for r in rows if r[0]]) if rows else np.array([], dtype=object)
    cats = np.array([category(r[1], r[2]) for r in rows if r[0]], dtype=np.int64)
    bad = ~shapely.is_valid(geoms)
    if bad.any():
        geoms[bad] = shapely.make_valid(geoms[bad])
    return geoms, cats


def _boxes(towns: Towns) -> list[tuple[float, float, float, float]]:
    """市区町村ごとの町丁・字等の範囲（都道府県の範囲は離島で広くなるため、市区町村ごとに植生図を探す）。"""
    groups: dict[str, list] = {}
    for key, g in zip(towns.keys, towns.geoms):
        groups.setdefault(key[:5], []).append(g)
    return [tuple(shapely.total_bounds(np.array(gs, dtype=object))) for gs in groups.values()]  # type: ignore[misc]


def summarize(towns: Towns, blocks: list[Path], year: int) -> list[list]:
    """1つの都道府県の町丁・字等ごとの [KEY_CODE, 年度, 区分ごとの面積…, 植生図の範囲外]（ha）。"""
    n = len(towns.keys)
    tg = np.array(towns.geoms, dtype=object)
    tg = np.where(shapely.is_valid(tg), tg, shapely.make_valid(tg))   # 重なりの計算で止まらないように
    scale = m2_per_deg2(shapely.get_y(shapely.point_on_surface(tg)))
    areas = np.zeros((n, len(COLUMNS)))
    boxes = _boxes(towns)
    for path in blocks:
        geoms, cats = read_polygons(path, boxes)
        if not len(geoms):
            continue
        ti, vi = shapely.STRtree(geoms).query(tg, predicate="intersects")
        np.add.at(areas, (ti, cats[vi]), shapely.area(shapely.intersection(tg[ti], geoms[vi])))
    areas *= scale[:, None]
    gap = np.maximum(shapely.area(tg) * scale - areas.sum(axis=1), 0)
    return [[key, year, *(round(float(a) / 1e4, 4) for a in areas[i]), round(float(gap[i]) / 1e4, 4)]
            for i, key in enumerate(towns.keys)]


def fetch_blocks(urls: list[str], work: Path, downloader=download) -> list[Path]:
    """地域ブロックの GeoPackage（取得したものは work に残す）。"""
    out = []
    for url in urls:
        path = work / url.rsplit("/", 1)[1]
        if not path.exists():
            started = time.monotonic()
            data = downloader(url)
            work.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.rename(path)
            progress(f"植生図 {path.name}: {len(data) / 1e6:,.0f}MB（{time.monotonic() - started:.0f} 秒）")
        out.append(path)
    return out


def prepare(cfg: dict, outputs: dict[str, Path], work: Path, prefs: list[str], load_towns,
            downloader=download) -> dict:
    blocks = fetch_blocks(cfg["blocks"], work, downloader)
    year = int(cfg["year"])
    rows: list[list] = []
    for pref in prefs:
        started = time.monotonic()
        towns = load_towns(pref)
        rows += summarize(towns, blocks, year)
        progress(f"植生図 町丁・字等への集計 {pref}: {len(towns.keys)} 地域（{time.monotonic() - started:.0f} 秒）")
    write_counts(outputs["towns"], [*COLUMNS, GAP], rows)
    return {"towns": len(rows)}
