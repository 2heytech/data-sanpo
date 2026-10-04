"""e-Stat 統計GIS の小地域集計（CSV/TXT）を取り込む。

ファイルは1行目が項目コード、2行目が項目名（日本語）の形式を想定する。列は項目名で
探すため、項目コードの違いには影響されない。見つからない場合は候補を示して止める。

記号の扱い（e-Stat の凡例に従う）:
  "-"  該当数値なし → 0（真のゼロ）
  "X"  秘匿 → status=suppressed（値なし）
  "…" / "..." / 空欄 → status=missing（値なし）
秘匿処理（HTKSYORI）:
  "2" 秘匿された地域。値は X で、合算先の地域（市区町村コード + HTKSAKI の6桁）に含まれる
  "1" 合算先の地域。GASSAN に列挙された秘匿地域の値を含む
（2020年国勢調査 小地域集計 T001081・T001082 の実ファイルで確認、2026-10-03）

統計GIS に町丁・字等の表がない項目（最終学歴など）は、e-Stat「ファイル」の小地域集計CSVを
read_files_table で同じ Table の形に読み替える（docs/design-changes.md #27-2）。
"""
from __future__ import annotations

import csv
import io
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ..db import insert_observation
from ..regions import municipality_entity_id, small_area_entity_id

ZERO_MARKS = {"-", "－"}
SUPPRESSED_MARKS = {"X", "x", "Ｘ"}
MISSING_MARKS = {"", "…", "...", "･･･"}


