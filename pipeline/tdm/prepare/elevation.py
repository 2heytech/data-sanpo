"""地理院タイル「標高タイル（基盤地図情報数値標高モデル）」（dem_png）から、町丁・字等ごとの平均標高・最高・最低を出す
（docs/design-changes.md #123）。

ズーム12のタイル（1画素は東京あたりで約31m四方）の各画素の中心が入る町丁・字等に、その画素の標高を数える
（画素を境界で分けない）。PNG の画素の色 (R, G, B) から x = R×65536 + G×256 + B とし、x < 2^23 なら x×0.01m、
x > 2^23 なら (x − 2^24)×0.01m（海面より低い所）、x = 2^23 は標高のない画素（海など）で数えない。
タイルのない範囲（海だけの範囲）は 404 が返るので飛ばす。
"""
from __future__ import annotations

import csv
import gzip
import io
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import shapely

from ..fetch import download
from ..progress import progress
from .towns import Towns

NO_VALUE = 2 ** 23
TILE = 256
DOWNLOAD_WORKERS = 4
COLUMNS = ["点の数", "標高の合計", "最低", "最高"]


def decode(png: bytes) -> np.ndarray:
    """標高タイルの PNG → 256×256 の標高（m）。標高のない画素は NaN。"""
    from PIL import Image   # 準備の処理だけで使う
    rgb = np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(np.int64)
    x = rgb[..., 0] * 65536 + rgb[..., 1] * 256 + rgb[..., 2]
    h = np.where(x < NO_VALUE, x, x - 2 ** 24) * 0.01
    return np.where(x == NO_VALUE, np.nan, h)


def pixel_centers(zoom: int, tx: int, ty: int) -> tuple[np.ndarray, np.ndarray]:
    """タイルの画素の中心の経度・緯度（256×256、行が北から）。"""
    n = 2 ** zoom
    i = (np.arange(TILE) + 0.5) / TILE
    lon = (tx + i) / n * 360 - 180
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (ty + i) / n))))
    lon2, lat2 = np.meshgrid(lon, lat)
    return lon2, lat2


def tile_box(zoom: int, tx: int, ty: int) -> tuple[float, float, float, float]:
    n = 2 ** zoom
    west, east = tx / n * 360 - 180, (tx + 1) / n * 360 - 180
    north = float(np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * ty / n)))))
    south = float(np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (ty + 1) / n)))))
    return west, south, east, north


def tiles_for(towns: Towns, zoom: int) -> list[tuple[int, int]]:
    """町丁・字等のどれかにかかるタイル。"""
    west, south, east, north = towns.bounds
    n = 2 ** zoom
    x0, x1 = int((west + 180) / 360 * n), int((east + 180) / 360 * n)
    y0 = int((1 - np.arcsinh(np.tan(np.radians(north))) / np.pi) / 2 * n)
    y1 = int((1 - np.arcsinh(np.tan(np.radians(south))) / np.pi) / 2 * n)
    out = []
    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            if len(towns.tree.query(shapely.box(*tile_box(zoom, tx, ty)), predicate="intersects")):
                out.append((tx, ty))
    return out


def fetch_tile(url_template: str, zoom: int, tx: int, ty: int, work: Path, downloader=download) -> np.ndarray | None:
    """標高タイル（取得したものは work に残す）。海だけのタイル（404）は None。"""
    path = work / str(zoom) / str(tx) / f"{ty}.png"
    empty = path.with_suffix(".none")
    if empty.exists():
        return None
    if not path.exists():
        url = url_template.replace("{z}", str(zoom)).replace("{x}", str(tx)).replace("{y}", str(ty))
        try:
            data = downloader(url)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            empty.parent.mkdir(parents=True, exist_ok=True)
            empty.touch()
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return decode(path.read_bytes())


def summarize(towns: Towns, url_template: str, zoom: int, work: Path, downloader=download) -> list[list]:
    """1つの都道府県の町丁・字等ごとの（点の数、標高の合計、最低、最高）。"""
    n = len(towns.keys)
    count = np.zeros(n, dtype=np.int64)
    total = np.zeros(n)
    low = np.full(n, np.inf)
    high = np.full(n, -np.inf)
    tiles = tiles_for(towns, zoom)

    def one(t):
        return t, fetch_tile(url_template, zoom, t[0], t[1], work, downloader)

    with ThreadPoolExecutor(DOWNLOAD_WORKERS) as pool:
        for (tx, ty), h in pool.map(one, tiles):
            if h is None:
                continue
            lon, lat = pixel_centers(zoom, tx, ty)
            ok = ~np.isnan(h)
            idx = towns.locate(lon[ok], lat[ok])
            hit = idx >= 0
            idx, vals = idx[hit], h[ok][hit]
            count += np.bincount(idx, minlength=n)
            total += np.bincount(idx, weights=vals, minlength=n)
            np.minimum.at(low, idx, vals)
            np.maximum.at(high, idx, vals)
    rows = []
    for i, key in enumerate(towns.keys):
        if count[i]:
            rows.append([key, int(count[i]), round(float(total[i]), 2), round(float(low[i]), 2), round(float(high[i]), 2)])
        else:
            rows.append([key, 0, "", "", ""])
    return rows


def prepare(cfg: dict, outputs: dict[str, Path], work: Path, prefs: list[str], load_towns,
            downloader=download) -> dict:
    rows: list[list] = []
    for pref in prefs:
        started = time.monotonic()
        towns = load_towns(pref)
        rows += summarize(towns, cfg["tiles"], int(cfg["zoom"]), work, downloader)
        progress(f"標高 {pref}: {len(towns.keys)} 地域（{time.monotonic() - started:.0f} 秒）")
    rows.sort(key=lambda r: r[0])
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["KEY_CODE", *COLUMNS])
    w.writerows(rows)
    outputs["towns"].parent.mkdir(parents=True, exist_ok=True)
    outputs["towns"].write_bytes(gzip.compress(buf.getvalue().encode("utf-8"), 9, mtime=0))
    return {"towns": len(rows)}
