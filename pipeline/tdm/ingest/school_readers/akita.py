import re
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text, workbook

TYPES = {"小学校": "elementary", "中学校": "junior_high", "義務教育学校": "compulsory"}


def read_akita(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """秋田県教育委員会「秋田県学校統計一覧」のエクセル版（5月1日現在。1ブック）。2026-10-17 に取得して確認（令和8年度版）。

    形式: 表紙・目次・総括表・統計表のあとに「Ⅳ．学校別一覧」のシートがある。読むのは次の3つ（シート名は年度で変わりうるので、
    1行目の題名「３　小学校一覧」「４　中学校一覧」「５　義務教育学校一覧」で探す）:
      2行目が見出し: 所在（市町村名）, 小学校名（正式名。「保戸野小学校」「勝平小学校千秋分校」「義務教育学校阿仁学園」）,
      設置者（「市立」「町立」「村立」「県立」「国立」「私立」）, へき地, 児童数（総計）, 学級数（単式）, 複式学級数,
      特別支援学級生徒数, 特別支援学級数, 本務教員数, 本務職員数。
      4行目に学年（「１年」〜「６年」と「合計」。中学校は「１年」〜「３年」と「計」、義務教育学校は〜「９年」と「合計」）、
      5行目に学年ごとの「男」「女」。6行目から1行1校。市ごとに「秋田市　計」の行（1列目が空）がある。
      義務教育学校のシートは学級数・児童生徒数の表の下に、もう一度「所在」の見出しで教員数の表が続く（そこで読むのをやめる）。

    注意:
      - 公立（市立・町立・村立・県立）だけ。県立は併設型の中学校（「秋田南高等学校中等部」など）で、founder="都道府県立"、
        municipality は所在の市。国立・私立は読まない。
      - 総数は「合計」（中学校は「計」）の列。学年別は男＋女で、和は総数と一致する。「特別支援学級生徒数」は総数の内数なので足さない。
      - 総数が 0 の学校（「勝平小学校千秋分校」など。学校はあるが5月1日に在籍者がいない）は行を出さない。
      - 漢字にはさまれた小さい「ッ」は「ツ」にそろえる（令和8年度版の「二ッ井中学校」。正式名は二ツ井中学校）。
      - 学校コード・所在地（番地）はない。年度は目次・表紙の「令和８年度」から（読めなければ cfg["school_year"]）。
    """
    out = []
    for f in files:
        book = workbook(f)
        year = cfg["school_year"]
        for _, rows in book[:3]:
            for r in rows[:5]:
                if m := re.search(r"令和(\d+)年度", "".join(cell_text(c) for c in r)):
                    year = 2018 + int(m.group(1))
                    break
        for sheet, rows in book:
            if not rows or not rows[0]:
                continue
            m = re.fullmatch(r"\d+(小学校|中学校|義務教育学校)一覧", cell_text(rows[0][0]))
            if not m:
                continue
            school_type = TYPES[m.group(1)]
            head = [cell_text(c) for c in rows[1]]
            assert head[0] == "所在", (f, sheet, head[:4])
            start = next(i for i, h in enumerate(head) if h.endswith("数(総計)"))
            end = next((i for i in range(start + 1, len(head)) if head[i]), len(head))
            sub = [cell_text(c) for c in rows[3]]
            grades = {int(g.group(1)): i for i in range(start, end) if (g := re.fullmatch(r"(\d)年", sub[i]))}
            total_col = next(i for i in range(start, end) if sub[i] in ("合計", "計"))
            sexes = [cell_text(c) for c in rows[4]] + [""] * len(head)
            # 「男」「女」の見出しは義務教育学校の7〜9年で空欄（結合セル）。書いてある所だけ確かめる
            assert all(sexes[i] in ("男", "") and sexes[i + 1] in ("女", "") and i + 1 not in grades.values()
                       and i + 1 != total_col for i in grades.values()), (f, sheet)
            for r in rows[5:]:
                place, name, founder = (cell_text(r[i]) if i < len(r) else "" for i in range(3))
                if place == "所在":      # 義務教育学校のシートの教員数の表
                    break
                if not place or not name or not founder.endswith("立") or founder in ("国立", "私立"):
                    continue
                n = cell_int(r[total_col])
                if not n:
                    continue
                g = {}
                for k, i in sorted(grades.items()):
                    a, b = cell_int(r[i]), cell_int(r[i + 1])
                    g[f"{k}年"] = None if a is None or b is None else a + b
                if any(v is None for v in g.values()) or sum(g.values()) != n:
                    g = {}
                # 「二ッ井中学校」のように地名の「ツ」が小さい「ッ」になっている学校がある（小学校は「二ツ井小学校」）
                name = re.sub(r"(?<=[\u4e00-\u9fff])ッ(?=[\u4e00-\u9fff])", "ツ", name)
                out.append(SchoolCount(pref="05", municipality=place, name=name, school_type=school_type, year=year,
                                       total=n, grades=g, founder="都道府県立" if founder == "県立" else "市区町村立"))
    return out
