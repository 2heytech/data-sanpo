import re
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text, workbook

# P29（国土数値情報）の書き方にそろえる字（出典 → P29）
VARIANTS = str.maketrans({"\u6adf": "\u6aaa"})   # 櫟 → 檪（三好市「櫟生小学校」、P29 は「檪生」）


def read_tokushima(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """徳島県「令和8年度公立学校関係データ（小学校）」「同（中学校）」の xlsx（Our Open Data、CC BY）。
    2026-10-17 に取得して確認。年度ごと・学校の種類ごとに別のデータセット（小学校 5184、中学校 5185）。

    形式: シート1枚（「R８_小学校」「R８_中学校」）。0行目は題名と「（R８年５月１日現在）」（中学校は「令和８年」。年度はここから
    読み、読めなければ cfg["school_year"]）、1〜3行目が見出し:
      1行目: 設置者, 学校名, 郵便番号, 所在地, 学級数（4〜7列: 計・単式・複式・特別支援）, 児童数（中学校は生徒数）,
             本務教員数, 本務職員数
      2行目: 児童数の下に 1年, 2年, …, 6年, 計（中学校は 1年〜3年, 計）
      3行目: それぞれ 計, 男, 女
    4行目から1行1校。各学年・総数は「計」の列（男・女の列は使わない）。最後の行は「合計」。
    設置者は市町村ごとに最初の行にだけある（セル結合）ので、下の行に引き継ぐ。
    所在地は郡名から（「海部郡美波町西の地字谷裏９０の１９」「徳島市徳島町城内１番地の１５」）。

    注意:
    - 休校は所在地に「休校」「令和8年度より休校」、廃止は「令和8年度より廃止」と書かれ、人数の列が 0。
      総数が 0 の行は出さない（0人の値は取り込まない）。
    - 中学校の最初に県立（設置者「徳島県」: 県立川島中学校・富岡東中学校・しらさぎ中学校（夜間中学））がある。
      学校名の「県立」は除き、founder="都道府県立"、municipality は「徳島県」にする。吉野川市には
      県立川島中学校と吉野川市立川島中学校が同じ名前であり、所在地の市町村名（吉野川市）や "" では P29 の2校を
      区別できない。P29 の県立の点は設置者「徳島県」でも引けるので、「徳島県」なら県立の1校に決まる
      （市立の方はその後に残った1校に決まる。県立の行が表の先頭にあるので順番も合う）。
    - 学校名の字は P29 にそろえる（「櫟生」→「檪生」）。
    - 分校は「大麻中学校広塚分校」「由岐中学校伊座利分校」の形で1行（休校の分校もある）。
    - 中等教育学校・特別支援学校・高校は別のデータセットなので読まない。義務教育学校のデータセットはない（2026年度）。
    - 学校コードの列はない。
    """
    out = []
    for f in files:
        m = re.search(r"(elementary|junior_high)", f.name)
        for _, rows in workbook(f):
            head1 = [cell_text(h) for h in rows[1]]
            if "学校名" not in head1:
                continue
            school_type = m.group(1) if m else ("elementary" if "児童数" in head1 else "junior_high")
            title = "".join(cell_text(c) for c in rows[0])
            y = re.search(r"(?:R|令和)(\d+)年5月1日現在", title)
            year = 2018 + int(y.group(1)) if y else cfg["school_year"]
            start = next(i for i, h in enumerate(head1) if h in ("児童数", "生徒数"))
            end = next(i for i, h in enumerate(head1) if i > start and h)
            head2 = [cell_text(h) for h in rows[2]]
            grades = {int(g.group(1)): i for i in range(start, end) if (g := re.fullmatch(r"(\d)年", head2[i]))}
            total_col = next(i for i in range(start, end) if head2[i] == "計")
            founder = ""
            for r in rows[3:]:
                if cell_text(r[0]):
                    founder = cell_text(r[0])
                name = cell_text(r[1]).translate(VARIANTS)
                if not name or founder == "合計":
                    continue
                n = cell_int(r[total_col])
                if not n:            # 休校・廃止（0）や読めない値は出さない
                    continue
                g = {f"{k}年": cell_int(r[i]) for k, i in sorted(grades.items())}
                if any(v is None for v in g.values()) or sum(g.values()) != n:
                    g = {}
                address = cell_text(r[3]) or None
                pref_school = founder == "徳島県"
                if pref_school:
                    name = re.sub(r"^(徳島)?県立", "", name)
                out.append(SchoolCount(pref="36", municipality=founder, name=name, school_type=school_type,
                                       year=year, total=n, grades=g, address=address,
                                       founder="都道府県立" if pref_school else "市区町村立"))
    return out
