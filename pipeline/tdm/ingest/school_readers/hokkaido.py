import csv
import io
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from ..school_counts import (
    SchoolCount,
    cell_int,
    cell_text,
    core_name,
    founder_of,
    workbook,
)

TYPES = {"小学校": "elementary", "中学校": "junior_high", "義務教育学校": "compulsory"}
CODE_KINDS = {"B1": "elementary", "C1": "junior_high", "C2": "compulsory"}
# 学校コード一覧と突き合わせるときにそろえる字（「北桧山」と「北檜山」、「沼の端」と「沼ノ端」など）
FOLD = str.maketrans({"檜": "桧", "ノ": "の", "ケ": "ヶ", "曾": "曽", "澤": "沢", "邊": "辺", "邉": "辺", "濱": "浜", "嶋": "島"})


def read_hokkaido(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """北海道教育委員会「北海道学校一覧」（5月1日現在）の「5 小学校の部」「6 中学校の部」「7 義務教育学校の部」（xlsx）。
    2026-10-17 に取得して確認（令和7年度版。令和8年度版はまだ出ていない）。

    形式: 1ブックに「公立 (児童数)」「国立・私立(児童数)」「公立 (教員数)」などのシート（義務教育学校は「児童数」「教職員数」）。
    人数のシートの1行目が題名（「公立小学校　児童数　R7.5.1」）、2〜4行目が見出し、5行目から1行1校:
      管内（「01空知」）, 市町村名（設置者。郡名なし。札幌市も区に分けず「札幌市」）, 学校名, 小中一貫教育の施設形態,
      へき地級地, 学級数, 「１学年」〜「６学年」（中学校は〜「３学年」、義務教育学校は〜「９学年」）,
      合計の「男」「女」「計」, 特別支援学級（再掲）の学級数・障害種別の人数・計。
    管内ごとに「管内計」、最後に「公立計」の行がある（1列目が「NN管内名」の形でない行は読まない）。

    学校名は「小学校」「中学校」を付けない略した形で、同じ名前が道内に多い学校は市町村名を頭に付けてある
    （「岩見沢中央」＝岩見沢市立中央小学校。一方「滝川第一」＝滝川市立滝川第一小学校のように市町村名まで正式名のこともある）。
    どちらかは表だけでは決まらないので、文部科学省「学校コード」一覧の CSV（保存名 school_codes*.csv。任意）を一緒に渡すと、
    同じ市町村・同じ種類の学校の正式名と「略した名前そのまま」「頭の市町村名を除いた名前」を突き合わせ（「檜」と「桧」、
    「ノ」と「の」などの字はそろえて比べる）、1校に決まれば
    正式名・学校コード（13桁）・所在地（「北海道」を除く）を付ける。決まらない学校・CSV がないときは略した名前のまま。
    学校コード一覧は年度の5月1日より前に廃止された学校（属性情報廃止年月日がその日以前）を除いて使う。

    注意:
      - 「公立」で始まる人数のシート（題名が「公立…児童数／生徒数」）の「公立計」の行までだけを読む。国立・私立のシートは
        読まない（義務教育学校のシートは「公立計」の下に「国立義務教育学校」の表が続くので、そこで読むのをやめる）。
        公立は市町村立だけで、道立の小中学校・義務教育学校はない（中等教育学校・特別支援学校は別のファイル）。
      - 総数は合計の「計」の列。学年別の和と一致する。特別支援学級の列は「再掲」なので足さない。
      - 全部 0 の行（学級数も 0）は休校（令和7年度は小学校7校・中学校2校）。行を出さない（0人にしない）。
        札幌市の夜間中学「星友館」も児童生徒数が 0 の行なので出さない。
      - 分校は「幌北ひまわり分校」「西樺山分校」のように本校名＋分校名の1行（正式名は「幌北小学校ひまわり分校」
        「西小学校樺山分校」。学校コード一覧があれば正式名になる）。
      - 年度は題名の「R7.5.1」から（読めなければ cfg["school_year"]）。
    """
    sheets = []
    for f in files:
        if f.suffix.lower() in (".xlsx", ".xls"):
            sheets += workbook(f)
    year = cfg["school_year"]
    for _, rows in sheets:
        if rows and rows[0] and (y := re.search(r"R(\d+)\.5\.1", cell_text(rows[0][0]))):
            year = 2018 + int(y.group(1))
            break
    codes = school_codes(files, "01", year)
    used: set[str] = set()
    out = []
    for sheet, rows in sheets:
        if not rows:
            continue
        title = cell_text(rows[0][0] if rows[0] else None)
        m = re.match(r"^公立(小学校|中学校|義務教育学校)(?:児童|生徒)数", title)
        if not m:
            continue
        school_type = TYPES[m.group(1)]
        head = [[cell_text(c) for c in r] for r in rows[1:4]]
        grades = {}
        for r in head:
            for i, h in enumerate(r):
                if g := re.fullmatch(r"(\d)学年", h):
                    grades[int(g.group(1))] = i
        total_col = next(i for i, h in enumerate(head[1]) if h == "合計")
        assert head[2][total_col: total_col + 3] == ["男", "女", "計"], (sheet, head[2])
        total_col += 2
        for r in rows[4:]:
            area = cell_text(r[0] if r else None)
            if area == "公立計":      # 義務教育学校のシートはこの下に国立の表が続く
                break
            if not re.match(r"^\d\d\D", area):
                continue
            n = cell_int(r[total_col])
            if not n:      # 休校（0）・空欄
                continue
            g = {f"{k}年": cell_int(r[i]) for k, i in sorted(grades.items())}
            if any(v is None for v in g.values()) or sum(g.values()) != n:
                g = {}
            muni, name = cell_text(r[1]), cell_text(r[2])
            code = address = None
            if hit := _official(codes, used, muni, school_type, name):
                code, name, address = hit
                used.add(code)
            out.append(SchoolCount(pref="01", municipality=muni, name=name, school_type=school_type, year=year,
                                   total=n, grades=g, code=code, address=address))
    return out


def _official(codes: dict, used: set, muni: str, school_type: str, name: str) -> tuple[str, str, str] | None:
    """略した学校名（「岩見沢中央」）に当たる学校コード一覧の学校（学校コード, 正式名, 所在地）。1校に決まらなければ None。"""
    cands = codes.get((muni, school_type), [])
    stem = re.sub(r"[市町村]$", "", muni)
    tries = [name]
    if stem and name.startswith(stem) and len(name) > len(stem):
        tries.append(name[len(stem):])
    for t in tries:
        core = core_name(t, muni).translate(FOLD)
        hits = [c for c in cands if c[0].translate(FOLD) == core and c[1] not in used]
        if len(hits) == 1:
            return hits[0][1:]
    return None


def school_codes(files: list[Path], pref: str, year: int) -> dict[tuple[str, str], list[tuple[str, str, str, str]]]:
    """文部科学省「学校コード」一覧（CSV。https://www.mext.go.jp/b_menu/toukei/mext_01087.html。列は 学校コード, 学校種
    「B1(小学校)」, 都道府県番号「01(北海道)」, 設置区分「2(公)」, 本分校「1(本)」「2(分)」「9(廃)」, 学校名「岩見沢市立中央小学校」,
    学校所在地, 郵便番号, 属性情報設定年月日, 属性情報廃止年月日「2025/5/1」, …。文字コードは版により Shift_JIS か UTF-8。
    令和8年5月の暫定版は見出しの前に題名・更新日の行があり、東日本が2つの CSV に分かれている（どちらも渡せばよい））から、
    都道府県の公立の小学校・中学校・義務教育学校のうち year 年5月1日に廃止されていないもの。
    {(設置者の市町村名, 学校の種類): [(学校名の中心部分, 学校コード, 正式名, 所在地)]}。CSV がなければ空。"""
    out: dict[tuple[str, str], list] = defaultdict(list)
    for f in files:
        if f.suffix.lower() != ".csv":
            continue
        raw = f.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp932")
        rows = csv.reader(io.StringIO(text, newline=""))
        for _ in range(5):     # 令和8年5月版は見出しの前に題名・更新日の行がある
            head = [cell_text(h) for h in next(rows, [])]
            if head[:1] == ["学校コード"]:
                break
        else:
            continue
        ix = {h: i for i, h in enumerate(head)}
        for r in rows:
            if len(r) < len(head) or r[ix["都道府県番号"]][:2] != pref or r[ix["設置区分"]][:1] != "2":
                continue
            kind = CODE_KINDS.get(r[ix["学校種"]][:2])
            closed = tuple(int(x) for x in re.findall(r"\d+", r[ix["属性情報廃止年月日"]]))  # 「2025/5/1」「2023-05-01」
            if not kind or (closed and closed <= (year, 5, 1)):
                continue
            name = cell_text(r[ix["学校名"]])
            founder = founder_of(name)
            if not founder:
                continue
            address = unicodedata.normalize("NFKC", r[ix["学校所在地"]]).strip()
            address = re.sub(r"^(北海道|東京都|(?:京都|大阪)府|.{2,3}県)", "", address)
            out[(founder, kind)].append((core_name(name, founder), cell_text(r[ix["学校コード"]]), name, address))
    return out
