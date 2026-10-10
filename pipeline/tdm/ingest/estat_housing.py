"""住宅・土地統計調査（総務省統計局、各回10月1日現在）の市区町村別の表を取り込む。

e-Stat の基本集計「全国、都道府県、市区町村」の xlsx（2026-10-10 に GitHub Actions から取得して確認）。
どの表も全国で1ファイル・1シートで、全国・都道府県・市区町村の行が並ぶ。地域は「13101_千代田区」の形
（5桁の市区町村コード＋名前）。都道府県は「13000_東京都」、政令指定都市の市全体は「01100_札幌市」。
市区町村は「市、区及び人口1万5千人以上の町村」だけが載る（それより小さい町村の行はない）。
「-」は「該当なし又は数字が得られないもの」。

収入（kind = estat_housing_income）
  令和5年 第43-4表「世帯の年間収入階級(10区分)、住宅の所有の関係(5区分)別主世帯数…」: 縦長で、1行が
  「地域・所有の関係・収入階級」の組み合わせ（例: 13101_千代田区 / 0_総数 / 01_100万円未満 / 主世帯数）。
  平成30年 第44-4表「世帯の年間収入階級(9区分)，世帯の種類(2区分)，住宅の所有の関係(5区分)別普通世帯数…」:
  先頭に行番号などの列があり、「世帯の種類」（1_主世帯 / 2_同居世帯・住宅以外…）の列が加わる。
  収入階級の区切りは年で違う（令和5年は100〜150・150〜200万円、平成30年は100〜200万円）が、
  300万円・1000万円の境目はどちらにもある。収入階級の「総数」には収入不詳を含むので、割合の分母は
  収入階級ごとの世帯数の合計（収入が分かる世帯）とする。

住宅数（kind = estat_housing_stock）
  第1-2表「居住世帯の有無(8区分)別住宅数…」: 横長で、見出しの1行に「0_総数」「22_空き家」などの列名がある。
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from ..db import insert_observation
from ..regions import municipality_entity_id, prefecture_entity_id
from ..xlsx import read_sheet, sheet_names

INCOME_KIND = "estat_housing_income"
STOCK_KIND = "estat_housing_stock"
AREA = re.compile(r"^(\d{5})_")
LABEL = re.compile(r"^\d+_\S")
NOT_PUBLISHED = "この市区町村の値は公表されていません（人口1万5千人未満の町村は調査結果の公表の対象外）"


def _number(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "…", "x", "X", "***"):
        return None
    if s == "-":
        return 0.0   # 該当なし。合計の行（総数）が「-」なら下で値なしにする
    return float(s)


def _income_range(label: str) -> tuple[float, float] | None:
    """「02_100～150万円未満」→ (100, 150)、「11_1500万円以上」→ (1500, inf)、総数は None（万円）。"""
    text = label.split("_", 1)[1]
    if "総数" in text:
        return None
    nums = [float(x) for x in re.findall(r"\d+", text)]
    if "以上" in text:
        return (nums[0], float("inf"))
    return (0.0, nums[0]) if len(nums) == 1 else (nums[0], nums[1])


def _entity(known: set[str], code: str) -> str | None:
    entity_id = prefecture_entity_id(code[:2]) if code.endswith("000") else municipality_entity_id(code)
    return entity_id if entity_id in known else None


def _known(conn) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT entity_id FROM entities WHERE entity_type IN ('prefecture', 'municipality')")}


def _write_missing_towns(conn, known: set[str], written: set[str], targets: dict, source_id: str,
                         period: tuple[str, str, str]) -> int:
    """表に載っている都道府県の、表にない市区町村（小さい町村）を「値なし」として書く（0にしない）。"""
    prefs = {e[5:] for e in written if e.startswith("pref-")}
    n = 0
    for entity_id in sorted(known - written):
        if entity_id.startswith("pref-") or entity_id[5:7] not in prefs:
            continue
        for indicator_id, d in targets.items():
            insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                               definition_version=d["definition_version"], period_start=period[0],
                               period_end=period[1], period_kind=period[2], value=None, status="missing",
                               source_id=source_id, method_note=NOT_PUBLISHED)
        n += 1
    return n


def _write_ratio(conn, entity_id, indicator_id, d, num, den, source_id, period) -> None:
    obs = dict(entity_id=entity_id, indicator_id=indicator_id, definition_version=d["definition_version"],
               period_start=period[0], period_end=period[1], period_kind=period[2], source_id=source_id,
               denominator_source_id=source_id)
    if num is None or not den:
        insert_observation(conn, value=None, status="missing", **obs)
    else:
        insert_observation(conn, value=num / den * d.get("scale", 1), status="derived",
                           numerator=num, denominator=den, **obs)


def read_income(path: Path) -> dict[str, dict[tuple[float, float], float | None]]:
    """5桁コード → 収入階級（下限, 上限）→ 主世帯数。所有の関係は「総数」、世帯の種類は「主世帯」だけ。"""
    out: dict[str, dict[tuple[float, float], float | None]] = {}
    for r in read_sheet(path, sheet_names(path)[0]):
        cells = ["" if c is None else str(c).strip() for c in r]
        ai = next((j for j, c in enumerate(cells) if AREA.match(c)), None)
        if ai is None:
            continue
        labels = [(j, c) for j, c in enumerate(cells[ai + 1:], ai + 1) if LABEL.match(c)]
        if len(labels) not in (2, 3):
            continue
        if len(labels) == 3 and labels[0][1] != "1_主世帯":
            continue   # 平成30年: 同居世帯などは除く
        if labels[-2][1] != "0_総数":
            continue   # 所有の関係の総数だけ
        rng = _income_range(labels[-1][1])
        if rng is None:
            continue
        j = labels[-1][0] + 1
        while j < len(cells) and cells[j] == "":
            j += 1
        code = AREA.match(cells[ai]).group(1)
        out.setdefault(code, {})[rng] = _number(cells[j]) if j < len(cells) else None
    return out


def ingest_income(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict,
                  period: tuple[str, str, str]) -> dict:
    """年収の階級別の世帯の割合。指標の income_min / income_max（万円）の範囲に入る階級を分子に足す。"""
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == INCOME_KIND}
    known = _known(conn)
    written: set[str] = set()
    result = {"municipalities": 0, "prefectures": 0}
    for code, classes in sorted(read_income(path).items()):
        entity_id = _entity(known, code)
        if entity_id is None:
            continue   # 全国・政令指定都市の市全体・特別区部・対象外の都道府県
        for indicator_id, d in targets.items():
            lo, hi = float(d.get("income_min", 0)), float(d.get("income_max", float("inf")))
            if any(v is None for v in classes.values()):
                num = den = None
            else:
                den = sum(classes.values())
                # 階級が範囲をまたぐときは誤りなので止める（年で区切りが違っても、境目がそろう範囲だけ使う）
                inside = [k for k in classes if lo <= k[0] and k[1] <= hi]
                cross = [k for k in classes if k[0] < hi and k[1] > lo and k not in inside]
                if cross:
                    raise ValueError(f"{path.name}: 収入階級 {cross} が {indicator_id} の範囲をまたぎます")
                num = sum(classes[k] for k in inside)
            _write_ratio(conn, entity_id, indicator_id, d, num, den, source_id, period)
        written.add(entity_id)
        result["prefectures" if entity_id.startswith("pref-") else "municipalities"] += 1
    result["not_published"] = _write_missing_towns(conn, known, written, targets, source_id, period)
    return result


def ingest_stock(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict,
                 period: tuple[str, str, str]) -> dict:
    """住宅数の割合（空き家率など）。指標の housing_numerator ÷ housing_denominator（列名）。"""
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == STOCK_KIND}
    rows = read_sheet(path, sheet_names(path)[0])
    head = next(r for r in rows if any(str(c).strip() == "0_総数" for c in r if c is not None))
    cols = {str(c).strip(): j for j, c in enumerate(head) if c is not None and LABEL.match(str(c).strip())}
    for d in targets.values():
        for c in (d["housing_numerator"], d["housing_denominator"]):
            if c not in cols:
                raise KeyError(f"{path.name}: 列 {c} が見つかりません（{sorted(cols)}）")
    known = _known(conn)
    written: set[str] = set()
    result = {"municipalities": 0, "prefectures": 0}
    for r in rows:
        cells = ["" if c is None else str(c).strip() for c in r]
        m = next((AREA.match(c) for c in cells if AREA.match(c)), None)
        if m is None:
            continue
        entity_id = _entity(known, m.group(1))
        if entity_id is None:
            continue
        for indicator_id, d in targets.items():
            num = _number(r[cols[d["housing_numerator"]]])
            den = _number(r[cols[d["housing_denominator"]]])
            _write_ratio(conn, entity_id, indicator_id, d, num, den, source_id, period)
        written.add(entity_id)
        result["prefectures" if entity_id.startswith("pref-") else "municipalities"] += 1
    result["not_published"] = _write_missing_towns(conn, known, written, targets, source_id, period)
    return result
