"""宮崎県内の市が BODIK ODCS（https://data.bodik.jp/）に CC BY 4.0 で出している、学校別の児童・生徒数の読み方。

県（宮崎県）の学校別の数は商用利用の条件が明示されていないので、市ごとに読む。2024年度以降の学校別の数があるのは
日向市だけ（宮崎市・都城市・延岡市は2022年度まで）。形式は 2026-10-17 に取得して確認したもの。
"""
import csv
import io
import re
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text

PREF = "45"


def _csv(f: Path) -> list[list[str]]:
    """CSV の行（UTF-8（BOM 付きを含む）か Shift_JIS）。空の行は除く。"""
    data = f.read_bytes()
    for enc in ("utf-8-sig", "cp932"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"{f.name}: 文字コードが分からない")
    return [r for r in csv.reader(io.StringIO(text, newline="")) if any(c.strip() for c in r)]


def read_hyuga(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """日向市「日向市立小中学校 児童・生徒数」の「令和6年度 公立小・中学校の児童生徒数一覧」CSV（UTF-8 BOM 付き）。
    1行目: (空), １年(人)…６年(人), 計(人)。1行1校で、小学校の行のあと「(小 計)」、中学校の行のあと「(小 計)」
    「合 計」の行がある（読まない）。数は「65 」「3,074 」のように後ろに空白・桁区切りが付く。
    学校名は「富高小」「富島中」の略称なので「小学校」「中学校」を付ける。分校は「東郷小（若竹）」（若竹分校）・
    「田の原分校」（美々津小の分校。「本年度休校」と書かれ、数がないので読まない）の形で、「東郷小学校若竹分校」
    「美々津小学校田の原分校」に直す。中学校は1〜3年の列だけ。総数は「計(人)」。特別支援学級を含むかは書かれていない。"""
    out = []
    for f in files:
        rows = _csv(f)
        head = [cell_text(h) for h in rows[0]]
        grade_cols = {int(m.group(1)): i for i, h in enumerate(head) if (m := re.fullmatch(r"(\d)年\(人\)", h))}
        total_col = head.index("計(人)")
        prev_school = ""
        for r in rows[1:]:
            raw = cell_text(r[0])
            if not raw or "計" in raw:
                continue
            m = re.fullmatch(r"(.+?)(小|中)(?:\((.+)\))?", raw)
            if m:
                base = m.group(1) + ("小学校" if m.group(2) == "小" else "中学校")
                kind = "elementary" if m.group(2) == "小" else "junior_high"
                name = base + (m.group(3) + "分校" if m.group(3) else "")
                if not m.group(3):
                    prev_school = base
            elif raw.endswith("分校"):          # 「田の原分校」: 直前の本校（美々津小）の分校
                kind, name = "elementary", prev_school + raw
            else:
                raise ValueError(f"{f.name}: 学校名が読めない: {raw}")
            total = cell_int(r[total_col])
            if total is None:
                continue                         # 「本年度休校」
            n = 6 if kind == "elementary" else 3
            g = [cell_int(r[grade_cols[k]]) for k in range(1, n + 1)]
            grades = {f"{k}年": v for k, v in enumerate(g, 1)} if None not in g and sum(g) == total else {}
            out.append(SchoolCount(pref=PREF, municipality="日向市", name=name, school_type=kind,
                                   year=cfg["school_year"], total=total, grades=grades))
    return out
