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


def read_towns(shp: Path, pref: str, encoding: str = "cp932") -> Towns:
    reader = shapefile.Reader(str(shp), encoding=encoding)
    fields = [f[0] for f in reader.fields[1:]]
    parts: dict[str, list] = {}
    for sr in reader.iterShapeRecords():
        rec = dict(zip(fields, sr.record))
        if _clean(rec.get("PREF")) != pref or int(rec.get("HCODE") or 0) == WATER_HCODE:
            continue
        key = _clean(rec["KEY_CODE"])
        if not key.startswith(pref + _clean(rec.get("CITY")).zfill(3)):
            continue
        parts.setdefault(key, []).append(shape(sr.shape.__geo_interface__))
    keys = sorted(parts)
    geoms = [_polygonal(shapely.union_all(parts[k])) if len(parts[k]) > 1 else _polygonal(parts[k][0])
             for k in keys]
    return Towns(pref, keys, geoms, shapely.STRtree(geoms))


def load_towns(raw: Path, sources: dict, pref: str) -> Towns:
    """都道府県の町丁・字等の境界を（なければ e-Stat から取得して）読む。"""
    cfg = sources[BOUNDARY_KEY]
    files = fetch_source(BOUNDARY_KEY, cfg, raw / BOUNDARY_KEY, prefs=[pref])
    shp = next(f for f in files if f.suffix.lower() == ".shp")
    return read_towns(shp, pref, cfg.get("encoding", "cp932"))
