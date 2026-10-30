"""地理院タイル「標高タイル（基盤地図情報数値標高モデル）」（dem_png）から、町丁・字等ごとの地面の傾斜をまとめる
（docs/design-changes.md #179）。

ズーム14のタイル（元の標高は約10m間隔。1画素は東京あたりで約8m四方）の画素ごとに、周りの8画素の標高から傾斜（度）を
計算し（Horn 法。地図の背景「傾斜」の web/src/map/slope.ts と同じ計算）、画素の中心が入る町丁・字等に数える
（画素を境界で分けない）。タイルの端の画素は隣のタイルの標高を使う。標高のない画素（海など）は数えず、周りの画素に
標高がないとき（海岸・タイルのない所）は、その画素と同じ高さとして計算する。
列は「KEY_CODE, 点の数, 傾斜の合計, 3度以上, 4度以上, …」（傾斜の合計は度の合計、「○度以上」はその傾斜以上の点の数）。

全国のズーム14のタイルは十数万枚あるので、取得は多くを並べて行い（workers）、取得したタイルは都道府県ごとに消す。
1回目に全部のタイルを取得して端の1列ずつの標高を覚え、2回目にタイルごとに傾斜を計算して町丁・字等ごとに足す
（2回目は1つずつ。町丁・字等の図形を調べる GEOS は、同じ図形をいくつものスレッドから使うと落ちることがあるため）。
"""
from __future__ import annotations

import csv
import gzip
import io
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from ..fetch import download
from ..progress import progress
from .elevation import TILE, decode, fetch_tile, pixel_centers, tile_box, tiles_for
from .towns import Towns

EARTH_CIRCUMFERENCE = 2 * np.pi * 6378137


def column_names(thresholds: list[float]) -> list[str]:
    return ["点の数", "傾斜の合計", *(f"{t:g}度以上" for t in thresholds)]


def pixel_meters(zoom: int, ty: int) -> np.ndarray:
    """タイルの行ごとの画素の地上の大きさ（m）。ウェブメルカトルの画素は東西・南北とも 赤道での大きさ × cos(緯度)。"""
    n = 2 ** zoom
    lat = np.arctan(np.sinh(np.pi * (1 - 2 * (ty + (np.arange(TILE) + 0.5) / TILE) / n)))
    return EARTH_CIRCUMFERENCE / (TILE * n) * np.cos(lat)


Edges = tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]   # 上の行・下の行・左の列・右の列


def edges_of(dem: np.ndarray) -> Edges:
    return dem[0].copy(), dem[-1].copy(), dem[:, 0].copy(), dem[:, -1].copy()


def padded(dem: np.ndarray, near: dict[tuple[int, int], Edges | None]) -> np.ndarray:
    """タイルの標高の周りに、隣のタイル（near: (dx, dy) → 端の標高。ないタイルは None）の1画素ずつを足した 258×258。"""
    grid = np.full((TILE + 2, TILE + 2), np.nan)
    grid[1:-1, 1:-1] = dem
    if (e := near.get((0, -1))) is not None:
        grid[0, 1:-1] = e[1]
    if (e := near.get((0, 1))) is not None:
        grid[-1, 1:-1] = e[0]
    if (e := near.get((-1, 0))) is not None:
        grid[1:-1, 0] = e[3]
    if (e := near.get((1, 0))) is not None:
        grid[1:-1, -1] = e[2]
    if (e := near.get((-1, -1))) is not None:
        grid[0, 0] = e[1][-1]
    if (e := near.get((1, -1))) is not None:
        grid[0, -1] = e[1][0]
    if (e := near.get((-1, 1))) is not None:
        grid[-1, 0] = e[0][-1]
    if (e := near.get((1, 1))) is not None:
        grid[-1, -1] = e[0][0]
    return grid


