"""東京都建設局「都道の街路樹」（23区・多摩、1本ごとの位置と樹種）を町丁目・区市町村ごとに数える。

形式（tokyo_gairoju.csv を 2026-10-03 に GitHub Actions から取得して確認）: Shift_JIS（cp932）の CSV、
1行目が列名「樹種,区分,樹高(m),枝張(m),幹周(cm）,行政区,種別,整理番号,路線名,通称道路名,経度,緯度」。
1行が1本（高木・中木）。23区分は約14万本、樹種は約400種類。経度・緯度は世界測地系の度。
多摩分（tokyo_tama_gairoju.csv）は UTF-8（BOM つき）で、列名が英語「name,type,height,perimeter,width,route,
route_name,route_nickname,route_type,longitude,latitude」。BOM があれば UTF-8 として読み、列名はどちらにも対応する。

都道の街路樹だけで、区市町村道・国道の街路樹は含まない。木の位置を最新の境界に重ねて数えるので、
集計は元データより粗くなる（細かく割り振らない原則に沿う）。都道の街路樹がない町丁目は 0 本とする
（都道がない・木がないのどちらか。色は塗らない）。
指標（definition の tree_match）: 樹種名にいずれかの文字列を含む木を数える。"*" はすべての木。
tree_value = "species" は樹種の数。総数の指標には、最も多い樹種を各地域の注記に入れる。
"""
from __future__ import annotations

import csv
import io
import sqlite3
from collections import Counter
from pathlib import Path

from shapely.geometry import Point

from ..db import insert_observation
from .npa_traffic import _Index


COLUMNS = {"species": ("樹種", "name"), "lon": ("経度", "longitude"), "lat": ("緯度", "latitude")}


def read_trees(path: Path, encoding: str = "cp932") -> list[tuple[str, float, float]]:
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    reader = csv.DictReader(io.StringIO(data.decode(encoding, errors="replace")))
    reader.fieldnames = [f.strip() for f in reader.fieldnames or []]
    col = {k: next(n for n in names if n in reader.fieldnames) for k, names in COLUMNS.items()}
    out = []
    for r in reader:
        try:
            lon, lat = float(r[col["lon"]]), float(r[col["lat"]])
        except (TypeError, ValueError):
            continue
        out.append(((r.get(col["species"]) or "").strip(), lon, lat))
    return out


ISLANDS_FROM = "13360"   # 島しょの町村（大島町 13361 〜 小笠原村 13421）


def _matches(species: str, match: list[str]) -> bool:
    return "*" in match or any(m in species for m in match)


def ingest(conn: sqlite3.Connection, files: list[tuple[str, Path, str]], catalog: dict,
           period: tuple[str, str, str], boundary_version: str) -> dict:
    """files: (出典ID, パス, 文字コード)。出典ごとの区市町村の範囲（区部・多摩）は地域コードで分ける。"""
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "tokyo_street_trees"}
    # 都道の街路樹は東京都だけ。ほかの道府県の地域を0本にしない（全国の境界を取り込んだときに0本が入っていた）
    areas = _Index(conn, boundary_version, "small_area", ["13"])
    munis = _Index(conn, boundary_version, "municipality", ["13"])
    species: dict[str, Counter] = {}
    result: dict = {"trees": 0, "outside": 0, "no_location": 0}
    sources = []
    for source_id, path, encoding in files:
        trees = read_trees(path, encoding)
        sources.append(source_id)
        for name, lon, lat in trees:
            point = Point(lon, lat)
            places = [p for p in (areas.locate(point), munis.locate(point)) if p]
            if not places:
                result["outside"] += 1
                continue
            for p in places:
                species.setdefault(p, Counter())[name] += 1
            result["trees"] += 1
    # 区部（131xx）は23区のファイル、それ以外は多摩のファイルを出典にする（ファイルの順に指定）
    ku, tama = sources[0], sources[-1]

    def source_of(entity_id: str) -> str:
        code = entity_id.split("-", 1)[1]
        return ku if code.startswith("131") else tama

    for entity_id in areas.ids + munis.ids:
        c = species.get(entity_id, Counter())
        covered = entity_id.split("-", 1)[1][:5] < ISLANDS_FROM
        for indicator_id, d in targets.items():
            if not covered:   # 島しょはどちらのファイルにも含まれない（0本ではなく値なし）
                insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                                   definition_version=d["definition_version"], period_start=period[0],
                                   period_end=period[1], period_kind=period[2], value=None,
                                   status="missing", source_id=source_of(entity_id))
                continue
            if d.get("tree_value") == "species":
                value = float(len(c))
            else:
                value = float(sum(n for s, n in c.items() if _matches(s, d["tree_match"])))
            note = None
            if d.get("tree_match") == ["*"] and c:
                top, n = c.most_common(1)[0]
                note = f"最も多い樹種: {top}（{n:,}本）"
            insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                               definition_version=d["definition_version"], period_start=period[0],
                               period_end=period[1], period_kind=period[2], value=value,
                               status="observed", source_id=source_of(entity_id), method_note=note)
    return result
