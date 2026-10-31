"""土地利用別の地面の傾斜（建物用地・田・畑などの傾斜）を町丁・字等ごとにまとめる（docs/design-changes.md #181）。

傾斜は slope.py（#179）と同じく、地理院タイル「標高タイル」のズーム14の画素ごとに周りの8画素の標高から計算する。
その画素の中心が入る、国土数値情報「土地利用細分メッシュ」（令和3年度、100m四方のマス）の区分を画素につけ、
町丁・字等ごと・区分ごとに数える（マスを画素に割り振るのではなく、画素が入るマスの区分をそのまま使う）。
海・分類のないマス・データのない範囲に入る画素は数えない。
列は「KEY_CODE, 区分, 点の数, 傾斜の合計, 1度以上, 2度以上, …」で、点のある町丁・字等と区分の組だけを書く
（ない組は点が0）。区分は config/prepare.toml の land_uses（land_use.py の LAND_USE の名前）。
"""
from __future__ import annotations

import csv
import gzip
import io
import shutil
import time
from pathlib import Path

import numpy as np

from ..fetch import download
from ..progress import progress
from . import land_use as lu
from . import slope
from .mesh import CELLS, COLS_PER_DEG, ROWS_PER_DEG


def classifier(grids: dict[str, np.ndarray], land_uses: list[str]):
    """点の経度・緯度 → 点が入る100mのマスの区分の番号（land_uses の順に1から。ほかの区分・海・マスのない所は0）。"""
    by_mesh = {int(mesh): grid for mesh, grid in grids.items()}
    to_class = np.zeros(256, dtype=np.int64)
    for i, name in enumerate(land_uses):
        to_class[lu.LAND_USE.index(name) + 1] = i + 1

    def classify(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
        row = np.floor(lat * ROWS_PER_DEG).astype(np.int64)
        col = np.floor((lon - 100) * COLS_PER_DEG).astype(np.int64)
        mesh = (row // CELLS) * 100 + col // CELLS   # 1次メッシュのコード（緯度×1.5 の2桁 + 経度−100 の2桁）
        out = np.zeros(len(lon), dtype=np.int64)
        for m in np.unique(mesh):
            grid = by_mesh.get(int(m))
            if grid is None:
                continue
            sel = mesh == m
            out[sel] = to_class[grid[row[sel] - (m // 100) * CELLS, col[sel] - (m % 100) * CELLS]]
        return out
    return classify


def summarize(towns, url_template: str, zoom: int, thresholds: list[float], work: Path, classify,
              land_uses: list[str], downloader=download, workers: int = 32) -> list[list]:
    """1つの都道府県の町丁・字等と区分ごとの（点の数、傾斜の合計、○度以上の点の数…）。点のない組は書かない。"""
    count, total, at_least = slope.count_points(towns, url_template, zoom, thresholds, work, downloader, workers,
                                                classify=classify, classes=len(land_uses))
    rows = []
    for i, key in enumerate(towns.keys):
        for k, name in enumerate(land_uses):
            if count[i, k]:
                rows.append([key, name, int(count[i, k]), round(float(total[i, k]), 1),
                             *(int(v) for v in at_least[i, k])])
    return rows


def prepare(cfg: dict, outputs: dict[str, Path], work: Path, prefs: list[str], load_towns,
            downloader=download) -> dict:
    zoom, thresholds = int(cfg["zoom"]), [float(t) for t in cfg["thresholds"]]
    land_uses = list(cfg["land_uses"])
    unknown = [n for n in land_uses if n not in lu.LAND_USE]
    if unknown:
        raise ValueError(f"土地利用の区分 {unknown} は land_use.LAND_USE にありません")
    # 一部の都道府県だけで試すときは、その都道府県にかかる1次メッシュだけを取得する
    wanted = None
    if len(prefs) < 47:
        all_towns = [load_towns(p) for p in prefs]
        wanted = lambda mesh: any(lu.towns_in(t, mesh) for t in all_towns)  # noqa: E731
    meshes = [m for m in lu.listed_meshes(cfg["mesh_list"], cfg["land_use_url"], downloader) if not wanted or wanted(m)]
    grids = lu.load_grids(work / "land_use", "土地利用", cfg["land_use_url"], meshes, lu.CODE_TABLES[cfg["codes"]],
                          downloader)
    classify = classifier(grids, land_uses)
    rows: list[list] = []
    for pref in prefs:
        started = time.monotonic()
        towns = load_towns(pref)
        rows += summarize(towns, cfg["tiles"], zoom, thresholds, work, classify, land_uses, downloader,
                          int(cfg.get("workers", 32)))
        # 取得したタイルは都道府県ごとに消す（全国で10GBほどになるので）。土地利用の配列は残す
        shutil.rmtree(work / str(zoom), ignore_errors=True)
        progress(f"土地利用別の傾斜 {pref}: {len(towns.keys)} 地域（{time.monotonic() - started:.0f} 秒）")
    rows.sort(key=lambda r: (r[0], land_uses.index(r[1])))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["KEY_CODE", "区分", *slope.column_names(thresholds)])
    w.writerows(rows)
    outputs["towns"].parent.mkdir(parents=True, exist_ok=True)
    outputs["towns"].write_bytes(gzip.compress(buf.getvalue().encode("utf-8"), 9, mtime=0))
    return {"towns": len(rows)}
