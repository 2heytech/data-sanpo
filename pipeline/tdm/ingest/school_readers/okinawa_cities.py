"""沖縄県内の市が BODIK ODCS（https://data.bodik.jp/）に CC BY 4.0 で出している、学校別の児童・生徒数の読み方。

県の学校別の数（学校基本調査の速報）は商用利用の条件が明示されていないので、市ごとに読む。2024年度以降の学校別の数が
あるのは沖縄市（統計書）と石垣市（統計いしがき）。どちらも市の統計書の表で、値は学校基本調査（5月1日現在）。
形式は 2026-10-17 に取得して確認したもの。
"""
import csv
import io
import re
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text

PREF = "47"


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


def read_okinawashi(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """沖縄市「沖縄市統計書_分野11_文教」の「4．小学校学年別学級数および児童数」「6．市立中学校学年別学級数および
    生徒数」の CSV（UTF-8 BOM 付き。小学校・中学校で別ファイル）。縦持ちの表で、列は 年次, 学校名, 種別, 値。
    年次は「2023/05/01」「2024/05/01」の2年分（令和6年度版）。cfg["school_year"] の年の行だけ読む。
    学校名は「越来」「越来中」の略称（小学校は「小学校」を、中学校は「学校」を付ける）。「総数」の行（市の合計）は読まない。
    小学校の種別: 「総数 児童数 小計」（総数）、「N学年 児童数 小計」（学年別）、「… 特別支援学級・児童数 小計」
    （特別支援学級の再掲。足さない）、「… 男」「… 女」「… 学級数」。中学校の種別: 「総数 総数」（総数）、「N学年 計」
    （学年別）、「… 特別支援学級・生徒数 …」（再掲）。学年の和は総数と同じ（特別支援学級を含む）。"""
    year = int(cfg["school_year"])
    out = []
    for f in files:
        rows = _csv(f)
        head = [cell_text(h) for h in rows[0]]
        i_year, i_name, i_kind, i_val = (head.index(h) for h in ("年次", "学校名", "種別", "値"))
        kinds = {cell_text(r[i_kind]) for r in rows[1:]}
        if "総数児童数小計" in kinds:
            school_type, total_key, grade_key, n = "elementary", "総数児童数小計", "{}学年児童数小計", 6
        elif "総数総数" in kinds:
            school_type, total_key, grade_key, n = "junior_high", "総数総数", "{}学年計", 3
        else:
            raise ValueError(f"{f.name}: 総数の種別がない")
        vals: dict[str, dict[str, int | None]] = {}
        for r in rows[1:]:
            if not cell_text(r[i_year]).startswith(f"{year}/"):
                continue
            name = cell_text(r[i_name])
            if not name or name == "総数":
                continue
            vals.setdefault(name, {})[cell_text(r[i_kind])] = cell_int(r[i_val])
        for name, v in vals.items():
            total = v.get(total_key)
            if total is None:
                continue
            g = [v.get(grade_key.format(k)) for k in range(1, n + 1)]
            grades = {f"{k}年": x for k, x in enumerate(g, 1)} if None not in g and sum(g) == total else {}
            full = name + ("小学校" if school_type == "elementary" else "学校" if name.endswith("中") else "中学校")
            out.append(SchoolCount(pref=PREF, municipality="沖縄市", name=full, school_type=school_type,
                                   year=year, total=total, grades=grades))
    return out


ISHIGAKI_NAMES = {"石垣二": "石垣第二"}   # 統計いしがきの略称 → 学校名


def read_ishigaki(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """石垣市「【令和6年度統計いしがき】教育および文化」の「12-6．小学校別学年別学級数および児童数」「12-8．中学校別
    学年別学級数および生徒数」の CSV（UTF-8 BOM 付き。令和6年5月1日現在、資料は令和6年度学校基本調査）。
    1行目は表題、2行目: 区分, 1学年, , , , 2学年 …, 特別支援学級（小学校は「(再掲）」付き）, , 総計。
    3行目: (空), 男, 女, 計, 学級数 …（特別支援学級は 児童数（生徒数）, 学級数）。4行目から1行1校で、「計」の行と
    注記の行（「（単位：クラス、人）」）がある。学校名は「富　野」「石垣二」のように「小学校」「中学校」がなく、間に
    全角空白が入ることがある（cell_text で除き、「石垣二」は「石垣第二中学校」に直す）。総数は「総計」の「計」、
    学年別は各学年の「計」。特別支援学級は再掲（学年の数に含まれる）なので足さない。"""
    out = []
    for f in files:
        rows = _csv(f)
        top = [cell_text(c) for c in rows[1]]
        sub = [cell_text(c) for c in rows[2]]
        groups, cur = {}, None
        for i, h in enumerate(top):
            if h:
                cur = h
            if cur and i < len(sub) and sub[i] == "計":
                groups[cur] = i
        grade_cols = {int(m.group(1)): i for k, i in groups.items() if (m := re.fullmatch(r"(\d)学年", k))}
        total_col = groups["総計"]
        kind = "elementary" if len(grade_cols) == 6 else "junior_high" if len(grade_cols) == 3 else None
        if kind is None:
            raise ValueError(f"{f.name}: 学年の列が6でも3でもない")
        for r in rows[3:]:
            name = cell_text(r[0])
            total = cell_int(r[total_col]) if len(r) > total_col else None
            if not name or name == "計" or total is None:
                continue
            name = ISHIGAKI_NAMES.get(name, name)
            g = [cell_int(r[grade_cols[k]]) for k in sorted(grade_cols)]
            grades = {f"{k}年": v for k, v in enumerate(g, 1)} if None not in g and sum(g) == total else {}
            out.append(SchoolCount(pref=PREF, municipality="石垣市",
                                   name=name + ("小学校" if kind == "elementary" else "中学校"),
                                   school_type=kind, year=cfg["school_year"], total=total, grades=grades))
    return out

