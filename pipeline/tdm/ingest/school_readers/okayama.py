import re
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text, workbook

KANJI = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
TYPES = {"小学校": "elementary", "中学校": "junior_high", "義務教育学校": "compulsory"}
TYPE_WORD = {"elementary": "小学校", "junior_high": "中学校", "compulsory": ""}


def read_okayama(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """岡山県教育委員会「公立学校一覧【在学者数・教職員数】」の令和8年度の Excel（2026-10-17 に取得して確認）。

    ファイルは小学校（elementary.xlsx）・中学校（junior_high.xlsx）・義務教育学校（compulsory.xlsx）。
    種類は1行目の「公立小学校一覧（令和８年５月１日現在）」で判断し、年度もここから読む（cfg の school_year と違えば例外）。
    小学校・中学校: 2〜4行目が見出し（番号 | 学校名 | 郵便番号 | 所在地 | 電話番号 | 設置者 | 校長名 | 児童数（一学年〜六学年、
    計の男・女・計）| 特別支援学級児童数（再掲）| 学級数 | 教職員数…）。市・郡ごとに「岡 山 市 (本校85 分校2)」の見出し行、
    1行1校、「計」の行。学校名は「足守」のように種類なし。設置者は「〃」で上の行と同じ。所在地は市の学校は市名を除いた形
    （「北区足守789」）、郡の学校は町村名から。学校名に注の印が付くことがある（「作東(※)」→「作東」）。中学校には県立（設置者「岡山県」、岡山操山など）と組合立
    （「笠岡市矢掛町中学校組合」）があり、市区町村はその市の見出しから取る。分校は「迫川分校」の形で本校の次の行にあり、
    「灘崎小学校迫川分校」にする。休校は校長名の列が「(休校)」で人数がすべて0なので行を出さない。
    義務教育学校: 1校4行（本務・兼務の教職員の行と空行）。所在地の列は「〒704-8134 岡山市東区 北幸田509-1」の形
    （郵便番号を除き、前期課程・後期課程で所在地が分かれるときは前期課程の所在地）。学年は「1学年」〜「９学年」の男・女の2列ずつ。
    特別支援学級の人数（再掲）は学年別に含まれているので足さない。総数は「計」の男・女の次の列（学年別の合計と一致）。
    校長名の列は読まない。
    """
    out: list[SchoolCount] = []
    for f in files:
        for _, rows in workbook(f):
            title = cell_text(rows[0][0]) if rows and rows[0] else ""
            m = re.fullmatch(r"公立(小学校|中学校|義務教育学校)一覧\(令和(\d+|元)年5月1日現在\)", title)
            if not m:
                continue
            year = 2018 + (1 if m.group(2) == "元" else int(m.group(2)))
            if year != cfg["school_year"]:
                raise ValueError(f"{f.name}: 表の年度が {year} で、設定の {cfg['school_year']} と違う")
            out.extend(_read_sheet(rows, TYPES[m.group(1)], year))
    return out


def _read_sheet(rows: list[list], school_type: str, year: int) -> list[SchoolCount]:
    h1, h2, h3 = ([cell_text(c) for c in rows[i]] + [""] * 60 for i in (1, 2, 3))
    col = {k: h1.index(k) for k in ("学校名", "所在地", "設置者")}
    grades = {}      # 学年 → [列]（男・女に分かれていれば2列）
    for i, h in enumerate(h2):
        if (g := re.fullmatch(r"([一二三四五六七八九]|\d)学年", h)):
            k = KANJI.get(g.group(1)) or int(g.group(1))
            grades[k] = [i, i + 1] if h3[i] == "男" and h3[i + 1] == "女" else [i]
    total_col = h2.index("計", max(c[-1] for c in grades.values()))   # 学年の右の「計」（男・女・計）
    out = []
    area, founder, parent = None, "", None
    for r in rows[4:]:
        c = [cell_text(x) for x in r] + [""] * 60
        r = list(r) + [None] * 60
        if (m := re.fullmatch(r"(.+?[市郡])\(本校\d+(?:分校\d+)?\)", c[0])):
            area, parent = m.group(1), None
            continue
        name = re.sub(r"\(?※\)?", "", c[col["学校名"]])   # 「作東(※)」の注の印
        if not re.fullmatch(r"\d+", c[0]) or not name:
            continue
        if c[col["設置者"]] and c[col["設置者"]] != "〃":
            founder = c[col["設置者"]]
        g = {k: _sum(r, cols) for k, cols in sorted(grades.items())}
        men, women, total = (cell_int(r[total_col + i]) for i in range(3))
        if total is None and men is not None and women is not None:
            total = men + women
        if not total:
            continue          # 休校（人数がすべて0）
        if any(v is None for v in g.values()) or sum(g.values()) != total:
            g = {}
        if school_type == "compulsory":
            full = name
        elif name.endswith("分校"):
            full = f"{parent}{TYPE_WORD[school_type]}{name}" if parent else name
        else:
            parent, full = name, name + TYPE_WORD[school_type]
        pref_school = founder in ("岡山県", "県")
        if pref_school or founder.endswith("組合"):
            municipality = area if area and area.endswith("市") else ""
        else:
            municipality = founder
        addr = _address(c[col["所在地"]])
        if addr and municipality and not re.match(rf"(.+?郡)?{re.escape(municipality)}", addr):
            addr = municipality + addr
        out.append(SchoolCount(pref="33", municipality=municipality, name=full, school_type=school_type, year=year,
                               total=total, grades={f"{k}年": v for k, v in g.items()}, address=addr or None,
                               founder="都道府県立" if pref_school else "市区町村立"))
    return out


def _sum(r: list, cols: list[int]) -> int | None:
    vals = [cell_int(r[i]) for i in cols]
    return None if any(v is None for v in vals) else sum(vals)


def _address(s: str) -> str:
    """「〒704-8134岡山市東区北幸田509-1」→「岡山市東区北幸田509-1」。前期課程・後期課程で分かれていれば前期課程。"""
    s = re.sub(r"〒?\d{3}-\d{4}", "", s)
    if (m := re.search(r"\(前期課程\)(.+?)(?:\(後期課程\)|$)", s)):
        s = m.group(1)
    return s
