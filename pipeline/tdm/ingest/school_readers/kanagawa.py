import re
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text, workbook

SHEET_TYPES = (("義務教育学校", "compulsory"), ("小学校", "elementary"), ("中学校", "junior_high"))


def read_kanagawa(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """神奈川県教育委員会「神奈川の教育統計（令和７年度 公立小・中学校等の児童・生徒数、学級数、教職員数及び
    公立高等学校等（全日制・定時制）の生徒数、学級数一覧）」の xlsx（神奈川県オープンデータカタログ、CC BY 4.0）。
    2026-10-17 に令和7年度版（令和7年5月1日現在）を取得して確認。令和8年度版はカタログに未掲載。

    保存名: elementary.xlsx（公立小学校）, junior_high.xlsx（公立中学校）, compulsory.xlsx（公立義務教育学校）。
    シート: 「Ｒ７公立小学校 児童数（市町村別）」「… 児童数（学校別）」「… 学級数（市町村別）」「… 学級数（学校別）」。
      「児童数（学校別）」「生徒数（学校別）」「児童・生徒数（学校別）」のシートだけ読む（学校の種類はシート名で判断）。
    形式: 1行目が題名（「令和７年５月１日現在」）、2〜3行目が2段の見出し、4行目から1行1校。A列は空。
      列: 学校コード（13桁）, 設置者（「横浜市」「大磯町」。郡名なし）, 所在市区町村（「101横浜市鶴見区」「341大磯町」。
      先頭3桁は県の市区町村番号）, 学校名（「旭」「市場けやき分校」の略称。「小学校」などは付かない）,
      児童数（生徒数）の 合計, １学年 … ６学年（中学校は３学年、義務教育学校は９学年）。所在地（番地）の列はないので、address は所在市区町村名
      （P29 にない新しい学校の市区町村を、政令指定都市の区まで決めるため）。
    注意:
      - 休校の学校は全列 0 で載り、学校名に「(注)」が付いて表の下に注がある（例: 清川村「宮ヶ瀬(注)」
        ＝令和6年度より休校、相模原市「大野南分校(注)」＝夜間中学として設置、令和7年5月1日は生徒 0）。
        総数 0・「－」など読めない行は出さない。学校名の「(注)」は除く。
      - 分校は1校1行（「市場けやき分校」「新井桜坂分校」「金目五領ヶ台分校」「国府生沢分校」）。本校と学年を分けて
        持つ学校があり（市場小は1〜4年、市場けやき分校は5・6年）、学年 0 はそのまま 0 として読む。
      - 特別支援学級の再掲の列はない（学級数のシートに特別支援学級の数があるが読まない）。
      - 表の下に注の行（学校コードが空）がある。学校コードが13桁でない行は読まない。
      - 学年別の合計が総数と合わない行は grades を {} にする（令和7年度版にはない）。
    """
    out = []
    for f in files:
        for sheet, rows in workbook(f):
            if "学校別" not in sheet or "学級数" in sheet:
                continue
            school_type = next((t for k, t in SHEET_TYPES if k in sheet), None)
            hi = next((i for i, r in enumerate(rows[:6]) if "学校コード" in [cell_text(c) for c in r]), None)
            if school_type is None or hi is None:
                continue
            head = [cell_text(c) for c in rows[hi]]
            sub = [cell_text(c) for c in rows[hi + 1]]
            ti = sub.index("合計")
            grades = {int(g.group(1)): i for i, h in enumerate(sub) if (g := re.fullmatch(r"(\d)学年", h))}
            col = {h: head.index(h) for h in ("学校コード", "設置者", "所在市区町村", "学校名")}
            for r in rows[hi + 2:]:
                r = list(r) + [None] * (len(sub) - len(r))
                code = cell_text(r[col["学校コード"]])
                if not re.fullmatch(r"[BC][12]\d{11}", code):
                    continue   # 注・空行
                total = cell_int(r[ti])
                if not total:
                    continue   # 休校（全列 0 か「－」）・読めない値
                g = {f"{k}年": cell_int(r[i]) for k, i in sorted(grades.items())}
                if any(v is None for v in g.values()) or sum(g.values()) != total:
                    g = {}
                founder = cell_text(r[col["設置者"]])
                name = re.sub(r"\(注\d*\)$", "", cell_text(r[col["学校名"]]))
                pref_run = founder == "神奈川県"
                located = re.sub(r"^\d+", "", cell_text(r[col["所在市区町村"]]))   # 「101横浜市鶴見区」
                out.append(SchoolCount(pref="14", municipality=located if pref_run else founder, name=name,
                                       school_type=school_type, year=cfg["school_year"], total=total, grades=g,
                                       code=code, address=located or None,
                                       founder="都道府県立" if pref_run else "市区町村立"))
    return out