def normalize_label(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").replace("〜", "~")
    return "".join(text.split()).replace("「", "").replace("」", "")


@dataclass
class Cell:
    value: float | None
    status: str  # observed / suppressed / missing


def parse_cell(raw: str) -> Cell:
    raw = (raw or "").strip()
    if raw in ZERO_MARKS:
        return Cell(0.0, "observed")
    if raw in SUPPRESSED_MARKS:
        return Cell(None, "suppressed")
    if raw in MISSING_MARKS:
        return Cell(None, "missing")
    return Cell(float(raw.replace(",", "")), "observed")


@dataclass
class Table:
    labels: list[str]
    rows: list[dict[str, str]]

    def column(self, candidates: list[str]) -> str:
        wanted = [normalize_label(c) for c in candidates]
        normalized = {normalize_label(l): l for l in self.labels}
        for w in wanted:
            if w in normalized:
                return normalized[w]
        raise KeyError(f"列 {candidates} が見つかりません。項目名: {self.labels}")


def read_table(path: Path, encoding: str = "cp932") -> Table:
    text = path.read_bytes().decode(encoding)
    records = list(csv.reader(io.StringIO(text)))
    codes, second = records[0], records[1]
    has_label_row = not second[0].strip().isdigit()
    labels = []
    for i, code in enumerate(codes):
        label = second[i].strip() if has_label_row and i < len(second) else ""
        labels.append(label or code.strip())
    body = records[2:] if has_label_row else records[1:]
    return Table(labels, [dict(zip(labels, r)) for r in body if r and r[0].strip()])


# e-Stat「ファイル」の小地域集計CSV（例: 令和2年 第13表 h13_13.csv）の秘匿処理の表記
FILES_SECRET = "秘匿地域"
FILES_MERGED = "合算地域あり"


def read_files_table(path: Path, encoding: str = "cp932") -> Table:
    """e-Stat「ファイル」の小地域集計CSVを、統計GISの表と同じ列（KEY_CODE・HTKSYORI 等）に読み替える。

    形式（令和2年国勢調査 第13表、平成27年 第13表で確認、2026-10-03）: 先頭列は行番号、4行目が列名。
    男女（総数・男・女）ごとに行が分かれるので「総数」の行だけ使う。男女の列がない表（第2表）は全行を使う。
    第2表は5行目が列名で、列名が「-」の列（外国人人口・世帯数）は4行目の分類名を使う。地域コードは
    市区町村コード5桁＋町丁字コード（町・字は4桁、丁目は6桁、市区町村は「-」）。
    """
    text = path.read_bytes().decode(encoding)
    records = list(csv.reader(io.StringIO(text)))
    header_at = next(i for i, r in enumerate(records)
                     if "市区町村コード" in [c.strip() for c in r])
    header = [c.strip() for c in records[header_at]]
    col = {name: i for i, name in enumerate(header)}
    first_value = col["字・丁目名"] + 1
    # 列名が「-」の列は1行上の分類名を列名にする（第2表の「外国人人口」「世帯数」）
    above = records[header_at - 1] if header_at else []
    values = [above[i].strip() if h in ("", "-") and i < len(above) else h
              for i, h in enumerate(header)][first_value:]
    # 2015年の表（男女の列がない）は総数・男・女の値が横に並び、列名がくり返す。最初（総数）の列を使い、
    # くり返した列には番号を付けて区別する
    seen: dict[str, int] = {}
    for i, v in enumerate(values):
        seen[v] = seen.get(v, 0) + 1
        if seen[v] > 1:
            values[i] = f"{v}#{seen[v]}"
    labels = ["KEY_CODE", "HTKSYORI", "HTKSAKI", "GASSAN", *values]
    rows = []
    for r in records[header_at + 1:]:
        if len(r) < len(header) or ("男女" in col and r[col["男女"]].strip() != "総数"):
            continue
        town = r[col["町丁字コード"]].strip()
        key = r[col["市区町村コード"]].strip() + ("" if town in ("", "-") else town)
        flag = r[col["秘匿処理"]].strip()
        flag = SECRET_FLAG if flag == FILES_SECRET else MERGED_FLAG if flag == FILES_MERGED else ""
        rows.append(dict(zip(labels, [key, flag, r[col["秘匿先情報"]].strip(),
                                      r[col["合算地域"]].strip(), *r[first_value:]])))
    return Table(labels, rows)


READERS = {"estat_gis": read_table, "estat_files": read_files_table}


def _entity_for(conn: sqlite3.Connection, key: str, filled: set[str]) -> str | None:
    if len(key) == 5:
        candidates = [municipality_entity_id(key)]  # 特別区部（13100）・政令指定都市の市全体（14100 等）は対象外
    else:
        candidates = [small_area_entity_id(key)]
    if len(key) == 9:  # 丁目のない町・字は境界側で末尾 "00"
        candidates.append(small_area_entity_id(key + "00"))
    for c in candidates:
        if c not in filled and conn.execute(
                "SELECT 1 FROM entities WHERE entity_id = ?", (c,)).fetchone():
            return c
    return None


def _ordered_rows(table: Table) -> list[dict[str, str]]:
    # 11桁（丁目）を先に処理し、9桁（町・字）は対応する境界が空いている場合のみ使う
    return sorted(table.rows, key=lambda r: -len(r["KEY_CODE"].strip()))


SECRET_FLAG = "2"   # 秘匿され、合算先に値が含まれる地域
MERGED_FLAG = "1"   # 秘匿地域の値を含む合算先


def _is_secret(row: dict[str, str]) -> bool:
    return (row.get("HTKSYORI") or "").strip() == SECRET_FLAG


def _notes(row: dict[str, str]) -> str | None:
    flag = (row.get("HTKSYORI") or "").strip()
    if flag == SECRET_FLAG:
        saki = (row.get("HTKSAKI") or "").strip()
        target = row["KEY_CODE"].strip()[:5] + saki if saki else "近隣の地域"
        return f"秘匿処理により値は地域コード {target} に合算"
    if flag == MERGED_FLAG:
        n = len([g for g in (row.get("GASSAN") or "").split(";") if g.strip()])
        return f"秘匿処理された近隣地域{f'（{n}地域）' if n else ''}の値を含む"
    return None


def match_rows(conn, table: Table) -> tuple[list[tuple[str, dict[str, str]]], list[str]]:
    """各行を地域IDに対応付ける。対応先のないコードの一覧も返す。"""
    filled: set[str] = set()
    matched, unmatched = [], []
    with_chome: set[str] = set()   # 丁目の行が対応した町・字（9桁）
    for row in _ordered_rows(table):
        key = row["KEY_CODE"].strip()
        if len(key) <= 2:
            continue  # 都道府県の行
        if len(key) == 9 and key in with_chome:
            # 丁目に分かれた町・字の行はその丁目の合計。境界に丁目のない部分（末尾00）があっても、
            # そこに合計を入れると二重に数えるので使わない
            continue
        entity_id = _entity_for(conn, key, filled)
        if entity_id is None:
            unmatched.append(key)
            continue
        filled.add(entity_id)
        matched.append((entity_id, row))
        if len(key) == 11 and not key.endswith("00"):
            with_chome.add(key[:9])
    # 丁目に分かれた町・字の行（9桁）は、その丁目が対応していれば問題ない
    prefixes = {e.removeprefix("area-")[:9] for e, _ in matched}
    unmatched = [k for k in unmatched if not (len(k) == 9 and k in prefixes)]
    return matched, unmatched


def ingest_counts(conn: sqlite3.Connection, table: Table, source_id: str, indicator_id: str,
                  definition: dict, period: tuple[str, str, str]) -> dict:
    # sum_columns: 複数の列の合計を件数にする（例: 大学＋大学院の在学者）
    cols = [table.column(c) for c in definition.get("sum_columns", [definition.get("column")])]
    matched, unmatched = match_rows(conn, table)
    for entity_id, row in matched:
        cells = [parse_cell(row[c]) for c in cols]
        if any(c.status == "suppressed" for c in cells):
            cell = Cell(None, "suppressed")
        elif any(c.value is None for c in cells):
            cell = Cell(None, "missing")
        else:
            cell = Cell(sum(c.value for c in cells), "observed")
        if _is_secret(row) and cell.value is not None:
            cell = Cell(None, "suppressed")  # 合算先で計上済みのため二重計上しない
        insert_observation(
            conn, entity_id=entity_id, indicator_id=indicator_id,
            definition_version=definition["definition_version"],
            period_start=period[0], period_end=period[1], period_kind=period[2],
            value=cell.value, status=cell.status, source_id=source_id,
            coverage_note=_notes(row))
    return {"rows": len(matched), "unmatched": unmatched}


def ingest_ratio(conn: sqlite3.Connection, table: Table, source_id: str, indicator_id: str,
                 definition: dict, period: tuple[str, str, str]) -> dict:
    # 分子・分母は列の合計にできる（例: 分母は年齢3区分の合計＝年齢判明人口）
    num_cols = ([table.column(c) for c in definition["numerator_sum_columns"]]
                if "numerator_sum_columns" in definition
                else [table.column(definition["numerator_column"])])
    den_cols = [table.column(c) for c in definition["denominator_sum_columns"]]
    # denominator_subtract_columns: 分母から引く列（例: 通勤者・通学者の総数 − 利用交通手段「不詳」）
    sub_cols = [table.column(c) for c in definition.get("denominator_subtract_columns", [])]
    scale = float(definition.get("scale", 1))
    min_den = float(definition.get("min_denominator", 0))
    matched, unmatched = match_rows(conn, table)
    for entity_id, row in matched:
        nums = [parse_cell(row[c]) for c in num_cols]
        dens = [parse_cell(row[c]) for c in den_cols]
        subs = [parse_cell(row[c]) for c in sub_cols]
        hidden = _is_secret(row)
        obs = dict(entity_id=entity_id, indicator_id=indicator_id,
                   definition_version=definition["definition_version"],
                   period_start=period[0], period_end=period[1], period_kind=period[2],
                   source_id=source_id, denominator_source_id=source_id,
                   coverage_note=_notes(row), method_note=None)
        parts = (*nums, *dens, *subs)
        if hidden or any(c.status == "suppressed" for c in parts):
            obs.update(value=None, status="suppressed")
        elif any(c.value is None for c in parts):
            obs.update(value=None, status="missing")
        else:
            denominator = sum(c.value for c in dens) - sum(c.value for c in subs)
            numerator = sum(c.value for c in nums)
            obs.update(numerator=numerator, denominator=denominator)
            if denominator <= 0:
                obs.update(value=None, status="not_applicable",
                           method_note="分母が0のため算出しない")
            elif denominator < min_den:
                obs.update(value=None, status="withheld",
                           method_note=f"分母が{min_den:g}未満のため非表示")
            else:
                obs.update(value=numerator / denominator * scale, status="derived")
        insert_observation(conn, **obs)
    return {"rows": len(matched), "unmatched": unmatched}
