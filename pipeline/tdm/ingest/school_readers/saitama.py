import re
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text, workbook

TYPE_BY_HEAD = {"児童数計": "elementary", "生徒数計": "junior_high", "児童生徒数計": "compulsory"}


def read_saitama(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """埼玉県教育委員会「埼玉県学校便覧」名簿の部（公立学校）の xlsx。2026-10-17 に令和8年度版を取得して確認。

    保存名: elementary.xlsx（小学校・市町村立）, junior_high.xlsx（中学校・市町村立）,
    junior_high_pref.xlsx（中学校・県立）, compulsory.xlsx（義務教育学校）。1ファイル1シート。
    形式: 1〜3行目が題名（「令和８年度 埼玉県学校便覧」「（１）小学校（市町村立）」）、4行目が見出し、5行目から1行1校。
      見出し: [教育事務所等,] 設置者, 学校名（「高砂小」「岸中」の略称、義務教育学校は「武蔵台小中学校」）,
      学校名フリガナ, 学校コード（13桁）, 所属所コード, 郵便番号, 住所（「埼玉県さいたま市浦和区岸町4-1-29」、郡名なし）,
      電話番号, FAX番号, 校長名, 教員数, 職員数, 学級数（単式・特別支援・複式）,
      1学年児童数 … 6学年児童数, 児童数計（中学校は「1学年生徒数」…「生徒数計」、義務教育学校は
      「1学年児童数」…「6学年児童数」「7学年生徒数」…「9学年生徒数」「児童生徒数計」）。
      県立中学校の表には「教育事務所等」の列がなく、設置者は「埼玉県」。
    注意:
      - 学級数（特別支援）は学級の数で、児童生徒数は学年別に含まれる（再掲の列はない）。総数は「…数計」をそのまま使う。
      - 休校の学校は全列 0 で載る（例: ふじみ野市 東台小、熊谷市 小島小・小島中）。総数 0 の行は出さない。
      - 末尾に「公立小学校 計」などの合計行（学校コードが「－」）がある。学校コードが13桁でない行は読まない。
      - 夜間中学（例: 川口市「芝園学園中陽春分校」）は分校として学校コード付きで載る。そのまま1校として読む。
      - 校長名は読まない。「…数計」の見出しで学校の種類を判断する（保存名には頼らない）。
      - 学年別の合計が総数と合わない行は grades を {} にする（令和8年度版にはない）。
    """
    out = []
    for f in files:
        for _sheet, rows in workbook(f):
            hi = next((i for i, r in enumerate(rows[:10]) if "学校コード" in [cell_text(c) for c in r]), None)
            if hi is None:
                continue
            head = [cell_text(c) for c in rows[hi]]
            ti, school_type = next((i, TYPE_BY_HEAD[h]) for i, h in enumerate(head) if h in TYPE_BY_HEAD)
            grades = {int(g.group(1)): i for i, h in enumerate(head) if (g := re.fullmatch(r"(\d)学年(?:児童|生徒)数", h))}
            col = {h: head.index(h) for h in ("設置者", "学校名", "学校コード", "住所")}
            for r in rows[hi + 1:]:
                r = list(r) + [None] * (len(head) - len(r))
                code = cell_text(r[col["学校コード"]])
                if not re.fullmatch(r"[BC][12]\d{11}", code):
                    continue   # 合計行・空行
                total = cell_int(r[ti])
                if not total:
                    continue   # 休校（全列 0）・読めない値
                g = {f"{k}年": cell_int(r[i]) for k, i in sorted(grades.items())}
                if any(v is None for v in g.values()) or sum(g.values()) != total:
                    g = {}
                founder = cell_text(r[col["設置者"]])
                address = re.sub(r"^埼玉県", "", cell_text(r[col["住所"]])) or None
                pref_run = founder == "埼玉県"
                if pref_run:
                    m = re.match(r"^(.+?郡.+?[町村]|.+?市|.+?[町村])", address or "")
                    muni = m.group(1) if m else ""
                else:
                    muni = founder
                out.append(SchoolCount(pref="11", municipality=muni, name=cell_text(r[col["学校名"]]),
                                       school_type=school_type, year=cfg["school_year"], total=total, grades=g,
                                       code=code, address=address,
                                       founder="都道府県立" if pref_run else "市区町村立"))
    return out
