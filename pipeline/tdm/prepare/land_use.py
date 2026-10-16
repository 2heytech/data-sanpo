"""国土数値情報「土地利用細分メッシュ」「都市地域土地利用細分メッシュ」（100m）を町丁・字等ごとのマスの数にまとめ、
地図に重ねる土地利用図の画像を作る（docs/design-changes.md #123）。

元データ（1次メッシュごとの ZIP。中の DBF にメッシュコードと土地利用の区分がある）を年度ごとに取得し、
1次メッシュの800×800の配列にしてから使う。区分のコードは年度で違う（コードリスト LandUseCd-77・88・YY・09）ので、
共通の区分（LAND_USE）に読み替える。昭和51年度の果樹園・その他の樹木畑は「畑など（その他の農用地）」に、
建物用地A・B は「建物用地」に、河川地A・B・湖沼は「河川・湖沼」に入れる。
平成18年度にある区分「0」（コードリストにない）は分類のないマスとして「データなし」に数える。
1次メッシュの中でレコードのない2次メッシュは海だけの範囲（東京湾の 5339-27 など）なので、海として扱う。

町丁・字等への集計: マスの中心が入る町丁・字等に、そのマスを丸ごと数える（マスを境界で分けない。元データより
細かく割り振らないため）。中心がどの町丁・字等にも入らないマス（海・水面調査区など）は数えない。
その年度のデータがない1次メッシュ（昭和51年度の北方領土など）に入る部分は、令和3年度のマスで数えて「データなし」にする。

都市地域土地利用細分メッシュ（令和3年度）は都市地域の中だけのデータで、令和3年度の土地利用細分メッシュと同じマス。
陸のマスのうち都市地域のデータがないマスを「都市地域の範囲外」に数える。

土地利用図: 年度ごとに Web メルカトルのタイル（ズーム5は1024画素、ズーム7は2048画素）にする。1画素には中心が入る
マスの区分のうち最も多いものを塗り（同数なら陸の区分）、海・データなしは透明にする。
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import shapely

from ..fetch import download
from ..progress import progress
from .mesh import (CELLS, cell_centers, first_mesh_origin, jgd_to_tokyo, mesh_grid, tokyo_to_jgd)
from .towns import Towns

# 共通の区分（配列の値は 番号+1。0 はレコードのないマス）。海と分類なしは町丁・字等の値に使わない
LAND_USE = ["田", "畑など", "森林", "荒地", "建物用地", "道路・鉄道", "その他の用地", "河川・湖沼", "海浜", "ゴルフ場"]
SEA = len(LAND_USE) + 1
UNCLASSIFIED = 255
COLORS = ["#f2dc6b", "#f0a85a", "#3f8f4e", "#c4bf86", "#e2574c", "#8e8e8e", "#b08bd9", "#5aa7e3", "#efdfb0", "#a8d86e"]

_L = {name: i + 1 for i, name in enumerate(LAND_USE)}
_YY = {b"1": _L["田"], b"2": _L["畑など"], b"5": _L["森林"], b"6": _L["荒地"], b"7": _L["建物用地"],
       b"9": _L["道路・鉄道"], b"A": _L["その他の用地"], b"B": _L["河川・湖沼"], b"E": _L["海浜"], b"F": SEA,
       b"G": _L["ゴルフ場"], b"0": UNCLASSIFIED}
CODE_TABLES: dict[str, dict[bytes, int]] = {
    # 昭和51年度（LandUseCd-77）
    "77": {b"1": _L["田"], b"2": _L["畑など"], b"3": _L["畑など"], b"4": _L["畑など"], b"5": _L["森林"],
           b"6": _L["荒地"], b"7": _L["建物用地"], b"8": _L["建物用地"], b"9": _L["道路・鉄道"],
           b"A": _L["その他の用地"], b"B": _L["河川・湖沼"], b"C": _L["河川・湖沼"], b"D": _L["河川・湖沼"],
           b"E": _L["海浜"], b"F": SEA},
    # 昭和62年度（LandUseCd-88）
    "88": {b"1": _L["田"], b"2": _L["畑など"], b"3": _L["畑など"], b"4": _L["畑など"], b"5": _L["森林"],
           b"6": _L["荒地"], b"7": _L["建物用地"], b"9": _L["道路・鉄道"], b"A": _L["その他の用地"],
           b"B": _L["河川・湖沼"], b"E": _L["海浜"], b"F": SEA},
    # 平成3・9・18年度（LandUseCd-YY）
    "YY": _YY,
    # 平成21年度以降（LandUseCd-09）
    "09": {b"0100": _L["田"], b"0200": _L["畑など"], b"0500": _L["森林"], b"0600": _L["荒地"],
           b"0700": _L["建物用地"], b"0901": _L["道路・鉄道"], b"0902": _L["道路・鉄道"],
           b"1000": _L["その他の用地"], b"1100": _L["河川・湖沼"], b"1400": _L["海浜"], b"1500": SEA,
           b"1600": _L["ゴルフ場"]},
}
NO_DATA = "データなし"

# 都市地域土地利用細分メッシュ（令和3年度、LandUseCd 都市地域の17区分）
URBAN = ["田", "畑など", "森林", "荒地", "高層建物", "工場", "低層建物", "低層建物（密集地）", "道路", "鉄道",
         "公共施設等用地", "空地", "公園・緑地", "河川・湖沼", "海浜", "ゴルフ場"]
URBAN_SEA = len(URBAN) + 1
_U = {name: i + 1 for i, name in enumerate(URBAN)}
URBAN_CODES = {b"0100": _U["田"], b"0200": _U["畑など"], b"0500": _U["森林"], b"0600": _U["荒地"],
               b"0701": _U["高層建物"], b"0702": _U["工場"], b"0703": _U["低層建物"],
               b"0704": _U["低層建物（密集地）"], b"0901": _U["道路"], b"0902": _U["鉄道"],
               b"1001": _U["公共施設等用地"], b"1002": _U["空地"], b"1003": _U["公園・緑地"],
               b"1100": _U["河川・湖沼"], b"1400": _U["海浜"], b"1500": URBAN_SEA, b"1600": _U["ゴルフ場"]}
OUTSIDE = "都市地域の範囲外"

TILE_SIZES = {5: 1024, 7: 2048}
DOWNLOAD_WORKERS = 4


def listed_meshes(page_url: str, url_template: str, downloader=download) -> list[str]:
    """データの一覧のページにある、その年度の1次メッシュのコード。"""
    html = downloader(page_url).decode("utf-8", errors="replace")
    name = re.escape(url_template.rsplit("/", 1)[1]).replace(re.escape("{mesh}"), r"(\d{4})")
    meshes = sorted(set(re.findall(name, html)))
    if not meshes:
        raise RuntimeError(f"{page_url} に {url_template} の1次メッシュが見つかりません")
    return meshes


def _grid_from_zip(data: bytes, mesh: str, codes: dict[bytes, int]) -> np.ndarray:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        dbf = [n for n in z.namelist() if n.lower().endswith(".dbf")]
        if len(dbf) != 1:
            raise RuntimeError(f"{mesh}: ZIP の中の DBF が {len(dbf)} 個です")
        return mesh_grid(z.read(dbf[0]), dbf[0], codes, mesh)


def load_grids(work: Path, label: str, url_template: str, meshes: list[str], codes: dict[bytes, int],
               downloader=download) -> dict[str, np.ndarray]:
    """1次メッシュごとの区分の配列。作った配列は work に残し、やり直したときに取り直さない。"""
    work.mkdir(parents=True, exist_ok=True)

    def one(mesh: str) -> tuple[str, np.ndarray]:
        cached = work / f"{mesh}.npy"
        if cached.exists():
            return mesh, np.load(cached)
        url = url_template.replace("{mesh}", mesh)
        for attempt in range(3):
            try:
                grid = _grid_from_zip(downloader(url), mesh, codes)
                break
            except (OSError, zipfile.BadZipFile) as e:
                if attempt == 2:
                    raise RuntimeError(f"{url}: 取得できません（{e}）") from e
                time.sleep(10 * (attempt + 1))
        np.save(cached, grid)
        return mesh, grid

    started = time.monotonic()
    out: dict[str, np.ndarray] = {}
    with ThreadPoolExecutor(DOWNLOAD_WORKERS) as pool:
        for i, (mesh, grid) in enumerate(pool.map(one, meshes), 1):
            out[mesh] = grid
            if i % 20 == 0 or i == len(meshes):
                progress(f"{label}: {i}/{len(meshes)} の1次メッシュ（{time.monotonic() - started:.0f} 秒）")
    return out


def _mesh_cells(mesh: str, grid: np.ndarray, mask: np.ndarray, datum: str):
    """配列の mask のマスの、中心の経度・緯度（世界測地系）と配列の中の位置。"""
    r, c = np.nonzero(mask)
    row0, col0 = first_mesh_origin(mesh)
    lon, lat = cell_centers(row0 + r, col0 + c)
    if datum == "tokyo":
        lon, lat = tokyo_to_jgd(lon, lat)
    return lon, lat, r, c


def _mesh_box(mesh: str, datum: str, margin: float = 0.0) -> tuple[float, float, float, float]:
    """1次メッシュの範囲（世界測地系の経度・緯度）。日本測地系のメッシュは換算した位置の範囲。"""
    row0, col0 = first_mesh_origin(mesh)
    west, south = 100 + col0 / 800, row0 / 1200
    east, north = west + 1.0, south + 2 / 3
    if datum == "tokyo":
        lons, lats = tokyo_to_jgd(np.array([west, east, west, east]), np.array([south, south, north, north]))
        west, east, south, north = lons.min(), lons.max(), lats.min(), lats.max()
    return west - margin, south - margin, east + margin, north + margin


def towns_in(towns: Towns, mesh: str, datum: str = "jgd") -> bool:
    """1次メッシュの範囲にかかる町丁・字等があるか。"""
    return len(towns.tree.query(shapely.box(*_mesh_box(mesh, datum, 0.01)))) > 0


def count_towns(towns: Towns, years: list[dict], grids: dict[int, dict[str, np.ndarray]],
                urban: dict[str, np.ndarray] | None) -> tuple[list[list], list[list]]:
    """1つの都道府県の町丁・字等ごとの区分別のマスの数（年度ごとの行、都市地域の行）。
    years の最後の年度（令和3年度）を基準にして、ほかの年度のデータがない部分を数える。"""
    n = len(towns.keys)
    k = len(LAND_USE) + 1   # 区分 + データなし
    uk = len(URBAN) + 1    # 都市地域の区分 + 範囲外
    latest = years[-1]
    rows_out: list[list] = []
    urban_out: list[list] = []
    base_points = None   # 基準の年度の陸のマスの中心と町丁・字等（データのない1次メッシュの部分を数えるため）
    for y in sorted(years, key=lambda y: y is not latest):   # 基準の年度を先に数える
        year, datum = y["year"], y.get("datum", "jgd")
        counts = np.zeros(n * k, dtype=np.int64)
        ucounts = np.zeros(n * uk, dtype=np.int64)
        base_lon, base_lat, base_idx = [], [], []
        for mesh, grid in grids[year].items():
            if not towns_in(towns, mesh, datum):
                continue
            ugrid = urban.get(mesh) if (urban is not None and y is latest) else None
            land = (grid > 0) & (grid != SEA)
            if ugrid is not None:
                land |= (ugrid > 0) & (ugrid != URBAN_SEA)
            lon, lat, r, c = _mesh_cells(mesh, grid, land, datum)
            idx = towns.locate(lon, lat)
            ok = idx >= 0
            cats = grid[r, c][ok].astype(np.int64)
            idx_ok = idx[ok]
            keep = (cats > 0) & (cats != SEA)
            cats = np.where(cats == UNCLASSIFIED, k - 1, cats - 1)
            counts += np.bincount(idx_ok[keep] * k + cats[keep], minlength=n * k)
            if y is latest:
                base_lon.append(lon[ok][keep])
                base_lat.append(lat[ok][keep])
                base_idx.append(idx_ok[keep])
            if ugrid is not None:
                ucats = ugrid[r, c][ok].astype(np.int64)
                land_u = (ucats > 0) & (ucats != URBAN_SEA)
                # 土地利用細分メッシュでは陸なのに、都市地域のデータがないマス → 範囲外
                outside = (ucats == 0) & keep
                code = np.where(land_u, ucats - 1, uk - 1)
                sel = land_u | outside
                ucounts += np.bincount(idx_ok[sel] * uk + code[sel], minlength=n * uk)
        if y is latest:
            base_points = (np.concatenate(base_lon) if base_lon else np.zeros(0),
                           np.concatenate(base_lat) if base_lat else np.zeros(0),
                           np.concatenate(base_idx) if base_idx else np.zeros(0, dtype=np.int64))
        else:
            counts += _missing_mesh_cells(base_points, set(grids[year]), datum, n, k)
        counts = counts.reshape(n, k)
        for i, key in enumerate(towns.keys):
            rows_out.append([key, year, *counts[i].tolist()])
        if urban is not None and y is latest:
            uc = ucounts.reshape(n, uk)
            for i, key in enumerate(towns.keys):
                urban_out.append([key, year, *uc[i, :len(URBAN)].tolist(), int(uc[i, -1])])
    rows_out.sort(key=lambda r: (r[0], r[1]))
    return rows_out, urban_out


def _missing_mesh_cells(base_points, have: set[str], datum: str, n: int, k: int) -> np.ndarray:
    """その年度のデータがない1次メッシュに入る、基準の年度の陸のマスの数（町丁・字等ごと）→ データなしの列。"""
    out = np.zeros(n * k, dtype=np.int64)
    lon, lat, idx = base_points
    if not len(lon):
        return out
    if datum == "tokyo":
        lon, lat = jgd_to_tokyo(lon, lat)
    meshes = np.char.add(np.char.zfill(((lat * 1.5).astype(np.int64)).astype(str), 2),
                         np.char.zfill(((lon - 100).astype(np.int64)).astype(str), 2))
    missing = ~np.isin(meshes, np.array(sorted(have)))
    out += np.bincount(idx[missing] * k + (k - 1), minlength=n * k)
    return out


def write_counts(path: Path, columns: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["KEY_CODE", "年度", *columns])
    w.writerows(rows)
    # 同じ内容なら同じファイルになるよう、圧縮の時刻を入れない
    path.write_bytes(gzip.compress(buf.getvalue().encode("utf-8"), 9, mtime=0))


# --- 土地利用図のタイル --------------------------------------------------------------------

def _mercator(lon: np.ndarray, lat: np.ndarray, zoom: int, size: int) -> tuple[np.ndarray, np.ndarray]:
    scale = (2 ** zoom) * size
    x = (lon + 180) / 360 * scale
    y = (1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2 * scale
    return x, y


def _tile_range(box, zoom: int) -> tuple[range, range]:
    size = 1
    x0, y1 = _mercator(np.array([box[0]]), np.array([box[1]]), zoom, size)
    x1, y0 = _mercator(np.array([box[2]]), np.array([box[3]]), zoom, size)
    return range(int(x0[0]), int(x1[0]) + 1), range(int(y0[0]), int(y1[0]) + 1)


def render_tiles(grids: dict[str, np.ndarray], datum: str, zoom: int, size: int) -> dict[tuple[int, int], np.ndarray]:
    """年度の土地利用図のタイル（(x, y) → 区分の番号の画像。0 は透明）。"""
    by_tile: dict[tuple[int, int], list[str]] = {}
    for mesh in grids:
        xs, ys = _tile_range(_mesh_box(mesh, datum), zoom)
        for x in xs:
            for y in ys:
                by_tile.setdefault((x, y), []).append(mesh)
    k = len(LAND_USE) + 1   # 0: 透明（海・分類なし）、1〜: 陸の区分
    out = {}
    for (tx, ty), meshes in sorted(by_tile.items()):
        acc = np.zeros(size * size * k, dtype=np.int32)
        for mesh in meshes:
            grid = grids[mesh]
            lon, lat, r, c = _mesh_cells(mesh, grid, grid > 0, datum)
            px, py = _mercator(lon, lat, zoom, size)
            px = np.floor(px).astype(np.int64) - tx * size
            py = np.floor(py).astype(np.int64) - ty * size
            inside = (px >= 0) & (px < size) & (py >= 0) & (py < size)
            cats = grid[r, c][inside].astype(np.int64)
            cats = np.where((cats == SEA) | (cats == UNCLASSIFIED), 0, cats)
            acc += np.bincount((py[inside] * size + px[inside]) * k + cats, minlength=size * size * k).astype(np.int32)
        acc = acc.reshape(size * size, k)
        land = acc[:, 1:]
        best = land.argmax(axis=1) + 1
        best_n = land.max(axis=1)
        img = np.where((best_n > 0) & (best_n >= acc[:, 0]), best, 0).astype(np.uint8).reshape(size, size)
        if img.any():
            out[(tx, ty)] = img
    return out


def png_bytes(img: np.ndarray) -> bytes:
    from PIL import Image   # 準備の処理だけで使う（公開版の取込には要らない）
    im = Image.fromarray(img, mode="P")
    palette = [0, 0, 0]
    for color in COLORS:
        palette += [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    im.putpalette(palette)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True, transparency=0)
    return buf.getvalue()


def write_tiles(path: Path, years: list[dict], grids: dict[int, dict[str, np.ndarray]]) -> dict:
    """土地利用図のタイル一式を ZIP にする（年度/ズーム/x/y.png と、一覧の tiles.json）。"""
    index: dict = {"years": [], "zooms": {str(z): s for z, s in TILE_SIZES.items()},
                   "legend": [{"id": i + 1, "name": name, "color": COLORS[i]} for i, name in enumerate(LAND_USE)]}
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        for y in years:
            year = y["year"]
            listed: dict[str, list[str]] = {}
            for zoom, size in TILE_SIZES.items():
                started = time.monotonic()
                tiles = render_tiles(grids[year], y.get("datum", "jgd"), zoom, size)
                for (tx, ty), img in sorted(tiles.items()):
                    # 同じ内容なら同じ ZIP になるよう、ファイルの日時を固定する
                    info = zipfile.ZipInfo(f"{year}/{zoom}/{tx}/{ty}.png", date_time=(2020, 1, 1, 0, 0, 0))
                    z.writestr(info, png_bytes(img))
                listed[str(zoom)] = [f"{tx}/{ty}" for tx, ty in sorted(tiles)]
                progress(f"土地利用図 {year}年度 ズーム{zoom}: {len(tiles)} 枚（{time.monotonic() - started:.0f} 秒）")
            index["years"].append({"year": year, "label": y["label"], "tiles": listed})
        info = zipfile.ZipInfo("tiles.json", date_time=(2020, 1, 1, 0, 0, 0))
        z.writestr(info, json.dumps(index, ensure_ascii=False, separators=(",", ":")))
    return index


def prepare(cfg: dict, outputs: dict[str, Path], work: Path, prefs: list[str], load_towns,
            downloader=download) -> dict:
    """outputs: towns（町丁・字等ごとの年度別のマスの数）・urban（都市地域）・tiles（土地利用図）の書き出し先。"""
    years = sorted(cfg["years"], key=lambda y: y["year"])
    # 一部の都道府県だけで試すときは、その都道府県にかかる1次メッシュだけを取得する（土地利用図もその範囲だけになる）
    wanted = None
    if len(prefs) < 47:
        all_towns = [load_towns(p) for p in prefs]
        wanted = lambda mesh: any(towns_in(t, mesh) for t in all_towns)  # noqa: E731
    grids: dict[int, dict[str, np.ndarray]] = {}
    for y in years:
        meshes = [m for m in listed_meshes(cfg["mesh_list"], y["url"], downloader) if not wanted or wanted(m)]
        grids[y["year"]] = load_grids(work / str(y["year"]), f"土地利用 {y['year']}年度", y["url"], meshes,
                                      CODE_TABLES[y["codes"]], downloader)
    urban_meshes = [m for m in listed_meshes(cfg["urban_mesh_list"], cfg["urban_url"], downloader)
                    if not wanted or wanted(m)]
    urban = load_grids(work / "urban", "都市地域の土地利用", cfg["urban_url"], urban_meshes, URBAN_CODES, downloader)
    result: dict = {}
    if "tiles" in outputs:
        index = write_tiles(outputs["tiles"], years, grids)
        result["tiles"] = {y["year"]: {z: len(t) for z, t in y["tiles"].items()} for y in index["years"]}
    rows: list[list] = []
    urban_rows: list[list] = []
    for pref in prefs:
        started = time.monotonic()
        towns = load_towns(pref)
        r, u = count_towns(towns, years, grids, urban)
        rows += r
        urban_rows += u
        progress(f"町丁・字等への集計 {pref}: {len(towns.keys)} 地域（{time.monotonic() - started:.0f} 秒）")
    write_counts(outputs["towns"], [*LAND_USE, NO_DATA], rows)
    write_counts(outputs["urban"], [*URBAN, OUTSIDE], urban_rows)
    result.update(towns=len(rows), urban=len(urban_rows))
    print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
    return result
