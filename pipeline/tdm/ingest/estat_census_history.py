"""国勢調査の時系列データ「第1表 男女別人口及び人口性比 － 全国，都道府県（大正9年～令和2年）」を取り込む。

e-Stat（statInfId=000001085925）の xlsx（Strict Open XML 形式。2026-10-10 に GitHub Actions から取得して確認）。
シート「人口」の見出しの行に「地域」と「1920年」「1925年」…の列があり、各年は「総数・男・女」の3列。
地域は「01000_北海道」の形（全国は「00000_全国」、人口集中地区の行もある）。
沖縄県の1945年は調査されていないため「-」。都道府県の境界は1920年からほぼ変わっていない。
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from ..db import insert_observation
from ..regions import prefecture_entity_id
from ..xlsx import read_sheet

KIND = "estat_census_history"


def read_population(path: Path) -> dict[str, dict[int, float | None]]:
    """都道府県コード（2桁）→ 年 → 人口（総数）。"""
    rows = read_sheet(path, "人口")
    head = next(i for i, r in enumerate(rows) if r and str(r[0] or "").strip() == "地域")
    years = {j: int(m.group(1)) for j, c in enumerate(rows[head])
             if (m := re.fullmatch(r"(\d{4})年", str(c or "").strip()))}
    out: dict[str, dict[int, float | None]] = {}
    for r in rows[head + 1:]:
        m = re.fullmatch(r"(\d{2})000_[^（]+", str(r[0] if r else "").strip())
        if m is None or m.group(1) == "00":
            continue   # 全国・人口集中地区・空行
        out[m.group(1)] = {y: (r[j] if j < len(r) and isinstance(r[j], float) else None)
                           for j, y in years.items()}
    return out


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict) -> dict:
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == KIND}
    known = {r[0] for r in conn.execute("SELECT entity_id FROM entities WHERE entity_type = 'prefecture'")}
    result = {"prefectures": 0, "periods": set()}
    for pref, by_year in sorted(read_population(path).items()):
        entity_id = prefecture_entity_id(pref)
        if entity_id not in known:
            continue
        for y, v in by_year.items():
            for indicator_id, d in targets.items():
                insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                                   definition_version=d["definition_version"], period_start=f"{y}-10-01",
                                   period_end=f"{y}-10-01", period_kind="point", value=v,
                                   status="observed" if v is not None else "missing", source_id=source_id,
                                   method_note=None if v is not None else "この年は調査されていません")
            result["periods"].add(y)
        result["prefectures"] += 1
    result["periods"] = f"{min(result['periods'])}〜{max(result['periods'])}年" if result["periods"] else "なし"
    return result
