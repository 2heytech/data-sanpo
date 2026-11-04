"""国土交通省「全国道路・街路交通情勢調査（道路交通センサス）一般交通量調査」の箇所別基本表から、市区町村・都道府県の
幹線道路の平均交通量・大型車の割合・混雑時の平均旅行速度を取り込む（docs/design-changes.md #172）。

箇所別基本表は都道府県ごとの CSV（令和3年度は Shift_JIS、平成27年度は BOM 付き UTF-8）で、1行が1つの交通調査基本区間。
区間ごとに市区町村コード（政令指定都市は区のコード）・区間延長（km）・24時間の自動車類交通量（上下合計の大型車・合計）・
混雑時の旅行速度（上り・下り、km/h）がある。交通量は調査単位区間（いくつかの基本区間をまとめた区間）の観測値で、同じ
調査単位区間の基本区間には同じ値が入っている。列は見出しの文字で探す（年度で列の並びが違い、令和3年度は表の右端に
左端の列が繰り返される）。

- 対象は道路種別が一般国道・主要地方道（都道府県道・指定市道）・一般都道府県道の区間。国土交通省の集計表の
  「一般道路計」と同じ範囲で、高速自動車国道・都市高速道路と、指定市の一般市道（一部の路線だけが対象）は除く。
  一般国道の自動車専用の区間（バイパスなど）は含む。この範囲の都道府県の平均交通量は、集計表（「交通量推定不能区間を
  含まない」）の値と、令和3年度・平成27年度とも全都道府県で1.3%以内で一致することを確かめた（2026-10-28）。
- 市区町村の値は区間の市区町村コードでまとめる（位置から推し量らない）。都道府県の値はその都道府県の区間すべてから
  計算する（値のある区間の平均なので、値のない町村があっても都道府県の値は出す）。
- 平均交通量（台/日）: Σ(24時間交通量 × 区間延長)（台キロ）÷ Σ(値のある区間の延長)。上下線が分かれた区間（区間種別
  1・3）は1行が片方向の交通量なので延長を半分にして足し、複断面区間の側道（分離区分 3・4）は延長に足さない
  （同じ道路を2回数えないため。台キロはどちらも足す）。
- 大型車の割合（%）: Σ(大型車 × 延長) ÷ Σ(合計 × 延長) × 100。
- 混雑時の平均旅行速度（km/h）: 上り・下りの速度のある区間の Σ延長 ÷ Σ(延長 ÷ 速度)。すべての区間をその速度で
  走ったときの距離 ÷ 時間（速い区間に引っ張られる単純平均にしない）。国土交通省の集計表の都道府県の混雑時旅行速度
  とは集め方が違い、一致しない（集計表より数%〜15%ほど速く出る。令和3年度）。
- 交通量や速度の値がない区間（交通不能区間・部分供用区間など）は数えない。対象の区間はあるが値のある区間がない
  市区町村は missing、対象の区間がない市区町村は not_applicable（0 にしない）。
"""
from __future__ import annotations

import csv
import io
import sqlite3
from collections import defaultdict
from pathlib import Path

from ..db import insert_observation
from ..progress import progress
from ..regions import current_code, municipality_entity_id, prefecture_entity_id

# 平成27年度の表の古い団体コード（富谷町は2016年10月に市になった）。那珂川町→那珂川市は regions.CODE_CHANGES
OLD_CODES = {"04423": "04216"}

# 列の見出し（完全に一致するもの）
EXACT = {"code": "市区町村コード", "road": "道路種別", "length": "区間延長（ｋｍ）",
         "kind": "区間種別", "separation": "分離区間／分離区分",
         "total": "２４時間自動車類交通量（上下合計）／合計（台）",
         "large": "２４時間自動車類交通量（上下合計）／大型車（台）"}
# 一般道路（一般国道・主要地方道（都道府県道）・主要地方道（指定市道）・一般都道府県道）の道路種別
GENERAL_ROADS = ("3", "4", "5", "6")
# 混雑時の旅行速度の列: 令和3年度「朝夕（混雑時）／上り／旅行速度／合計（ｋｍ／ｈ）」、
# 平成27年度「混雑時／上り／旅行速度（ｋｍ／ｈ）」。前回の調査の値・車種別・昼間（非混雑時）の列は除く
SPEED_EXCLUDE = ("非混雑", "平成", "小型", "大型", "１２時間")


def _text(path: Path) -> str:
    data = path.read_bytes()
    return data.decode("utf-8-sig") if data.startswith(b"\xef\xbb\xbf") else data.decode("cp932")


def _columns(head: list[str]) -> dict[str, int]:
    first: dict[str, int] = {}
    for i, h in enumerate(head):
        first.setdefault(h.strip(), i)   # 右端に繰り返される列は左のものを使う
    cols = {}
    for key, name in EXACT.items():
        if name not in first:
            raise ValueError(f"道路交通センサスの表に列「{name}」がありません。見出し: {list(first)[:40]}")
        cols[key] = first[name]
    for key, direction in (("speed_up", "上り"), ("speed_down", "下り")):
        found = [i for h, i in first.items()
                 if all(w in h for w in ("混雑時", direction, "旅行速度", "ｋｍ／ｈ"))
                 and not any(w in h for w in SPEED_EXCLUDE)]
        if len(found) != 1:
            raise ValueError(f"道路交通センサスの表で混雑時の旅行速度（{direction}）の列が1つに決まりません: "
                             f"{[h for h, i in first.items() if i in found]}")
        cols[key] = found[0]
    return cols


