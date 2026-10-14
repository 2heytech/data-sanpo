"""令和7年（2025年）国勢調査 人口等基本集計の e-Stat「ファイル」の表（Excel、全国・都道府県・市区町村）を読む。

形式（2026-09-29 公表の表1-1・2-7・6-3・9-1 を 2026-10-05 に GitHub Actions から取得して確認）:
  1枚のシート。「地域識別コード」のある行が列名の行で、その上の行に「表章項目」（例: 人口・世帯数・一般世帯数）、
  「項目名」（例: 0_総数、R1_（再掲）15歳未満、01_世帯人員が1人）が値の列ごとに並ぶ。
  地域識別コードは a 全国・都道府県、1 政令指定都市の市全体、0 特別区・政令指定都市の区、2 市、3 町村、
  9 2000年時点の市区町村（表1-1・2-7 にある）。市区町村のコードは「2025年_地域コード」の列か、
  「地域名」の先頭（例: 13101_千代田区）にある。
  地域の列の前後に分類の列があることがある（表2-7 の「国籍総数か日本人」「男女」、表9-1 の「世帯の家族類型」）。
  「-」は該当なし（0）、「X」は秘匿。

市区町村（地域識別コード 0・2・3）と都道府県（a、全国の行を除く）の行を、国勢調査の小地域の表と同じ形
（estat_small_area.Table）で返す。都道府県の行は KEY_CODE を2桁にする。政令指定都市の市全体の行は使わない。
都道府県の値は公表の都道府県の行を使う（2020年の境界に合わない市区町村があっても都道府県の値は出せるように。
例: 浜松市は2024年に区を再編し、新しい区は2020年の境界に当てはまらない。docs/design-changes.md #73）。

過去の調査の人口等基本集計の表も同じ形で読む（国籍別人口。docs/design-changes.md #102。2026-10-13 に GitHub Actions から取得して確認）:
  令和2年（2020年）の Excel は「表章項目」「項目名」の見出しの文字がなく、値の列の上の行に表章項目（人口）と
  項目名（0_総数、1_外国人、102_中国 …）だけが並ぶ。地域のコードは「地域名」の先頭（13101_千代田区）。
  平成27年・22年（2015・2010年）は CSV（cp932）。「地域コード」「地域識別コード」のある行が列名の行で、
  値の列名（総数（国籍）、中国、（別掲）総人口 …）は男女総数・男・女の順にくり返すので最初（男女総数）を使う。
  列名の末尾の注の番号（「その他 1)」の「 1)」）は除いて照合する。地域識別コード b（市部・郡部）・d（人口集中地区）の行は使わない。

従業地・通学地集計の表も同じ形で読む（昼間人口。docs/design-changes.md #106。2026-10-14 に GitHub Actions から取得して確認）:
  令和2年の表1-1（Excel）は「男女」「年齢」の分類の列がある（filters で総数の行を選ぶ）。
  平成27年の第1表（CSV）は列名の末尾に注の番号と記号がつく（「総数（昼間人口） 2)3) (k)」）。どちらも除いて照合する。
  平成22年は都道府県ごとの第1表（CSV）で、男女・年齢の分類が列名のない列に符号（danjo.0000・nen5EX.0000）で入る
  （row_codes で男女総数・年齢総数の行を選ぶ）。
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from ..xlsx import read_sheet
from .estat_small_area import Table

MUNICIPALITY_LEVELS = {"0", "2", "3"}
PREFECTURE_LEVEL = "a"
HEAD = "地域識別コード"


def _same(s: str) -> str:
    """列名の照合用（波ダッシュ・全角チルダ・半角チルダを同じにする）。"""
    return re.sub("[〜～~]", "~", s)


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else str(v)
    return str(v).strip()


def read_table(path: Path, columns: dict[str, str], filters: dict[str, str] | None = None,
               encoding: str = "cp932", row_codes: list[str] | None = None) -> Table:
    """columns: 返す列名 → 「表章項目/項目名」（項目名は先頭が一致すればよい。例: "人口/R1_（再掲）15歳未満"）。
    CSV（2015・2010年）は列名そのもの（例: "（別掲）総人口"）。
    filters: 分類の列名 → 残す値（例: {"男女": "0_総数"}）。
    row_codes: CSV で、行に含まれていなければならない分類の符号（列名のない分類の列。例: "danjo.0000"）。"""
    if path.suffix.lower() == ".csv":
        return _read_csv(path, columns, encoding, row_codes or [])
    rows = read_sheet(path)
    h = next((i for i, r in enumerate(rows[:60]) if any(c == HEAD for c in r)), None)
    if h is None:
        raise KeyError(f"{path.name}: 「{HEAD}」の行が見つかりません")
    head = [_cell_text(c) for c in rows[h]]
    above = [[_cell_text(c) for c in r] for r in rows[:h]]
    item_row = next((i for i in range(h - 1, -1, -1) if "表章項目" in above[i]), None)
    if item_row is not None:
        name_row = next(i for i in range(h - 1, item_row, -1) if "項目名" in above[i])
        label_col = above[item_row].index("表章項目")
    else:
        # 見出しの文字がない形（2020年）: 「0_総数」のような項目名の行と、その上の値の列に文字のある最初の行
        name_row = next(i for i in range(h - 1, -1, -1) if any(re.match(r"\d+_", c) for c in above[i]))
        label_col = next(j for j, c in enumerate(above[name_row]) if re.match(r"\d+_", c)) - 1
        item_row = next(i for i in range(name_row) if any(c for c in above[i][label_col + 1:]))
    items = above[item_row]
    names = above[name_row] + [""] * len(items)
    keys = {j: f"{items[j]}/{names[j]}" for j in range(label_col + 1, len(items)) if items[j]}
    picked: dict[str, int] = {}
    for out, spec in columns.items():
        hits = [j for j, k in keys.items() if _same(k) == _same(spec) or (_same(k).startswith(_same(spec)) and names[j])]
        if not hits:
            raise KeyError(f"{path.name}: 列 {spec} が見つかりません。項目: {list(keys.values())}")
        picked[out] = hits[0]
    level = head.index(HEAD)
    code_col = head.index("2025年_地域コード") if "2025年_地域コード" in head else head.index("地域名")
    conds = []
    for col, value in (filters or {}).items():
        if col not in head:
            raise KeyError(f"{path.name}: 分類の列 {col} が見つかりません。列名: {head}")
        conds.append((head.index(col), value))
    out_rows = []
    seen: set[str] = set()
    for r in rows[h + 1:]:
        cells = [_cell_text(c) for c in r] + [""] * (len(head) + len(items))
        if cells[level] not in MUNICIPALITY_LEVELS | {PREFECTURE_LEVEL} or any(cells[c] != v for c, v in conds):
            continue
        m = re.match(r"\d{5}", cells[code_col])
        if not m:
            continue
        key = m[0]
        if cells[level] == PREFECTURE_LEVEL:
            if not key.endswith("000") or key == "00000":
                continue   # 全国の行
            key = key[:2]
        if key in seen:
            continue
        seen.add(key)
        out_rows.append({"KEY_CODE": key, "HTKSYORI": "", "HTKSAKI": "", "GASSAN": "",
                         **{name: cells[j] for name, j in picked.items()}})
    return Table(["KEY_CODE", "HTKSYORI", "HTKSAKI", "GASSAN", *columns], out_rows, prefecture_rows=True)


def _csv_label(s: str) -> str:
    # 末尾の注の番号（「 1)」「 2)3)」）と記号（「 (k)」）を除く
    return re.sub(r"(\s*(\d\)|\([a-z]\)))+$", "", s.strip()).strip()


def _read_csv(path: Path, columns: dict[str, str], encoding: str, row_codes: list[str]) -> Table:
    with path.open(encoding=encoding, newline="") as f:
        rows = [[c.strip() for c in r] for r in csv.reader(f)]
    h = next((i for i, r in enumerate(rows[:60]) if HEAD in r and "地域コード" in r), None)
    if h is None:
        raise KeyError(f"{path.name}: 「地域コード」「{HEAD}」の行が見つかりません")
    head = rows[h]
    labels = [_csv_label(c) for c in head]
    picked: dict[str, int] = {}
    for out, spec in columns.items():
        if _csv_label(spec) not in labels:
            raise KeyError(f"{path.name}: 列 {spec} が見つかりません。列名: {head}")
        picked[out] = labels.index(_csv_label(spec))   # 男女総数・男・女でくり返す列名は最初（男女総数）
    level, code_col = head.index(HEAD), head.index("地域コード")
    out_rows = []
    seen: set[str] = set()
    for r in rows[h + 1:]:
        cells = r + [""] * len(head)
        if cells[level] not in MUNICIPALITY_LEVELS | {PREFECTURE_LEVEL} or not re.fullmatch(r"\d{5}", cells[code_col]):
            continue
        if any(c not in cells for c in row_codes):
            continue
        key = cells[code_col]
        if cells[level] == PREFECTURE_LEVEL:
            if not key.endswith("000") or key == "00000":
                continue   # 全国の行
            key = key[:2]
        if key in seen:
            continue
        seen.add(key)
        out_rows.append({"KEY_CODE": key, "HTKSYORI": "", "HTKSAKI": "", "GASSAN": "",
                         **{name: cells[j] for name, j in picked.items()}})
    return Table(["KEY_CODE", "HTKSYORI", "HTKSAKI", "GASSAN", *columns], out_rows, prefecture_rows=True)
