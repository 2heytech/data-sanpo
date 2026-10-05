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
"""
from __future__ import annotations

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


def read_table(path: Path, columns: dict[str, str], filters: dict[str, str] | None = None) -> Table:
    """columns: 返す列名 → 「表章項目/項目名」（項目名は先頭が一致すればよい。例: "人口/R1_（再掲）15歳未満"）。
    filters: 分類の列名 → 残す値（例: {"男女": "0_総数"}）。"""
    rows = read_sheet(path)
    h = next((i for i, r in enumerate(rows[:60]) if any(c == HEAD for c in r)), None)
    if h is None:
        raise KeyError(f"{path.name}: 「{HEAD}」の行が見つかりません")
    head = [_cell_text(c) for c in rows[h]]
    item_row = next(i for i in range(h - 1, -1, -1) if "表章項目" in [_cell_text(c) for c in rows[i]])
    name_row = next(i for i in range(h - 1, item_row, -1) if "項目名" in [_cell_text(c) for c in rows[i]])
    items = [_cell_text(c) for c in rows[item_row]]
    names = [_cell_text(c) for c in rows[name_row]] + [""] * len(items)
    label_col = items.index("表章項目")
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
