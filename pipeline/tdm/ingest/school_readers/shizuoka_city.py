import csv
import re
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text


def read_shizuoka_city(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """静岡市「静岡市立の学校に在籍する児童及び生徒数」（静岡県オープンデータカタログ、CC BY）の CSV（UTF-8 BOM）。
    保存名 elementary.csv（市立小学校：児童及び学級数）・junior_high.csv（市立中学校：生徒及び学級数）。

    形式（2026-10-17 に取得して確認）:
      1行目 題名「公立小学校　児童数及び学級数（R8.5.1時点）」（中学校は「公立中学校　生徒数及び学級数（…）」）
      2行目 №, (空 / 「公立中学校」), 「１年生」, , , 「２年生」, …, 「計」, , , 「学級数」, …
      3行目 , , 男, 女, 計, 男, 女, 計, …（学年ごとに男・女・計の3列。そのあと全体の男・女・計、学級数の列）
      4行目から 1行1校: №, 学校名（「番町小」「清水有度第一小」「籠上中」のような略称）, 人数…
    年度は題名の「R8.5.1時点」から読む（令和8年度＝2026。読めなければ cfg["school_year"]）。

    注意:
      - 最新年度だけ掲載（毎年差し替え）。静岡市が同じ表を載せている PDF には「速報値」「暫定値であり、今後修正される
        場合があります」とある（令和8年5月1日現在）。
      - 学校名は「〇〇小」「〇〇中」の略称なので「小学校」「中学校」に直す（突き合わせで種類の語は除かれるが、表示名のため）。
      - 総数が0の学校（2026年度は井川中）は休校とみて出さない。
      - 学級数の列（特支・複式を含む）は読まない。特別支援学級の児童・生徒は各学年の数に含まれている（再掲の列はない）。
      - 学校コード・所在地はない。義務教育学校はない。
      - 中学校を先に返す。2026年4月に蒲原西小・蒲原東小・蒲原中を統合して開校した蒲原小中学校（施設一体型の小中一貫校。
        表では「蒲原小」「蒲原中」の2行）の「蒲原小」は P29（2023年度）に点がなく、小学校を先に突き合わせると
        種類を問わない名前の照合で「蒲原中学校」の点に付いてしまうため。
    """
    out = []
    for f in files:
        m = re.search(r"(elementary|junior_high)", f.name)
        if not m:
            continue
        kind = m.group(1)
        rows = list(csv.reader(f.open(encoding="utf-8-sig", newline="")))
        title = cell_text(rows[0][0]) if rows and rows[0] else ""
        y = re.search(r"R(\d+)\.5\.1", title)
        year = 2018 + int(y.group(1)) if y else cfg["school_year"]
        head = [cell_text(h) for h in rows[1]]
        sub = [cell_text(h) for h in rows[2]]
        # 学年（「１年生」）と全体（「計」）の列の塊。塊の中で「計」の列を使う
        blocks = {}
        for i, h in enumerate(head):
            g = re.fullmatch(r"(\d)年生", h)
            if g or h == "計":
                j = next(k for k in range(i, min(i + 3, len(sub))) if sub[k] == "計")
                blocks[f"{g.group(1)}年" if g else "total"] = j
        if "total" not in blocks:
            raise ValueError(f"{f.name}: 「計」の列が見つからない")
        suffix = "小学校" if kind == "elementary" else "中学校"
        for r in rows[3:]:
            if len(r) <= blocks["total"]:
                continue
            name = cell_text(r[1])
            if not name or not cell_text(r[0]).isdigit():
                continue
            n = cell_int(r[blocks["total"]])
            if not n:          # 読めない値・0人（休校）は出さない
                continue
            if re.search(r"[小中]$", name):
                name = name[:-1] + suffix
            grades = {k: cell_int(r[i]) for k, i in blocks.items() if k != "total"}
            if any(v is None for v in grades.values()) or sum(grades.values()) != n:
                grades = {}
            out.append(SchoolCount(pref="22", municipality="静岡市", name=name, school_type=kind,
                                   year=year, total=n, grades=dict(sorted(grades.items()))))
    return sorted(out, key=lambda s: s.school_type != "junior_high")
