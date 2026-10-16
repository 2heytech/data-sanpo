"""農林水産省「筆ポリゴン」（農地の区画）から、町丁・字等ごとの田・畑の面積と区画の数を出す（docs/design-changes.md #124）。

筆ポリゴン公開サイト（https://open.fude.maff.go.jp/）の地図が使っている ArcGIS Online の地物サービス（prepare.toml の
service）から、区画ごとの耕地の種類（田 100・畑 200）・重心点の経度・緯度・面積だけを読む（区画の形は読まない）。
全国で約2,800万区画あり、OBJECTID の順に32,000件ずつ読む（形を含めないときの1回の上限）。
ダウンロード用のファイルのサイト（opendata.fude.maff.go.jp）は、国外のサーバーからは 403 になり取得できなかった。

区画は重心点が入る町丁・字等に数える（境界で区画を分けない。重心点がどの町丁・字等にも入らない区画は数えない）。
面積はサービスの SHAPE__Area（Web メルカトル図法の平面での面積）に cos²(緯度) を掛けて地表の面積にする
（区画は小さいので、区画の形から測った面積との差は0.1%程度）。
町丁・字等の面積は国勢調査の小地域境界の AREA（水面調査区を除く）。面積はどれも ha で書く。
"""
from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path

import numpy as np

from ..fetch import download
from ..progress import progress
from .land_use import write_counts
from .towns import Towns

PADDY, FIELD = 100, 200   # 耕地の種類（land_type）
COLUMNS = ["田", "畑", "田の区画", "畑の区画", "面積"]
PAGE = 32000
FIELDS = "OBJECTID,land_type,point_lng,point_lat,SHAPE__Area"
QUERY_RETRIES = 4


def query(service: str, params: dict, downloader=download) -> dict:
    url = f"{service}/query?" + urllib.parse.urlencode({**params, "f": "json"})
    for attempt in range(QUERY_RETRIES):
        d = json.loads(downloader(url))
        if "error" not in d:
            return d
        # 混んでいるときに「Unable to perform query」が返ることがある。間をあけてやり直す
        if attempt == QUERY_RETRIES - 1:
            raise RuntimeError(f"筆ポリゴンのサービスがエラーを返しました: {d['error']}（{url}）")
        time.sleep(10 * (attempt + 1))
    raise AssertionError("unreachable")


def _first_at(service: str, oid: int, downloader) -> tuple[int, str] | None:
    """OBJECTID が oid 以上の最初の区画の（OBJECTID, 市区町村コード）。なければ None。"""
    d = query(service, {"where": f"OBJECTID>={oid}", "outFields": "OBJECTID,local_government_cd",
                        "orderByFields": "OBJECTID", "resultRecordCount": 1, "returnGeometry": "false"}, downloader)
    f = d.get("features") or []
    return (int(f[0]["attributes"]["OBJECTID"]), f[0]["attributes"]["local_government_cd"] or "") if f else None


def _last_id(service: str, downloader) -> int:
    d = query(service, {"where": "1=1", "outFields": "OBJECTID", "orderByFields": "OBJECTID DESC",
                        "resultRecordCount": 1, "returnGeometry": "false"}, downloader)
    return int(d["features"][0]["attributes"]["OBJECTID"])


def pref_range(service: str, pref: str, last: int, downloader=download) -> tuple[int, int]:
    """都道府県の区画の OBJECTID の範囲 [始め, 終わり)。サービスの区画は市区町村コードの順に並んでいるので、
    コードが pref・その次の都道府県になる最初の OBJECTID を二分探索で探す（一部の都道府県だけで試すとき用）。"""
    def bound(code: str) -> int:
        lo, hi = 1, last + 1
        while lo < hi:
            mid = (lo + hi) // 2
            r = _first_at(service, mid, downloader)
            if r is None or r[1] >= code:
                hi = mid
            else:
                lo = r[0] + 1
        return lo
    return bound(pref), bound(f"{int(pref) + 1:02d}")


