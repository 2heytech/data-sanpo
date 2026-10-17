import re
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text, workbook

TYPE_SHEETS = {"小学校": "elementary", "中学校": "junior_high", "義務教育学校": "compulsory"}
TYPE_WORD = {"elementary": "小学校", "junior_high": "中学校", "compulsory": ""}
ZEN = str.maketrans("０１２３４５６７８９", "0123456789")
# 郡の町（郡の学校の設置者。所在地の頭の町名で決める）
TOWNS = {"桑名郡": ["木曽岬町"], "員弁郡": ["東員町"], "三重郡": ["菰野町", "朝日町", "川越町"],
         "多気郡": ["多気町", "明和町", "大台町"], "度会郡": ["玉城町", "度会町", "大紀町", "南伊勢町"],
         "北牟婁郡": ["紀北町"], "南牟婁郡": ["御浜町", "紀宝町"]}


def _reiwa_year(rows: list[list]) -> int | None:
    """「（令和８年５月１日現在）」「令和 ８年 度」から西暦の年度。"""
    for r in rows:
        for c in r:
            s = cell_text(c).translate(ZEN)
            m = re.search(r"令和(\d+|元)年5月1日現在", s) or re.search(r"令和(\d+|元)年度", s)
            if m:
                return 2018 + (1 if m.group(1) == "元" else int(m.group(1)))
    return None


def read_mie(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """三重県教育委員会「学校名簿」の Excel 版（2026-10-17 に取得して確認。令和8年度版、1ファイルに全校種）。

    形式: シートは冊子のページ番号ごと（「9-20」が小学校、「21-27」が中学校、「28」が義務教育学校。
    ページ数は年度で変わるので、シートは1行目の「（３）小学校」「（４）中学校」「（５）義務教育学校」で選ぶ。
    国立は「（２）小学校（本校1）」、私立は別の見出しなので選ばれない）。
    市・郡ごとに「桑名市（本校23　分校1）」「南牟婁郡（本校9）」の見出し行、「学校名 | ふりがな | 郵便番号 |
    所在地 | 電話 | Fax | 校長 | 児童数（生徒数）| 学級数 | 教員数」の見出し、1行1校、「計」の行が続く。
    学校名は「日進」のように種類なし。所在地は市の学校は市名を除いた形（「新屋敷126」）、郡の学校は町名から
    （「木曽岬町田代160」）。郡の学校の設置者は所在地の頭の町名（TOWNS）とする。令和8年度は大紀中学校の所在地が
    「滝原1889-7」と町名なしなので、同じ郵便番号の郡の学校（大宮小学校＝大紀町）の町にする。決まらなければ設置者は ""。
    1列目の印: ☆＝休校（数は「－」。行を出さない）、〇＝分校（直前の本校の名前を付けて「伊曽島小学校悠分校」にする）、
    △＝学校組合立。
    義務教育学校は学校名の行の下に「前期課程」「後期課程」の行があり、その数を足して総数にする。
    学年別はない（grades は {}）。校長名の列は読まない。

    注意: 同じ URL（/common/content/001153699.xlsx）のまま毎年中身が書き換わる。年度は「凡例」シートの
    「（令和８年５月１日現在）」（なければ表紙の「令和８年度」）から読み、cfg の school_year と違えば例外にする。
    """
    out: list[SchoolCount] = []
    for f in files:
        sheets = workbook(f)
        year = None
        for name, rows in sheets:
            if name in ("凡例", "表紙", "裏表紙"):
                year = year or _reiwa_year(rows)
        if year is None:
            raise ValueError(f"{f.name}: 学校名簿の年度（令和○年５月１日現在）が見つからない")
        if year != cfg["school_year"]:
            raise ValueError(f"{f.name}: 学校名簿の年度が {year} で、設定の {cfg['school_year']} と違う"
                             "（同じ URL のまま中身が書き換わる出典）")
        raw = []
        for name, rows in sheets:
            title = next((cell_text(c) for r in rows[:2] for c in r if cell_text(c)), "")
            m = re.fullmatch(r"\(\d\)(小学校|中学校|義務教育学校)", title)
            if m:
                raw.extend(_read_sheet(rows, TYPE_SHEETS[m.group(1)]))
        # 郡の学校で所在地に町名がない行（令和8年度の大紀中学校「滝原1889-7」）は、同じ郵便番号の学校の町にする
        postal = {}
        for area, _, _, _, addr, zip_ in raw:
            if (t := _town(area, addr)) and zip_:
                postal.setdefault(zip_, t)
        for area, name, school_type, total, addr, zip_ in raw:
            if area.endswith("郡"):
                town = _town(area, addr)
                if town:
                    municipality, address = area + town, addr
                elif zip_ in postal:
                    municipality, address = area + postal[zip_], postal[zip_] + addr
                else:
                    municipality, address = "", None   # 町が分からない（突き合わせは県内で名前が1つだけの学校）
            else:
                municipality, address = area, area + addr if addr else None
            out.append(SchoolCount(pref="24", municipality=municipality, name=name, school_type=school_type,
                                   year=year, total=total, grades={}, address=address))
    return out


def _town(area: str, addr: str) -> str | None:
    return next((t for t in TOWNS.get(area, []) if addr.startswith(t)), None)


def _read_sheet(rows: list[list], school_type: str) -> list[tuple]:
    """(市・郡, 学校名, 種類, 総数, 所在地, 郵便番号) の一覧。"""
    out = []
    area = None          # 「桑名市」「南牟婁郡」
    col = {}             # 見出しの列
    parent = None        # 分校の本校の名前
    pending = None       # 義務教育学校: [名前, 所在地, [前期, 後期], 郵便番号]

    def flush():
        nonlocal pending
        if pending and pending[2] and all(n is not None for n in pending[2]):
            out.append((area, pending[0], school_type, sum(pending[2]), pending[1], pending[3]))
        pending = None

    for r in rows:
        c = [cell_text(x) for x in r]
        if not any(c):
            continue
        if (m := re.fullmatch(r"(.+?[市郡])\(本校\d+(?:分校\d+)?\)", "".join(c))):
            flush()
            area, parent = m.group(1), None
            continue
        if len(c) > 1 and c[1] == "学校名":
            col = {"addr": next(i for i, h in enumerate(c) if h == "所在地"),
                   "zip": next(i for i, h in enumerate(c) if h == "郵便番号"),
                   "n": next(i for i, h in enumerate(c) if h in ("児童数", "生徒数"))}
            continue
        if area is None or not col:
            continue
        r = list(r) + [None] * (col["n"] + 1 - len(r))
        c = c + [""] * (len(r) - len(c))
        mark, name = c[0], c[1]
        if not name or re.fullmatch(r"合?計", name):
            flush()
            continue
        if school_type == "compulsory":
            if name in ("前期課程", "後期課程"):
                if pending is not None:
                    pending[1] = pending[1] or c[col["addr"]]
                    pending[3] = pending[3] or c[col["zip"]]
                    pending[2].append(cell_int(r[col["n"]]))
                continue
            flush()
            if "☆" not in mark:
                pending = [name, c[col["addr"]], [], ""]
            continue
        if "〇" in mark or "○" in mark:
            full = f"{parent}{TYPE_WORD[school_type]}{name}" if parent else name
        else:
            parent = name
            full = name + TYPE_WORD[school_type]
        if "☆" in mark:
            continue          # 休校（数は「－」）
        n = cell_int(r[col["n"]])
        if n is None:
            continue
        out.append((area, full, school_type, n, c[col["addr"]], c[col["zip"]]))
    flush()
    return out