def slope_degrees(grid: np.ndarray, zoom: int, ty: int) -> np.ndarray:
    """258×258 の標高 → 真ん中の 256×256 の画素の傾斜（度）。標高のない画素は NaN。"""
    e = grid[1:-1, 1:-1]

    def at(dr: int, dc: int) -> np.ndarray:
        v = grid[1 + dr:TILE + 1 + dr, 1 + dc:TILE + 1 + dc]
        return np.where(np.isnan(v), e, v)
    a, b, c = at(-1, -1), at(-1, 0), at(-1, 1)
    d, f = at(0, -1), at(0, 1)
    g, h, k = at(1, -1), at(1, 0), at(1, 1)
    d8 = 8 * pixel_meters(zoom, ty)[:, None]
    sx = (c + 2 * f + k - (a + 2 * d + g)) / d8
    sy = (g + 2 * h + k - (a + 2 * b + c)) / d8
    return np.degrees(np.arctan(np.hypot(sx, sy)))


def summarize(towns: Towns, url_template: str, zoom: int, thresholds: list[float], work: Path,
              downloader=download, workers: int = 32) -> list[list]:
    """1つの都道府県の町丁・字等ごとの（点の数、傾斜の合計、○度以上の点の数…）。"""
    n = len(towns.keys)
    bins = np.asarray(thresholds, dtype=float)
    count = np.zeros(n, dtype=np.int64)
    total = np.zeros(n)
    at_least = np.zeros((n, len(bins)), dtype=np.int64)
    tiles = tiles_for(towns, zoom)
    needed = sorted({(tx + dx, ty + dy) for tx, ty in tiles for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                     if 0 <= ty + dy < 2 ** zoom})

    def edges(t):
        dem = fetch_tile(url_template, zoom, t[0], t[1], work, downloader)
        return t, None if dem is None else edges_of(dem)

    with ThreadPoolExecutor(workers) as pool:
        border = dict(pool.map(edges, needed))

    def one(t):
        tx, ty = t
        if border.get(t) is None:
            return None
        dem = decode((work / str(zoom) / str(tx) / f"{ty}.png").read_bytes())
        near = {(dx, dy): border.get((tx + dx, ty + dy)) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy}
        s = slope_degrees(padded(dem, near), zoom, ty).ravel()
        lon, lat = pixel_centers(zoom, tx, ty)
        idx = towns.locate_in_box(lon.ravel(), lat.ravel(), tile_box(zoom, tx, ty))
        ok = (idx >= 0) & ~np.isnan(s)
        idx, s = idx[ok], s[ok]
        if not len(idx):
            return None
        ids, inv = np.unique(idx, return_inverse=True)
        cls = np.searchsorted(bins, s, side="right")   # 0: 一番下の境目より小さい、k: k番目の境目以上
        hist = np.bincount(inv * (len(bins) + 1) + cls, minlength=len(ids) * (len(bins) + 1))
        hist = hist.reshape(len(ids), len(bins) + 1)[:, ::-1].cumsum(axis=1)[:, ::-1][:, 1:]   # ○度以上の点の数
        return ids, np.bincount(inv), np.bincount(inv, weights=s), hist

    towns.prepare()
    for got in map(one, tiles):
        if got is None:
            continue
        ids, c, s, h = got
        count[ids] += c
        total[ids] += s
        at_least[ids] += h
    rows = []
    for i, key in enumerate(towns.keys):
        if count[i]:
            rows.append([key, int(count[i]), round(float(total[i]), 1), *(int(v) for v in at_least[i])])
        else:
            rows.append([key, 0, "", *([""] * len(bins))])
    return rows


def prepare(cfg: dict, outputs: dict[str, Path], work: Path, prefs: list[str], load_towns,
            downloader=download) -> dict:
    zoom, thresholds = int(cfg["zoom"]), [float(t) for t in cfg["thresholds"]]
    rows: list[list] = []
    for pref in prefs:
        started = time.monotonic()
        towns = load_towns(pref)
        rows += summarize(towns, cfg["tiles"], zoom, thresholds, work, downloader, int(cfg.get("workers", 32)))
        # 取得したタイルは都道府県ごとに消す（全国で10GBほどになるので）
        shutil.rmtree(work / str(zoom), ignore_errors=True)
        progress(f"傾斜 {pref}: {len(towns.keys)} 地域（{time.monotonic() - started:.0f} 秒）")
    rows.sort(key=lambda r: r[0])
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["KEY_CODE", *column_names(thresholds)])
    w.writerows(rows)
    outputs["towns"].parent.mkdir(parents=True, exist_ok=True)
    outputs["towns"].write_bytes(gzip.compress(buf.getvalue().encode("utf-8"), 9, mtime=0))
    return {"towns": len(rows)}
