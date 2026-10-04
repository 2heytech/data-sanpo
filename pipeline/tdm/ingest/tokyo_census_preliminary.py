"""東京都「令和7年国勢調査 人口及び世帯数（速報）」表3（区市町村別の人口・世帯数）を読む。

形式（kt25sv0300.csv を 2026-10-03 に確認）: UTF-8（BOM付き）のCSV。1行目が列名で、「地域階層」4 の行が
区市町村（0 は東京都総数、1 は区部・市部など）、「地域コード」は団体コード5桁。末尾に空行と表題の行がある。
人口は「人口／総数／令和7（2025）年（人）」、世帯数は「世帯／総数／令和7（2025）年（世帯）」。
町丁・字等の速報はないため、区市町村の値だけを国勢調査の人口の表（population）と同じ形で返す。
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from .estat_small_area import Table

MUNICIPALITY_LEVEL = "4"


def read_table(path: Path, columns: dict[str, str], encoding: str = "utf-8-sig") -> Table:
    """columns: 返す列名 → 元の列名（例: {"人口総数": "人口／総数／令和7（2025）年（人）"}）。"""
    rows = list(csv.DictReader(io.StringIO(path.read_bytes().decode(encoding))))
    header = {c.strip(): c for c in rows[0] if c}
    missing = [src for src in columns.values() if src not in header]
    if missing:
        raise KeyError(f"列 {missing} が見つかりません。項目名: {list(header)}")
    labels = ["KEY_CODE", "HTKSYORI", "HTKSAKI", "GASSAN", *columns]
    out = []
    for r in rows:
        if (r.get("地域階層") or "").strip() != MUNICIPALITY_LEVEL:
            continue
        out.append({"KEY_CODE": r["地域コード"].strip(), "HTKSYORI": "", "HTKSAKI": "", "GASSAN": "",
                    **{name: r[header[src]].strip() for name, src in columns.items()}})
    return Table(labels, out)
