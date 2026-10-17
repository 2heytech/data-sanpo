import re
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text, workbook

TYPES = {"小学校": "elementary", "中学校": "junior_high", "義務教育学校": "compulsory"}


def read_niigata(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """新潟県教育委員会「学校基本調査関連データ」の「小学校／中学校／義務教育学校　設置者別・学校別学級数、児童数（生徒数）」（xls。
    5月1日現在）。2026-10-17 に取得して確認（令和7年度版。令和8年度は速報の PDF だけで、学校別の表はまだない）。

    形式: 1ファイル1シート。1行目が学校の種類（「小学校」「中学校」「義務教育学校」）、3〜6行目が見出し:
      区分, 学校数, 学級数（総数・単式学級の学年別・複式学級・特別支援学級の障害種別）, 児童数（生徒数）の総数, 学年別児童数（生徒数）
      （「1年」〜「6年」。中学校は「1年」〜「3年」、義務教育学校は「1年」〜「9年」）。
    行は「総計」→「国立計」と国立の学校→「公立計」→「市立計」→市ごとの見出し行（「新 潟 市」。学校数の列に「105(1)」の
    ように数がある）とその市の学校（学校数の列が空）→「町村立計」→町村の見出し行と学校→（中学校は）「私立計」と私立の学校。
    学校名は「浜浦」のように「小学校」なしの略した形（設置者の市町村名も付かない）。分校は「内野（希望が丘）」の形。
    値のない欄は「-」。

    注意:
      - 「公立計」から「私立計」の前までの、市町村の見出し行の下の学校だけを読む（国立・私立は読まない）。
        市町村名は見出し行の名前（字間の空白を除く）。新潟県には県立の小中学校・義務教育学校はない（中等教育学校は別のファイル）。
      - 総数は児童数（生徒数）の「総数」（中学校は「計」）の列。学年別の和と一致する。特別支援学級の列は学級数なので使わない。
      - 総数が「-」・0 の学校（休校など）は行を出さない。
      - 分校「X（Y）」は「X小学校Y分校」の形にする（例: 内野（希望が丘）→ 内野小学校希望が丘分校）。
      - 旧字体の「曾」は「曽」にそろえる（令和7年度版の長岡市「富曾亀」。正式名は富曽亀小学校）。
      - 学校コード・所在地はない。年度は cfg["school_year"]（表に年度の記載がない。令和7年度版なら 2025）。
    """
    out = []
    for f in files:
        for sheet, rows in workbook(f):
            kind = cell_text(rows[0][0]) if rows and rows[0] else ""
            if kind not in TYPES:
                continue
            school_type = TYPES[kind]
            hi = next(i for i, r in enumerate(rows) if r and cell_text(r[0]) == "区分")
            heads = [[cell_text(c) for c in r] for r in rows[:hi + 1]]
            total_col = next(j for r in heads for j, h in enumerate(r) if h in ("児童数", "生徒数"))
            grades = {int(g.group(1)): j for j, h in enumerate(heads[hi]) if j > total_col and (g := re.fullmatch(r"(\d)年", h))}
            public, muni = False, None
            for r in rows[hi + 1:]:
                label = cell_text(r[0]) if r else ""
                if not label:
                    continue
                if label == "公立計":
                    public = True
                    continue
                if label in ("国立計", "私立計"):
                    public = False
                    continue
                if not public or label.endswith("立計"):
                    continue
                if cell_text(r[1]):          # 市町村の見出し行（学校数）
                    muni = label
                    continue
                n = cell_int(r[total_col])
                if not n or muni is None:
                    continue
                name = label.replace("曾", "曽")    # 「富曾亀」→ 正式名「富曽亀小学校」
                if m := re.fullmatch(r"(.+)\((.+)\)", name):
                    name = f"{m.group(1)}{kind}{m.group(2)}分校"
                g = {f"{k}年": cell_int(r[j]) or 0 for k, j in sorted(grades.items())}   # 「-」は 0 人
                if sum(g.values()) != n:
                    g = {}
                out.append(SchoolCount(pref="15", municipality=muni, name=name, school_type=school_type,
                                       year=cfg["school_year"], total=n, grades=g))
    return out