def fetch_parcels(service: str, work: Path, start: int = 1, stop: int | None = None,
                  downloader=download) -> dict[str, np.ndarray]:
    """OBJECTID が [start, stop) の区画の耕地の種類・重心点・面積（㎡）。取得したものは work に残す。"""
    cache = work / f"parcels-{start}-{stop or 'end'}.npz"
    if cache.exists():
        with np.load(cache) as z:
            return {k: z[k] for k in z.files}
    kinds, lons, lats, areas = [], [], [], []
    last, pages, n, started = start - 1, 0, 0, time.monotonic()
    while True:
        where = f"OBJECTID>{last}" + (f" AND OBJECTID<{stop}" if stop else "")
        d = query(service, {"where": where, "outFields": FIELDS, "orderByFields": "OBJECTID",
                            "resultType": "standard", "resultRecordCount": PAGE, "returnGeometry": "false"},
                  downloader)
        feats = d.get("features") or []
        if not feats:
            break
        a = [f["attributes"] for f in feats]
        kinds.append(np.array([r["land_type"] or 0 for r in a], dtype=np.int16))
        lons.append(np.array([r["point_lng"] if r["point_lng"] is not None else np.nan for r in a]))
        lats.append(np.array([r["point_lat"] if r["point_lat"] is not None else np.nan for r in a]))
        areas.append(np.array([r["SHAPE__Area"] or 0.0 for r in a]))
        last = int(a[-1]["OBJECTID"])
        pages += 1
        n += len(a)
        if pages % 50 == 0:
            progress(f"筆ポリゴン: {n:,} 区画（{time.monotonic() - started:.0f} 秒）")
        if len(a) < PAGE and not d.get("exceededTransferLimit"):
            break
    lat = np.concatenate(lats) if lats else np.zeros(0)
    out = {"kind": np.concatenate(kinds) if kinds else np.zeros(0, dtype=np.int16),
           "lon": np.concatenate(lons) if lons else np.zeros(0), "lat": lat,
           # Web メルカトルの面積 → 地表の面積
           "area": (np.concatenate(areas) if areas else np.zeros(0)) * np.cos(np.radians(lat)) ** 2}
    progress(f"筆ポリゴン: {n:,} 区画（{time.monotonic() - started:.0f} 秒）")
    work.mkdir(parents=True, exist_ok=True)
    np.savez(cache, **out)
    return out


def count_towns(towns: Towns, parcels: dict[str, np.ndarray], year: int) -> tuple[list[list], int]:
    """町丁・字等ごとの [KEY_CODE, 年度, 田, 畑（ha）, 田の区画, 畑の区画（数）, 面積（ha）] と、数えた区画の数。"""
    n = len(towns.keys)
    west, south, east, north = towns.bounds
    lon, lat, kind, area = parcels["lon"], parcels["lat"], parcels["kind"], parcels["area"]
    sel = np.flatnonzero((lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)
                         & np.isin(kind, (PADDY, FIELD)))
    idx = towns.locate(lon[sel], lat[sel])
    hit = idx >= 0
    idx, sel = idx[hit], sel[hit]
    paddy = kind[sel] == PADDY
    sums = [np.bincount(idx[m], weights=area[sel][m], minlength=n) for m in (paddy, ~paddy)]
    counts = [np.bincount(idx[m], minlength=n) for m in (paddy, ~paddy)]
    rows = [[key, year, round(float(sums[0][i]) / 1e4, 4), round(float(sums[1][i]) / 1e4, 4),
             int(counts[0][i]), int(counts[1][i]), round(towns.areas[i] / 1e4, 4)]
            for i, key in enumerate(towns.keys)]
    return rows, len(sel)


def prepare(cfg: dict, outputs: dict[str, Path], work: Path, prefs: list[str], load_towns,
            downloader=download) -> dict:
    service, year = cfg["service"], int(cfg["year"])
    if len(prefs) == 47:
        parts = [fetch_parcels(service, work, downloader=downloader)]
    else:
        last = _last_id(service, downloader)
        parts = [fetch_parcels(service, work, *pref_range(service, p, last, downloader), downloader=downloader)
                 for p in prefs]
    parcels = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    rows: list[list] = []
    counted = 0
    for pref in prefs:
        started = time.monotonic()
        towns = load_towns(pref)
        r, c = count_towns(towns, parcels, year)
        rows += r
        counted += c
        progress(f"筆ポリゴン 町丁・字等への集計 {pref}: {len(towns.keys)} 地域・{c:,} 区画"
                 f"（{time.monotonic() - started:.0f} 秒）")
    write_counts(outputs["towns"], COLUMNS, rows)
    total = int(np.isin(parcels["kind"], (PADDY, FIELD)).sum())
    return {"towns": len(rows), "parcels": total, "counted": counted}
