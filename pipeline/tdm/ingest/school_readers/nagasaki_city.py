import csv
import re
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text


def read_nagasaki_city(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """長崎市「児童・生徒数一覧（市立小学校）」「児童・生徒数一覧（市立中学校）」（BODIK、CC BY 4.0）の CSV（UTF-8 BOM）。
    保存名 elementary.csv・junior_high.csv。年ごとに1ファイル（2019〜2026年）。

    形式（2026-10-17 に取得して確認）:
      見出し 全国地方公共団体コード, 地方公共団体名, 調査年月日, 小学校名（中学校は「中学校名」）, 1年, …, 6年
      （中学校は 1年〜3年）, 合計, 備考。1行1校。
      2行目は市全体の合計の行（学校名が「（66校）」）なので読まない。
      学校名は「戸石」「小ヶ倉」のように「小学校」「中学校」を除いた形。
      調査年月日は学校基本調査の基準日（2026-05-01）。年度はここから読む（読めなければ cfg["school_year"]）。

    注意:
      - 分校は「開成分校」とだけ書かれ、本校の行のすぐ後に並ぶ（2026年: 小学校は南陽の後、中学校は土井首の後）。
        P29 では「南陽小学校開成分校」「土井首中学校開成分校」なので、直前の本校の名前を付けて「南陽小学校開成分校」の形にする。
      - 合計が0・空欄の学校は休校とみて出さない（2026年はない）。備考は2026年は空。
      - 学校コード・所在地はない。義務教育学校はない（伊王島・高島・池島などは小学校と中学校を別の行で出している）。
    """
    out = []
    for f in files:
        m = re.search(r"(elementary|junior_high)", f.name)
        if not m:
            continue
        kind = m.group(1)
        suffix = "小学校" if kind == "elementary" else "中学校"
        rows = list(csv.reader(f.open(encoding="utf-8-sig", newline="")))
        head = [cell_text(h) for h in rows[0]]
        name_col = next(i for i, h in enumerate(head) if h in ("小学校名", "中学校名", "学校名"))
        date_col = head.index("調査年月日")
        total_col = head.index("合計")
        grade_cols = {f"{g.group(1)}年": i for i, h in enumerate(head) if (g := re.fullmatch(r"(\d)年", h))}
        parent = None
        for r in rows[1:]:
            if len(r) <= total_col:
                continue
            name = cell_text(r[name_col])
            if not name or re.fullmatch(r"\(\d+校\)", name) or name in ("合計", "計"):
                continue
            y = re.match(r"(\d{4})", cell_text(r[date_col]))
            year = int(y.group(1)) if y else cfg["school_year"]
            if name.endswith("分校"):
                if parent and not re.search(r"(小学校|中学校)", name):
                    name = parent + suffix + name
            else:
                parent = re.sub(r"(小学校|中学校|小|中)$", "", name)
                name = parent + suffix
            n = cell_int(r[total_col])
            if not n:          # 休校（0人・空欄）は出さない
                continue
            grades = {g: cell_int(r[i]) for g, i in sorted(grade_cols.items())}
            if any(v is None for v in grades.values()) or sum(grades.values()) != n:
                grades = {}
            out.append(SchoolCount(pref="42", municipality="長崎市", name=name, school_type=kind,
                                   year=year, total=n, grades=grades))
    return out
