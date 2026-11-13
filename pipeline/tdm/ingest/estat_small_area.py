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
from ..regions import municipality_entity_id, prefecture_entity_id

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
    prefecture_rows: bool = False   # True: 2桁の KEY_CODE を都道府県の値として取り込む

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


def _has_municipalities(conn: sqlite3.Connection, pref: str) -> bool:
    """今回の対象の都道府県か（市区町村の地域がある）。"""
    return conn.execute("SELECT 1 FROM entities WHERE entity_id LIKE ? LIMIT 1",
                        (municipality_entity_id(pref + "%"),)).fetchone() is not None


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


def _boundary_key(key: str, keys: dict[str, str], filled: set[str]) -> str | None:
    """表の地域コードにあたる境界の KEY_CODE。丁目のない町・字は境界側で末尾 "00" のことがある。"""
    for k in ([key, key + "00"] if len(key) == 9 else [key]):
        if k in keys and k not in filled:
            return k
    return None


def match_rows(conn, table: Table, keys: dict[str, str] | None = None
               ) -> tuple[list[tuple[str, dict[str, str]]], list[str]]:
    """各行を地域IDに対応付ける。対応先のないコードの一覧も返す。

    keys は境界の KEY_CODE → 町丁・字等の地域ID（estat_boundary.area_keys。省くと地域IDの KEY_CODE そのもの）。
    同じ名前でまとめた地域（#183）に複数の行があたるときは、_combine で1行に合わせる。"""
    if keys is None:
        keys = {r[0].removeprefix("area-"): r[0] for r in conn.execute(
            "SELECT entity_id FROM entities WHERE entity_type = 'small_area'")}
    filled: set[str] = set()       # 行を対応付けた境界の KEY_CODE（同じ区域に2つの行を入れない）
    filled_munis: set[str] = set()
    others: list[tuple[str, dict[str, str]]] = []      # 都道府県・市区町村
    by_area: dict[str, list[dict[str, str]]] = {}     # 町丁・字等の地域ID → 行
    unmatched = []
    with_chome: set[str] = set()   # 丁目の行が対応した町・字（9桁）
    for row in _ordered_rows(table):
        key = row["KEY_CODE"].strip()
        if len(key) <= 2:
            if table.prefecture_rows and len(key) == 2 and _has_municipalities(conn, key):
                others.append((prefecture_entity_id(key), row))
            continue  # 都道府県の行（小地域の表では市区町村の合計から作るので使わない）
        if len(key) == 5:
            # 特別区部（13100）・政令指定都市の市全体（14100 等）は対象外
            entity_id = municipality_entity_id(key)
            if entity_id in filled_munis or not conn.execute(
                    "SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)).fetchone():
                unmatched.append(key)
                continue
            filled_munis.add(entity_id)
            others.append((entity_id, row))
            continue
        if len(key) == 9 and key in with_chome:
            # 丁目に分かれた町・字の行はその丁目の合計。境界に丁目のない部分（末尾00）があっても、
            # そこに合計を入れると二重に数えるので使わない
            continue
        bkey = _boundary_key(key, keys, filled)
        if bkey is None:
            unmatched.append(key)
            continue
        filled.add(bkey)
        by_area.setdefault(keys[bkey], []).append(row)
        if len(key) == 11 and not key.endswith("00"):
            with_chome.add(key[:9])
    towns = _towns(table) if any(len(rows) > 1 for rows in by_area.values()) else ({}, {})
    matched = others + [(entity_id, rows[0] if len(rows) == 1 else _combine(entity_id, rows, table, keys, towns))
                        for entity_id, rows in by_area.items()]
    # 丁目に分かれた町・字の行（9桁）は、その丁目が対応していれば問題ない
    prefixes = {r["KEY_CODE"].strip()[:9] for rows in by_area.values() for r in rows}
    unmatched = [k for k in unmatched if not (len(k) == 9 and k in prefixes)]
    return matched, unmatched


_META = {"KEY_CODE", "HTKSYORI", "HTKSAKI", "GASSAN"}


def _towns(table: Table) -> tuple[dict[str, list[str]], dict[str, dict[str, str]]]:
    """町・字（9桁） → 表にある丁目の行の地域コード（11桁）と、町・字の行（丁目の合計）。"""
    children: dict[str, list[str]] = {}
    totals: dict[str, dict[str, str]] = {}
    for r in table.rows:
        k = r["KEY_CODE"].strip()
        if len(k) == 11:
            children.setdefault(k[:9], []).append(k)
        elif len(k) == 9:
            totals[k] = r
    return children, totals


def _combine(entity_id: str, rows: list[dict[str, str]], table: Table, keys: dict[str, str],
             towns: tuple[dict[str, list[str]], dict[str, dict[str, str]]]) -> dict[str, str]:
    """同じ名前でまとめた地域（#183）にあたる複数の行を、1つの地域の行に合わせる。

    - 町・字の丁目の行がすべてこの地域にあたるときは、丁目の行の代わりに町・字の行（9桁。丁目の合計）を使う
      （丁目の値が秘匿されて町・字の行に含まれている場合も値が出せる）
    - 秘匿された行（HTKSYORI=2）の値は合算先に含まれる。合算先がこの地域の中なら、その行は数えない。
      合算先が地域の外なら、地域の値の一部が外に含まれているので、地域全体を秘匿（値なし）にする
    - 合算先の行（HTKSYORI=1）は、合算された秘匿地域がすべてこの地域の中なら印を外し、外のものだけを残す
    - 値は列ごとに足す（「X」が1つでもあれば「X」、空欄・「…」があれば空欄）。数でない列（名前など）は最初の行のまま。
      小地域の表の列は人数・世帯数などの数だけで、割合・平均の列は指標に使っていない（足すと誤るので使わないこと）
    """
    city5 = rows[0]["KEY_CODE"].strip()[:5]
    children, totals = towns

    def inside(code: str) -> bool:
        if keys.get(code) == entity_id or (len(code) == 9 and keys.get(code + "00") == entity_id):
            return True
        return len(code) == 9 and bool(children.get(code)) and all(
            keys.get(c) == entity_id for c in children[code])

    used: list[dict[str, str]] = []
    whole = {k[:9] for r in rows if len(k := r["KEY_CODE"].strip()) == 11
             and len(children.get(k[:9], [])) > 1 and k[:9] in totals and inside(k[:9])}
    for town in sorted(whole):
        used.append(totals[town])
    used += [r for r in rows if r["KEY_CODE"].strip()[:9] not in whole or len(r["KEY_CODE"].strip()) != 11]
    kept = [r for r in used if not (_is_secret(r) and inside(city5 + (r.get("HTKSAKI") or "").strip()))]
    if not kept:
        kept = used
    secret = next((r for r in kept if _is_secret(r)), None)
    if secret is not None:
        return dict(secret)
    out = dict(kept[0])
    outside = [g.strip() for r in kept if (r.get("HTKSYORI") or "").strip() == MERGED_FLAG
               for g in (r.get("GASSAN") or "").split(";") if g.strip() and not inside(city5 + g.strip())]
    out.update(HTKSYORI=MERGED_FLAG if outside else "0", HTKSAKI="", GASSAN=";".join(outside))
    for label in table.labels:
        if label in _META:
            continue
        try:
            cells = [parse_cell(r.get(label, "")) for r in kept]
        except ValueError:
            continue
        if any(c.status == "suppressed" for c in cells):
            out[label] = "X"
        elif any(c.value is None for c in cells):
            out[label] = ""
        else:
            out[label] = str(sum(c.value for c in cells))
    return out


def ingest_counts(conn: sqlite3.Connection, table: Table, source_id: str, indicator_id: str,
                  definition: dict, period: tuple[str, str, str], keys: dict[str, str] | None = None) -> dict:
    """keys: 境界の KEY_CODE → 町丁・字等の地域ID（match_rows）。"""
    # sum_columns: 複数の列の合計を件数にする（例: 大学＋大学院の在学者）
    cols = [table.column(c) for c in definition.get("sum_columns", [definition.get("column")])]
    matched, unmatched = match_rows(conn, table, keys)
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
                 definition: dict, period: tuple[str, str, str], keys: dict[str, str] | None = None) -> dict:
    """keys: 境界の KEY_CODE → 町丁・字等の地域ID（match_rows）。"""
    # 分子・分母は列の合計にできる（例: 分母は年齢3区分の合計＝年齢判明人口）
    num_cols = ([table.column(c) for c in definition["numerator_sum_columns"]]
                if "numerator_sum_columns" in definition
                else [table.column(definition["numerator_column"])])
    den_cols = [table.column(c) for c in definition["denominator_sum_columns"]]
    # denominator_subtract_columns: 分母から引く列（例: 通勤者・通学者の総数 − 利用交通手段「不詳」）
    sub_cols = [table.column(c) for c in definition.get("denominator_subtract_columns", [])]
    scale = float(definition.get("scale", 1))
    min_den = float(definition.get("min_denominator", 0))
    matched, unmatched = match_rows(conn, table, keys)
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
