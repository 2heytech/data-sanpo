"""集計に使う町丁・字等の境界（2020年国勢調査の小地域境界、都道府県ごと）。

公開版の取込（ingest/estat_boundary.py）と同じく、同じ KEY_CODE の飛び地は1つの地域にまとめ、
水面調査区（HCODE=8154）は地域として扱わない。
KEY_CODE が市区町村コードで始まらない地物（東京都の所属未定地や青ヶ島村の岩礁にある KEY_CODE「13」など）は、
どの市区町村の町丁・字等とも決められないので使わない（そこにマスの中心がある部分は数えない）。境界のファイルは fetch.py で data/raw に取得したものを使う。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import shapefile  # pyshp
import shapely
from shapely.geometry import shape

from ..fetch import fetch_source
from ..ingest.estat_boundary import WATER_HCODE, _clean, _polygonal

BOUNDARY_KEY = "census2020_small_area_boundary"


@dataclass
class Towns:
    pref: str
    keys: list[str]               # KEY_CODE（町丁・字等の地域コード11桁など）
    geoms: list                   # shapely の図形（keys と同じ順）
    tree: shapely.STRtree
    areas: list[float] | None = None   # 境界の AREA（㎡、飛び地の合計。公開版の取込の面積と同じ）

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return tuple(shapely.total_bounds(np.array(self.geoms, dtype=object)))  # type: ignore[return-value]

    def locate(self, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
        """点が入る地域の番号（keys の添字）。どの地域にも入らない点は -1。
        境界線の上の点は、どちらか一方の地域に入れる（同じ点を2つの地域に数えない）。"""
        out = np.full(len(lon), -1, dtype=np.int64)
        if not len(lon):
            return out
        pi, gi = self.tree.query(shapely.points(lon, lat), predicate="intersects")
        first = np.unique(pi, return_index=True)[1]
        out[pi[first]] = gi[first]
        return out

    def prepare(self) -> None:
        """locate_in_box で点を調べる前に、地域の図形を調べやすくしておく（GEOS の prepared geometry）。"""
        shapely.prepare(np.array(self.geoms, dtype=object))

    def locate_in_box(self, lon: np.ndarray, lat: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
        """locate と同じ（境界線の上の点はどちらか一方の地域）。点がすべて box（西・南・東・北）の中にあるとき
        （タイルの画素の中心など）に使う。box にかかる地域ごとに、その地域の範囲の中の点だけを調べるので、
        点が多いときに locate よりずっと速い（ズーム14のタイル1枚 6万5千点で数十倍。先に prepare を呼んでおく）。
        GEOS の準備した図形を同時に使うと落ちることがあるので、いくつものスレッドから呼ばない。"""
        out = np.full(len(lon), -1, dtype=np.int64)
        area = shapely.box(*box)
        candidates = self.tree.query(area, predicate="intersects")
        if len(candidates) == 1 and shapely.contains(self.geoms[candidates[0]], area):
            out[:] = candidates[0]
            return out
        for g in candidates:
            geom = self.geoms[g]
            x0, y0, x1, y1 = geom.bounds
            sel = np.flatnonzero((out < 0) & (lon >= x0) & (lon <= x1) & (lat >= y0) & (lat <= y1))
            if len(sel):
                out[sel[shapely.intersects_xy(geom, lon[sel], lat[sel])]] = g
        return out


def read_towns(shp: Path, pref: str, encoding: str = "cp932") -> Towns:
    reader = shapefile.Reader(str(shp), encoding=encoding)
    fields = [f[0] for f in reader.fields[1:]]
    parts: dict[str, list] = {}
    areas: dict[str, float] = {}
    for sr in reader.iterShapeRecords():
        rec = dict(zip(fields, sr.record))
        if _clean(rec.get("PREF")) != pref or int(rec.get("HCODE") or 0) == WATER_HCODE:
            continue
        key = _clean(rec["KEY_CODE"])
        if not key.startswith(pref + _clean(rec.get("CITY")).zfill(3)):
            continue
        parts.setdefault(key, []).append(shape(sr.shape.__geo_interface__))
        areas[key] = areas.get(key, 0.0) + float(rec.get("AREA") or 0)
    keys = sorted(parts)
    geoms = [_polygonal(shapely.union_all(parts[k])) if len(parts[k]) > 1 else _polygonal(parts[k][0])
             for k in keys]
    return Towns(pref, keys, geoms, shapely.STRtree(geoms), [areas[k] for k in keys])


def load_towns(raw: Path, sources: dict, pref: str) -> Towns:
    """都道府県の町丁・字等の境界を（なければ e-Stat から取得して）読む。"""
    cfg = sources[BOUNDARY_KEY]
    files = fetch_source(BOUNDARY_KEY, cfg, raw / BOUNDARY_KEY, prefs=[pref])
    shp = next(f for f in files if f.suffix.lower() == ".shp")
    return read_towns(shp, pref, cfg.get("encoding", "cp932"))
