import re
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text, workbook

# 所属名の頭（「松江･母衣小」の「松江」）→ 設置者の市町村。郡の略称で町村が1つに決まらないもの
# （邑智郡＝川本町・美郷町・邑南町、隠岐郡＝海士町・西ノ島町・知夫村・隠岐の島町、鹿足郡＝津和野町・吉賀町）は ""
# （突き合わせは県内で種類と名前が同じ学校が1つだけのとき）。
MUNICIPALITIES = {"松江": "松江市", "出雲": "出雲市", "安来": "安来市", "雲南": "雲南市", "浜田": "浜田市",
                  "益田": "益田市", "大田": "大田市", "江津": "江津市", "飯石": "飯石郡飯南町", "仁多": "仁多郡奥出雲町",
                  "邑智": "", "隠岐": "", "鹿足": ""}
ZEN = str.maketrans("０１２３４５６７８９", "0123456789")


def read_shimane(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """島根県「島根県公立小中学校児童生徒数学級数」（しまねオープンデータカタログ、2026-10-17 に取得して確認）。

    ファイルは小学校（elementary.xlsx、シート「小学校」）と中学校（junior_high.xlsx、シート「中学校」）。
    1行目「令和８年度児童数・学級数（小学校）」、2行目「R8.5.1現在」、3行目「№ | 所属名 | 1年 | … | 6年 | 合計 | 合計（学級数）」
    （中学校は「1年」〜「3年」）、4行目から1行1校、最後に「合計」の行。
    所属名は「松江･母衣小」「隠岐・北小」の形（市町村・郡の略称＋「･」＋学校名の略称）。「小」「中」を「小学校」「中学校」に、
    分校は「来待小大野原分校」→「来待小学校大野原分校」にする。郡の略称のうち町村が1つに決まらない邑智・隠岐・鹿足の学校は
    設置者を "" にする（住所の列はない）。
    義務教育学校は小学校のファイルに「八束学園（前期課程）」、中学校のファイルに「八束学園（後期課程）」と分かれて載るので、
    1校（compulsory）にまとめ、前期の1〜6年を「1年」〜「6年」、後期の1〜3年を「7年」〜「9年」にする。
    休校の分校は全学年0で載る（令和8年度は出雲･神戸川小若松分校）ので行を出さない。
    年度は1行目の「令和８年度」から読み、cfg の school_year と違えば例外にする。
    """
    out: list[SchoolCount] = []
    courses: dict[tuple, dict] = {}   # 義務教育学校: (設置者, 名前) → {"前期": 行, "後期": 行}
    for f in files:
        for _, rows in workbook(f):
            title = cell_text(rows[0][0]) if rows and rows[0] else ""
            m = re.search(r"令和(\d+|元)年度.*\((小学校|中学校)\)", title.translate(ZEN))
            if not m:
                continue
            year = 2018 + (1 if m.group(1) == "元" else int(m.group(1)))
            if year != cfg["school_year"]:
                raise ValueError(f"{f.name}: 表の年度が {year} で、設定の {cfg['school_year']} と違う")
            head = [cell_text(h) for h in rows[2]]
            grade_cols = {int(g.group(1)): i for i, h in enumerate(head) if (g := re.fullmatch(r"(\d)年", h))}
            total_col = head.index("合計")      # 最初の「合計」が人数（2つ目は学級数）
            school_type = "elementary" if m.group(2) == "小学校" else "junior_high"
            for r in rows[3:]:
                name = cell_text(r[1]) if len(r) > 1 else ""
                if not (nm := re.fullmatch(r"(.+?)・(.+)", name)):
                    continue
                abbr, school = nm.groups()
                if abbr not in MUNICIPALITIES:
                    raise ValueError(f"{f.name}: 所属名「{name}」の市町村の略称が分からない")
                total = cell_int(r[total_col])
                grades = {k: cell_int(r[i]) for k, i in sorted(grade_cols.items())}
                if total is None or total == 0:
                    continue          # 休校（全学年0）
                if any(v is None for v in grades.values()) or sum(grades.values()) != total:
                    grades = {}
                muni = MUNICIPALITIES[abbr]
                if (c := re.fullmatch(r"(.+?)\((前期|後期)課程\)", school)):
                    courses.setdefault((muni, c.group(1)), {})[c.group(2)] = (total, grades, year)
                    continue
                out.append(SchoolCount(pref="32", municipality=muni, name=_full_name(school, school_type),
                                       school_type=school_type, year=year, total=total,
                                       grades={f"{k}年": v for k, v in grades.items()}))
    for (muni, name), parts in courses.items():
        total = sum(p[0] for p in parts.values())
        grades = {}
        if set(parts) == {"前期", "後期"} and parts["前期"][1] and parts["後期"][1]:
            grades = {f"{k}年": v for k, v in parts["前期"][1].items()}
            grades.update({f"{k + 6}年": v for k, v in parts["後期"][1].items()})
        if set(parts) != {"前期", "後期"}:
            raise ValueError(f"島根県: 義務教育学校 {name} の前期課程・後期課程の片方しかない")
        out.append(SchoolCount(pref="32", municipality=muni, name=name, school_type="compulsory",
                               year=parts["前期"][2], total=total, grades=grades))
    return out


def _full_name(school: str, school_type: str) -> str:
    """「母衣小」→「母衣小学校」、「来待小大野原分校」→「来待小学校大野原分校」、「第三中」→「第三中学校」。"""
    word = "小" if school_type == "elementary" else "中"
    m = re.fullmatch(rf"(.+?){word}(?:学校)?(.*分校)?", school)
    if not m:
        return school
    return f"{m.group(1)}{word}学校{m.group(2) or ''}"
