"""総務省の市区町村の財政のデータを取り込む（docs/design-changes.md #119）。

1. 地方公共団体の主要財政指標一覧「全市町村の主要財政指標」（kind = soumu_fiscal_indicators、1年度1ファイル）
   形式（平成29〜令和6年度の Excel を 2026-10-15 に取得して確認）: 1行目が題名、2行目が列名
   「団体コード」「都道府県名」「団体名」「財政力指数」「経常収支比率」「実質公債費比率」「将来負担比率」「ラスパイレス指数」。
   団体コードは6桁（末尾は検査数字）で、全国の市町村と東京都の特別区（1,741団体）。政令指定都市は市全体の行だけ。
   将来負担比率の「-」（「－」の年もある）は、将来負担額より充当できる財源の方が多く、比率がマイナスになる団体。
   特別区の財政力指数は、市町村別決算状況調では「-」だが、この一覧には載っている。

2. 市町村別決算状況調（kind = soumu_settlement、1年度に都市別・町村別 × 概況・歳入内訳・地方債現在高等の6ファイル）
   形式（同じく平成29〜令和6年度を確認）: 列名は数行にわたり（例: 「健全化判断比率」の下に「将来負担比率」）、
   団体コードの列（O列）の下に1団体1行。都道府県名だけの見出しの行（団体コードが空）が挟まる。金額は千円。
   「-」は該当する数値がないこと（地方債のない団体の地方債現在高など）なので0として読む。
   住民基本台帳登載人口は年度末の翌日に近い1月1日現在（例: 令和6年度は令和7年1月1日）。

指標（definition の fiscal_column / settlement_column で選ぶ）:
  fiscal_column: 主要財政指標の列の値をそのまま入れる（都道府県の値は合計できないので出さない）
  settlement_column: 決算の列の額 ÷ 住民基本台帳登載人口（千円 → 円は scale = 1000）。都道府県は県内の団体の合計で割る
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from ..db import insert_observation
from ..regions import current_code, municipality_entity_id, prefecture_entity_id
from ..xlsx import read_sheet

POPULATION = "住民基本台帳登載人口"
# 決算の各ファイルから読む列（ファイル名の末尾の番号: 1 概況・2 歳入内訳・5 地方債現在高等）
SETTLEMENT_COLUMNS = {"1": [POPULATION, "歳出総額"], "2": ["地方税"], "5": ["地方債現在高", "積立金現在高"]}
DASHES = {"-", "－", "‐", "―"}


def _norm(cell) -> str:
    return re.sub(r"\s+", "", str(cell)) if cell is not None else ""


def _code5(cell) -> str | None:
    code = _norm(cell)
    if not re.fullmatch(r"\d{6}", code):
        return None
    return current_code(code[:5])   # 市になって団体コードが変わる前の年度の行（regions.CODE_CHANGES）


def read_fiscal_indicators(path: Path, prefs: list[str]) -> dict[str, dict[str, float | str | None]]:
    """主要財政指標の一覧。地域コード5桁 → 列名 → 値（数値、「-」の印、空なら None）。"""
    rows = read_sheet(path)
    at = next(i for i, r in enumerate(rows) if any(_norm(c) == "団体コード" for c in r))
    header = [_norm(c) for c in rows[at]]
    code_col = header.index("団体コード")
    out: dict[str, dict] = {}
    for r in rows[at + 1:]:
        code = _code5(r[code_col]) if len(r) > code_col else None
        if code is None or code[:2] not in prefs:
            continue
        out[code] = {h: _value(r[i] if i < len(r) else None, dash="-") for i, h in enumerate(header) if h}
    return out


def _value(cell, dash):
    if isinstance(cell, float):
        return cell
    return dash if _norm(cell) in DASHES else None


def _settlement_table(path: Path, columns: list[str]) -> dict[str, dict[str, float | None]]:
    """決算状況調の1ファイル。列名の行（団体コードの行から最初の団体の行の前まで）のどこかに、名前がそのまま
    書かれている最初の列を使う（歳入内訳の「地方税」は内訳の表にも同じ名前があるので、最初の列＝歳入の地方税）。"""
    rows = read_sheet(path)
    at = next(i for i, r in enumerate(rows) if any(_norm(c) == "団体コード" for c in r))
    code_col = next(j for j, c in enumerate(rows[at]) if _norm(c) == "団体コード")
    first = next(i for i in range(at + 1, len(rows))
                 if len(rows[i]) > code_col and _code5(rows[i][code_col]))
    labels: dict[int, set[str]] = {}
    # 「歳入内訳」は団体コードの1行上にも見出し（「一」などの番号）があるので、その行から見る
    for i in range(max(at - 1, 0), first):
        for j, c in enumerate(rows[i]):
            if _norm(c):
                labels.setdefault(j, set()).add(_norm(c))
    col = {}
    for name in columns:
        hits = sorted(j for j, ls in labels.items() if name in ls)
        if not hits:
            raise ValueError(f"{path.name}: 列「{name}」が見つかりません")
        col[name] = hits[0]
    out = {}
    for r in rows[first:]:
        code = _code5(r[code_col]) if len(r) > code_col else None
        if code is None:
            continue
        out[code] = {name: _value(r[j] if j < len(r) else None, dash=0.0) for name, j in col.items()}
    return out


def read_settlement(files: list[Path], prefs: list[str]) -> dict[str, dict[str, float | None]]:
    """決算状況調の都市別・町村別の各ファイルをまとめる。地域コード5桁 → 列名 → 値（千円・人）。"""
    out: dict[str, dict] = {}
    for f in files:
        m = re.search(r"_(\d)\.xlsx$", f.name)
        if not m or m[1] not in SETTLEMENT_COLUMNS:
            continue
        for code, values in _settlement_table(f, SETTLEMENT_COLUMNS[m[1]]).items():
            if code[:2] in prefs:
                out.setdefault(code, {}).update(values)
    return out


def _exists(conn: sqlite3.Connection, entity_id: str) -> bool:
    return conn.execute("SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)).fetchone() is not None


def ingest_fiscal_indicators(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict,
                             period: tuple[str, str, str], prefs: list[str]) -> dict:
    data = read_fiscal_indicators(path, prefs)
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "soumu_fiscal_indicators"}
    result = {"municipalities": 0, "not_in_map": []}
    base = dict(period_start=period[0], period_end=period[1], period_kind=period[2], source_id=source_id)
    for code, values in sorted(data.items()):
        entity_id = municipality_entity_id(code)
        if not _exists(conn, entity_id):
            # 政令指定都市は市全体の値しかない。区に割り振ると元データより細かくなるので、区には値を入れない
            result["not_in_map"].append(code)
            continue
        result["municipalities"] += 1
        for indicator_id, d in targets.items():
            obs = dict(base, entity_id=entity_id, indicator_id=indicator_id,
                       definition_version=d["definition_version"])
            v = values.get(d["fiscal_column"])
            if v == "-" and "dash_value" in d:
                # 将来負担比率の「-」（比率がマイナス＝将来負担なし）。印のまま値なしにすると欠測に見えるので、
                # 指標の定義で決めた値（0）で塗り、注記を付ける
                insert_observation(conn, value=float(d["dash_value"]), status="observed",
                                   method_note=d.get("dash_note"), **obs)
            elif isinstance(v, float):
                insert_observation(conn, value=v, status="observed", **obs)
            else:
                insert_observation(conn, value=None, status="missing", **obs)
    # 比率は市区町村の値を合計できず、都道府県（県庁）の財政とも意味が違うので、都道府県の値は出さない
    for pref in sorted({c[:2] for c in data}):
        for indicator_id, d in targets.items():
            insert_observation(conn, entity_id=prefecture_entity_id(pref), indicator_id=indicator_id,
                               definition_version=d["definition_version"], value=None,
                               status="not_applicable",
                               method_note="都道府県の値はありません（市区町村の比率は合計できないため）", **base)
    return result


def ingest_settlement(conn: sqlite3.Connection, files: list[Path], source_id: str, catalog: dict,
                      period: tuple[str, str, str], prefs: list[str]) -> dict:
    data = read_settlement(files, prefs)
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "soumu_settlement"}
    result = {"municipalities": 0, "prefectures": 0, "not_in_map": []}
    # 都道府県の値は、政令指定都市（市全体の行）を含む県内のすべての団体の合計から出す
    totals: dict[str, dict[str, float | None]] = {}
    for code, values in sorted(data.items()):
        t = totals.setdefault(code[:2], {})
        for name, v in values.items():
            t[name] = None if v is None or (name in t and t[name] is None) else t.get(name, 0.0) + v
        entity_id = municipality_entity_id(code)
        if not _exists(conn, entity_id):
            result["not_in_map"].append(code)
            continue
        _insert_per_capita(conn, entity_id, values, targets, source_id, period)
        result["municipalities"] += 1
    for pref, values in sorted(totals.items()):
        _insert_per_capita(conn, prefecture_entity_id(pref), values, targets, source_id, period,
                           note="県内の市区町村（政令指定都市は市全体）の決算の合計を、県内の人口で割って計算"
                                "（都道府県庁の決算は含みません）")
        result["prefectures"] += 1
    return result


def _insert_per_capita(conn: sqlite3.Connection, entity_id: str, values: dict, targets: dict,
                       source_id: str, period: tuple[str, str, str], note: str | None = None) -> None:
    population = values.get(POPULATION)
    for indicator_id, d in targets.items():
        amount = values.get(d["settlement_column"])
        obs = dict(entity_id=entity_id, indicator_id=indicator_id, definition_version=d["definition_version"],
                   period_start=period[0], period_end=period[1], period_kind=period[2],
                   source_id=source_id, denominator_source_id=source_id, numerator=amount,
                   denominator=population, method_note=note)
        if amount is None or not population:
            insert_observation(conn, value=None, status="missing", **obs)
        else:
            insert_observation(conn, value=amount / population * d.get("scale", 1), status="derived", **obs)
