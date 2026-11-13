import re
from collections import defaultdict
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text, workbook

TYPES = {"小学校": "elementary", "中学校": "junior_high", "義務教育学校": "compulsory"}


def read_saga_city(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """佐賀市「佐賀市立小学校中学校児童生徒数」（BODIK、CC BY 4.0）の xlsx。保存名 students.xlsx（小学校・中学校が1ファイル）。
    年度ごとに1ファイル（R3〜R8年度）。

    形式（2026-10-17 に取得して確認）:
      シート1枚（Sheet1）。1行目が見出し: 学校種別, 学校名, 学年, 児童生徒数_通常学級, 児童生徒数_特別支援学級,
      学級数_通常学級, 複式学級フラグ, 複式学級編成学年, 少人数学級選択フラグ, 学級数_特別支援学級, 特別支援学級編成学年。
      2行目から1行が1校1学年（小学校は学年1〜6の6行、中学校は1〜3の3行）。
      学校種別は「小学校」「中学校」、学校名は「勧興」「成章」のように「小学校」「中学校」を除いた形。
    学年の人数は 通常学級＋特別支援学級（特別支援学級は再掲ではない）。総数は学年の合計。
    表に年月日はないので年度は cfg["school_year"]（リソース名「R8年度」、ファイル名 412015_school_students_2026.xlsx）。
    R7年度のファイルの小学校の合計（11,808人）は学校基本調査（令和7年5月1日現在）の佐賀市の公立小学校の児童数と一致する
    ので、各年度5月1日現在の値とみる。

    注意:
      - 学年の人数が読めない学校は出さない（総数を作れないため。0 にはしない）。総数0の学校も出さない（2026年度はない）。
      - 学級数・複式・少人数学級の列は読まない。
      - 学校コード・所在地はない。2026年度の表に義務教育学校はない（あれば学校種別から compulsory にする）。
    """
    out = []
    for f in files:
        for _, rows in workbook(f):
            if not rows:
                continue
            head = [cell_text(h) for h in rows[0]]
            if "学校種別" not in head:
                continue
            col = {h: i for i, h in enumerate(head)}
            schools: dict[tuple, dict] = defaultdict(dict)
            for r in rows[1:]:
                kind = TYPES.get(cell_text(r[col["学校種別"]]))
                name = cell_text(r[col["学校名"]])
                grade = cell_text(r[col["学年"]])
                if not kind or not name or not re.fullmatch(r"\d", grade):
                    continue
                a = cell_int(r[col["児童生徒数_通常学級"]])
                b = cell_int(r[col["児童生徒数_特別支援学級"]])
                schools[(kind, name)][f"{grade}年"] = None if a is None or b is None else a + b
            for (kind, name), grades in schools.items():
                if any(v is None for v in grades.values()):
                    continue
                n = sum(grades.values())
                if n <= 0:
                    continue
                if kind != "compulsory" and not name.endswith("学校"):
                    name += "小学校" if kind == "elementary" else "中学校"
                out.append(SchoolCount(pref="41", municipality="佐賀市", name=name, school_type=kind,
                                       year=cfg["school_year"], total=n,
                                       grades=dict(sorted(grades.items(), key=lambda x: int(x[0][:-1])))))
    return out
