import re
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text, workbook


def read_matsuyama(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """松山市オープンデータ「児童数・学級数」「生徒数・学級数」（CC BY 4.0）の xlsx。
    保存名 elementary.xlsx（R08jidousuu.xlsx）・junior_high.xlsx（R08chuuseitosuu.xlsx）。シートは1枚
    （「【小学校】（HP）」「【中学校】（HP）」）。

    形式（2026-10-17 に取得して確認）:
      1行目 B列「令和８年５月１日現在児童生徒数・学級数調」。4〜10行目が見出し（縦書きを1字ずつ行に分けたもの。
      4行目に学年の「１」〜「６」、7行目に全体の「計」の列）。
      12行目から1校5行:
        1行目 設置者名「松山市」, 学校番号, 学校名（「番町小」「拓南中」の略称）, 学年ごとの人数（特別支援学級を除く）
        2行目 「児童数」（中学校は「生徒数」）, 全体の「計」の列に総数（特別支援学級を含む）
        3行目 学年ごとの特別支援学級の人数を「(」「n」「)」の3セルで、その右に特別支援学級の計
        4・5行目 実学級数・標準学級数（読まない）
      最後に「合計（小計）」の行。
    学年別の人数は 1行目＋3行目（特別支援学級の学年別は再掲ではなく、足すと総数になる）。
    年度は1行目の「令和８年５月１日現在」から読む（読めなければ cfg["school_year"]）。

    注意:
      - 休校の学校（2026年度は興居島小釣島分校、睦月小・野忽那小・怒和小・津和地小・二神小）は人数が空欄か総数0なので出さない。
      - 学校名は「〇〇小」「〇〇中」の略称なので「小学校」「中学校」に直す。分校は「〇〇分校」とだけ書かれる。
      - 学校コード・所在地はない。義務教育学校はない。
      - 2022〜2026年度のファイルがあり、ファイル名は年度ごとに違う（R04jidousuu.xlsx, 06shoujidousuu.xlsx など）。
    """
    out = []
    for f in files:
        m = re.search(r"(elementary|junior_high)", f.name)
        if not m:
            continue
        kind = m.group(1)
        for _, rows in workbook(f):
            text = [[cell_text(c) for c in r] for r in rows]
            year = cfg["school_year"]
            for r in text[:5]:
                y = re.search(r"令和(\d+)年5月1日現在", "".join(r))
                if y:
                    year = 2018 + int(y.group(1))
                    break
            head = next((i for i, r in enumerate(text) if len(r) > 1 and r[1] == "設"), None)
            if head is None:
                continue
            grade_cols = {f"{c}年": j for j, c in enumerate(text[head]) if re.fullmatch(r"[1-9]", c)}
            total_col = next(j for r in text[head:head + 8] for j, c in enumerate(r) if c == "計")
            suffix = "小学校" if kind == "elementary" else "中学校"
            for i, r in enumerate(text):
                if i <= head or len(r) < 4 or r[1] != "松山市" or not r[3]:
                    continue
                count_row = next((k for k in range(i + 1, min(i + 3, len(text)))
                                  if len(text[k]) > 4 and text[k][4] in ("児童数", "生徒数")), None)
                if count_row is None:
                    continue
                n = cell_int(rows[count_row][total_col]) if total_col < len(rows[count_row]) else None
                if not n:          # 休校（空欄・0人）は出さない
                    continue
                name = r[3]
                if re.search(r"[小中]$", name):
                    name = name[:-1] + suffix
                special = rows[count_row + 1] if count_row + 1 < len(rows) else []
                grades = {}
                for g, j in grade_cols.items():
                    a = cell_int(rows[i][j]) if j < len(rows[i]) else None
                    b = cell_int(special[j]) if j < len(special) else None
                    grades[g] = None if a is None else a + (b or 0)
                if any(v is None for v in grades.values()) or sum(grades.values()) != n:
                    grades = {}
                out.append(SchoolCount(pref="38", municipality="松山市", name=name, school_type=kind,
                                       year=year, total=n, grades=grades))
    return out
