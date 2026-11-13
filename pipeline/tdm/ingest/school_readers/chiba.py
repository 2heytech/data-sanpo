import re
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text, workbook

SHEET_TYPES = (("義務教育学校", "compulsory"), ("中等教育学校", None), ("小学校", "elementary"), ("中学校", "junior_high"))


def read_chiba(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """千葉県教育委員会「千葉県教育便覧」V 学校名簿 5-1「国・公立学校名簿」（旧形式 xls、1ファイル）。
    2026-10-17 に令和7年版（数値は令和7年5月1日現在）を取得して確認。令和8年版の学校名簿は「1月掲載予定」で未掲載。

    保存名: schools.xls（何でもよい。シート名で学校の種類を判断する）。
    シート: 表紙, 5-1-1(幼稚園), 5-1-2(認定こども園), 5-1-3(小学校), 5-1-4(中学校), 5-1-5(義務教育学校),
      5-1-6(中等教育学校), 高等学校…, 特別支援学校。小学校・中学校・義務教育学校のシートだけ読む。
    形式: 1行目が題名（右端に「数値はR7.5.1現在」）、2〜4行目が3段の見出し、5行目から1行1校。
      列: 委員会名（設置者。「習志野市」「千葉県」「国立」）, 地区（教育事務所の地区。県立は「県立」）,
      区分（空欄・「休校」・「夜間学級」・「分校夜間学級」）, 学校名（「習志野市立津田沼小学校」）, 〒,
      所在地（「習志野市津田沼4-5-2」。県立の一部は「千葉県柏市…」、郡名なし）, TEL, FAX,
      学級数（計・単式・複式・特支）, 児童数（中学校・義務教育学校は「生徒数」）の「計」, 「１学年」の男・女 …
      「６学年」の男・女（中学校は３学年まで、義務教育学校は９学年まで）, 教員数（本務者）, 事務職員数, 学校栄養職員数。
      学年別は男女の和を学年の人数にする（男女別は読まない）。
    注意:
      - 国立（委員会名「国立」）は除く。県立中学校（千葉中・東葛飾中）は都道府県立として読み、市区町村は所在地から取る。
      - 休校は区分「休校」で全列 0（例: 千葉市立更科小学校富田分校）。総数 0 の行は出さない。
      - 分校は学校名に「〇〇小学校沖分校」の形で1校1行（八街市立二州小学校沖分校）。そのまま1校として読む。
      - 夜間中学: 区分「分校夜間学級」（松戸市立第一中学校みらい分校、千葉市立真砂中学校かがやき分校）は分校として読む。
        区分「夜間学級」の「市川市立大洲中学校(夜間学級)」は学校ではなく大洲中学校の学級（表の注「学校数は、
        市川市立大洲中学校(夜間学級)を除く」）なので読まない（大洲中学校の行の総数は元データのまま）。
      - 各シートの末尾に「①合計(国立)」「②合計(公立)」「合計(①+②)」と注の行がある（学校名の列が数値・空）。読まない。
      - 学級数（特支）は学級の数で、児童生徒数は学年別に含まれる（再掲の列はない）。
      - 学年別の合計が総数と合わない行は grades を {} にする（令和7年版にはない）。
    """
    out = []
    for f in files:
        for sheet, rows in workbook(f):
            school_type = next((t for k, t in SHEET_TYPES if k in sheet), None)
            if school_type is None or len(rows) < 5:
                continue
            h1, h2 = ([cell_text(c) for c in rows[i]] for i in (1, 2))
            ti = next(i for i, h in enumerate(h1) if h in ("児童数", "生徒数"))   # その下の段が「計」
            grades = {int(g.group(1)): i for i, h in enumerate(h2) if (g := re.fullmatch(r"(\d)学年", h))}
            col = {h: h1.index(h) for h in ("委員会名", "地区", "区分", "学校名", "所在地")}
            for r in rows[4:]:
                r = list(r) + [None] * (len(h1) - len(r))
                board, name, kind = (cell_text(r[col[k]]) for k in ("委員会名", "学校名", "区分"))
                if not re.search(r"(学校|学園|分校)$", name) or board == "国立":
                    continue   # 合計行・注・国立
                if kind == "夜間学級":
                    continue   # 学校ではなく本校の学級（本校の行とは別に載る）
                total = cell_int(r[ti])
                if not total:
                    continue   # 休校（全列 0）・読めない値
                g = {}
                for k, i in sorted(grades.items()):
                    m, w = cell_int(r[i]), cell_int(r[i + 1])
                    g[f"{k}年"] = None if m is None or w is None else m + w
                if any(v is None for v in g.values()) or sum(g.values()) != total:
                    g = {}
                address = re.sub(r"^千葉県", "", cell_text(r[col["所在地"]])) or None
                pref_run = board == "千葉県"
                if pref_run:
                    m = re.match(r"^(.+?郡.+?[町村]|.+?市|.+?[町村])", address or "")
                    muni = m.group(1) if m else ""
                else:
                    muni = board
                out.append(SchoolCount(pref="12", municipality=muni, name=name, school_type=school_type,
                                       year=cfg["school_year"], total=total, grades=g, address=address,
                                       founder="都道府県立" if pref_run else "市区町村立"))
    return out
