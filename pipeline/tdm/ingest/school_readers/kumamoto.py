import re
import unicodedata
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text, workbook

TYPE_WORD = {"elementary": "小学校", "junior_high": "中学校", "compulsory": "義務教育学校"}
ADDR_MUNI = re.compile(r"^(.+?郡.+?[町村]|.+?市|.+?[町村])")


def _address(cell) -> str | None:
    """住所のセル。校舎が2つある学校は改行で2つ書かれる（「…丙22-1（北校舎）\\n…丙123（南校舎）」）ので最初の1つ。"""
    if cell is None:
        return None
    first = unicodedata.normalize("NFKC", str(cell)).split("\n")[0]
    return re.sub(r"\([^)]*校舎\)$", "", cell_text(first)) or None


def read_kumamoto(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """熊本県「学校一覧」（BODIK、熊本県教育庁教育政策課、CC BY 4.0）の「1-4 小学校」「1-3 中学校」「1-5 義務教育学校」
    の xlsx。2026-10-17 に取得して確認（R8.1.26 版。値は令和7年（2025年）5月1日現在）。熊本市立の学校も含む。

    形式: シート1枚（「4 小学校」「3 中学校」「5 義務教育学校」）。1行目に「令和7年（2025年）5月1日現在」（年度はここから読む。
    読めなければ cfg["school_year"]）。区分ごとに「小学校（熊本市）」「小学校（宇城）」…（教育事務所別）、「中学校（県立）」
    「中学校（私立）」「小学校（国立大学法人）」の見出し行と列の見出し行（設置者, 学校名, へき地, 郵便番号, 住所, 電話番号,
    学校長名, 教員数, 児童数（中学校は生徒数、義務教育学校は児童・生徒数）, （再掲）, 学級数, （再掲））が繰り返し、
    その下に1行1校（0列目が通し番号）、区分の終わりに小計の行。
    学校名は「壺　　川」「玉名高等学校附属」のように「小学校」「中学校」を付けない略称（空白は除く）。学年別はない。

    注意:
    - 児童数・学級数の右の列は「（ ）は学校教育法第81条の学級再掲」（特別支援学級の再掲）。総数に含まれているので足さない。
      県立・国立の区分には再掲の列がなく、列の位置が変わるので、列は区分ごとの見出し行から決める。
    - 学校長名の列は読まない。
    - 私立・国立大学法人の区分は読まない。県立の中学校（宇土・玉名高等学校附属・八代・ゆうあい（夜間中学））は
      founder="都道府県立"、municipality は所在地の市名（宇土市など）。
    - 組合立（「氷川町及び八代市中学校組合」）は設置者の名前のまま（P29 の「〇〇組合立氷川中学校」と対応する）。
    - 休校は児童数などが「-」（多良木町の宮ヶ野・槻木）、分校の休校は 0（水俣第一の浜分校）。どちらも出さない。
    - 分校は「弥次分校」「柳野分校」「清水が丘分校」のように分校名だけが本校の次の行にあるので、
      「金剛小学校弥次分校」のように本校名を付ける（P29 の「八代市立金剛小学校弥次分校」と同じ形）。
    - 校舎が2つある学校（球磨清流学園）は住所が改行で2つ書かれるので、最初の住所にする。
    """
    out = []
    for f in files:
        m = re.search(r"(elementary|junior_high|compulsory)", f.name)
        for sheet, rows in workbook(f):
            school_type = m.group(1) if m else (
                "compulsory" if "義務教育" in sheet else "junior_high" if "中学校" in sheet else "elementary")
            year = cfg["school_year"]
            section, cols, prev = "", None, ""
            for r in rows:
                cells = [cell_text(c) for c in r]
                if (y := next((re.search(r"\((\d{4})年\)5月1日現在", c) for c in cells if "5月1日現在" in c), None)):
                    year = int(y.group(1))
                if "学校名" in cells:          # 列の見出し行
                    cols = {h: i for i, h in enumerate(cells) if h}
                    total = next(i for h, i in cols.items() if h in ("児童数", "生徒数", "児童・生徒数"))
                    continue
                if len(cells) > 1 and re.search(r"学校\((.+)\)$", cells[1]) and not (len(cells) > 2 and cells[2]):
                    section = re.search(r"学校\((.+)\)$", cells[1]).group(1)   # 区分の見出し行
                    prev = ""
                    continue
                if cols is None or not isinstance(r[0], (int, float)):
                    continue                    # 小計・空行
                if "私立" in section or "国立" in section:
                    continue
                founder = cells[cols["設置者"]]
                name = cells[cols["学校名"]]
                if name.endswith("分校") and prev:
                    name = prev + TYPE_WORD[school_type] + name
                else:
                    prev = name
                n = cell_int(r[total])
                if not n:                       # 休校（「-」）・在籍0の分校
                    continue
                pref_school = founder == "県立" or section == "県立"
                address = _address(r[cols["住所"]])
                if pref_school:
                    founder = am.group(1) if (am := ADDR_MUNI.match(address or "")) else ""
                out.append(SchoolCount(pref="43", municipality=founder, name=name,
                                       school_type=school_type, year=year, total=n, address=address,
                                       founder="都道府県立" if pref_school else "市区町村立"))
    return out