def _num(row: list[str], col: int) -> float | None:
    s = row[col].strip().replace(",", "") if col < len(row) else ""
    try:
        return float(s) if s else None
    except ValueError:
        return None


def read_sections(path: Path) -> list[dict]:
    """一般道路（GENERAL_ROADS）の区間。値のない項目は None。"""
    rows = list(csv.reader(io.StringIO(_text(path))))
    if not rows:
        return []
    cols = _columns(rows[0])
    out = []
    for row in rows[1:]:
        if not row or not row[0].strip() or row[cols["road"]].strip() not in GENERAL_ROADS:
            continue
        code = row[cols["code"]].strip().zfill(5)
        out.append({
            "code": current_code(OLD_CODES.get(code, code)),
            "length": _num(row, cols["length"]) or 0.0,
            "kind": row[cols["kind"]].strip(), "separation": row[cols["separation"]].strip(),
            "total": _num(row, cols["total"]), "large": _num(row, cols["large"]),
            "speeds": [v for v in (_num(row, cols["speed_up"]), _num(row, cols["speed_down"])) if v and v > 0],
        })
    return out


def road_length_weight(kind: str, separation: str) -> float:
    """平均交通量の分母に足す延長の割合。上下線分離は片方向ずつの行なので半分、複断面の側道は本線と同じ道路なので0。"""
    if separation in ("3", "4"):
        return 0.0
    return 0.5 if kind in ("1", "3") else 1.0


def summarize(sections: list[dict]) -> dict[str, float]:
    """区間の合計（平均交通量・大型車の割合・旅行速度の分子と分母）。"""
    s = defaultdict(float)
    for x in sections:
        s["sections"] += 1
        ln = x["length"]
        if x["total"] is not None:
            s["vehicle_km"] += x["total"] * ln
            s["road_km"] += ln * road_length_weight(x["kind"], x["separation"])
            if x["large"] is not None:
                s["large_km"] += x["large"] * ln
                s["mixed_km"] += x["total"] * ln
        for v in x["speeds"]:
            s["drive_km"] += ln
            s["drive_hours"] += ln / v
    return s


# 指標の road_census_value → (分子, 分母, 値のある区間の説明)
VALUES = {"traffic_volume": ("vehicle_km", "road_km", "交通量"),
          "large_share": ("large_km", "mixed_km", "交通量"),
          "congested_speed": ("drive_km", "drive_hours", "混雑時の旅行速度")}


def _put(conn, d: dict, indicator_id: str, entity_id: str, s: dict, period, source_id: str) -> None:
    num_key, den_key, what = VALUES[d["road_census_value"]]
    obs = dict(entity_id=entity_id, indicator_id=indicator_id, definition_version=d["definition_version"],
               period_start=period[0], period_end=period[1], period_kind=period[2], source_id=source_id,
               denominator_source_id=source_id)
    if not s.get("sections"):
        insert_observation(conn, value=None, status="not_applicable",
                           method_note="調査の対象の道路（高速道路を除く国道・都道府県道）がないため値なし", **obs)
    elif not s.get(den_key):
        insert_observation(conn, value=None, status="missing",
                           method_note=f"{what}の値がある区間がないため値なし", **obs)
    else:
        insert_observation(conn, value=s[num_key] / s[den_key] * d.get("scale", 1), status="derived",
                           numerator=round(s[num_key], 4), denominator=round(s[den_key], 4), **obs)


def ingest(conn: sqlite3.Connection, files_by_pref: dict[str, list[Path]], source_id: str, catalog: dict,
           fiscal_year: int) -> dict:
    """files_by_pref: 都道府県コード → その都道府県の箇所別基本表（kasyoNN.csv）。"""
    period = (f"{fiscal_year}-04-01", f"{fiscal_year + 1}-03-31", "fiscal_year")
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "mlit_road_census"}
    munis_of: dict[str, list[str]] = defaultdict(list)
    for r in conn.execute("SELECT entity_id FROM entities WHERE entity_type = 'municipality'"):
        munis_of[r[0][5:7]].append(r[0])
    result = {"municipalities": 0, "no_value": 0, "prefectures": 0, "sections": 0, "unmatched": []}
    for pref, files in sorted(files_by_pref.items()):
        sections = [x for f in files for x in read_sections(f)]
        result["sections"] += len(sections)
        by_muni: dict[str, list[dict]] = defaultdict(list)
        for x in sections:
            by_muni[municipality_entity_id(x["code"])].append(x)
        unmatched = sorted(set(by_muni) - set(munis_of[pref]))
        result["unmatched"] += unmatched
        sums = {m: summarize(by_muni.get(m, [])) for m in munis_of[pref]}
        whole = summarize([x for m, xs in by_muni.items() if m not in unmatched for x in xs])
        for indicator_id, d in targets.items():
            for m, s in sums.items():
                _put(conn, d, indicator_id, m, s, period, source_id)
            if whole.get("sections"):
                _put(conn, d, indicator_id, prefecture_entity_id(pref), whole, period, source_id)
        result["municipalities"] += sum(1 for s in sums.values() if s.get("road_km"))
        result["no_value"] += sum(1 for s in sums.values() if not s.get("road_km"))
        result["prefectures"] += 1 if whole.get("sections") else 0
    if result["unmatched"]:
        progress(f"  道路交通センサス {fiscal_year}年度: 地図にない市区町村コード {result['unmatched'][:20]}")
    result["unmatched"] = result["unmatched"][:30]
    return result
