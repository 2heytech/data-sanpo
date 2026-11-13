import csv
import io
import re
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text

ADDR_MUNI = re.compile(r"^(.+?郡.+?[町村]|.+?市|.+?[町村])")


def _rows(path: Path) -> list[list[str]]:
    """CSV の行。ファイルによって UTF-8（BOM 付き）か Shift_JIS（cp932）なので、UTF-8 で読めなければ cp932 で読む。"""
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp932")
    return list(csv.reader(io.StringIO(text, newline="")))


def read_kagawa(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """香川県「令和8年度学校一覧（学校（園）数、幼児児童生徒数、本務教員数、本務職員数等）」の「03_R8小学校.csv」
    「04_R8中学校.csv」（香川県オープンデータ、CC BY）。2026-10-17 に取得して確認。値は令和8年5月1日現在
    （表の中に年度はないので cfg["school_year"]）。学校の種類は保存名（elementary.csv / junior_high.csv）で決める。

    形式: 1行目が見出し、2行目から1行1校。設置者, 学校名, 郵便番号, 所在地, 電話番号, 学級数(計)…(特別支援),
    児童数1年（計）（人）, （男）, （女）, …, 児童数6年（計）（人）…, 児童数（合計）（人）, …, 本務教員数…, 本務職員数…, 備考。
    中学校は「生徒数1年（計）（人）」…「生徒数3年（計）（人）」、総数の列名は「生徒数合計（人）」（小学校と書き方が違う）。

    注意:
    - 文字コードがファイル・年度で違う（R8 は小学校 UTF-8 BOM 付き・中学校 Shift_JIS、R6 の小学校は Shift_JIS）。両方読む。
    - 数値に桁区切りの「,」がある（「1,097」）。
    - 所在地は、設置者が市町のときは市町名を除いた形（「錦町2-14-1」「1580」）なので設置者の名前を前に付ける。
      国・県・私立・学校組合の行は市名から書いてある（「高松市牟礼町牟礼1583-1」「三豊市山本町辻876」）のでそのまま。
    - 設置者「国」（香川大学教育学部附属）・「私立」の行は読まない。設置者「県」（高松北中学校）は founder="都道府県立"、
      municipality は所在地の市名（高松市）。
    - 学校組合立（設置者「三豊市観音寺市　　　学校組合」、三豊中学校）は空白を除いた設置者名のまま
      （P29 の「三豊市観音寺市学校組合立三豊中学校」と対応する）。
    - 休校は人数がすべて 0 で備考に「休校」（女木小学校・小手島中学校など）。休校と書かれずに在籍 0 の分校もある
      （亀阜小学校みねやま分校、R8）。総数が 0 の行は出さない。
    - 分校は「紫雲中学校みねやま分校」「下笠居小学校五色台分校」の形で1行。
    - 義務教育学校は R8 のデータセットにない。
    - 中学校を先に出す。突き合わせ（Matcher）は種類が合わないときに「市町村＋学校名」だけで別の種類の点にも
      対応させるので、2023年度の P29 にない豊中小学校（三豊市。R6 より後に桑山・比地大・笠田・上高野・本山の5校を統合）が先に来ると、
      三豊市立豊中中学校の点を取ってしまう（中学校が先なら中学校が自分の点を取り、豊中小学校は所在地から位置を求める）。
    """
    out = []
    for f in sorted(files, key=lambda p: "elementary" in p.name):   # junior_high を先に
        m = re.search(r"(elementary|junior_high)", f.name)
        if not m:
            continue
        rows = _rows(f)
        head = [cell_text(h) for h in rows[0]]
        total = next(i for i, h in enumerate(head) if re.fullmatch(r"(児童|生徒)数\(?合計\)?\(人\)", h))
        grades = {int(g.group(1)): i for i, h in enumerate(head) if (g := re.fullmatch(r"(?:児童|生徒)数(\d)年\(計\)\(人\)", h))}
        for r in rows[1:]:
            if len(r) <= total:
                continue
            founder = cell_text(r[0])
            if founder in ("国", "私立", "") or founder.endswith("法人"):
                continue
            n = cell_int(r[total])
            if not n:                      # 休校（0）や読めない値は出さない
                continue
            g = {f"{k}年": cell_int(r[i]) for k, i in sorted(grades.items())}
            if any(v is None for v in g.values()) or sum(g.values()) != n:
                g = {}
            place = cell_text(r[3])
            pref_school = founder == "県"
            municipal = re.fullmatch(r".+[市町村]", founder) is not None
            address = founder + place if municipal and not place.startswith(founder) else place
            muni = (am.group(1) if (am := ADDR_MUNI.match(place)) else "") if pref_school else founder
            out.append(SchoolCount(pref="37", municipality=muni,
                                   name=cell_text(r[1]), school_type=m.group(1), year=cfg["school_year"],
                                   total=n, grades=g, address=address or None,
                                   founder="都道府県立" if pref_school else "市区町村立"))
    return out
