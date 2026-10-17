"""福岡県内の市町が BODIK ODCS（https://data.bodik.jp/）に CC BY で出している、学校別の児童・生徒数の読み方。

県全域の出典はないので、2024年度以降の学校別の数を出している市町ごとに読む。形式は 2026-10-17 に取得して確認したもの。

- read_kurume / read_ogori: 久留米広域連携中枢都市圏の共通形式「市立学校児童生徒数一覧」（1ファイルに小・中学校）
- read_fukuoka_toshiken: 福岡都市圏共通フォーマット「公立小学校児童数・公立中学校生徒数（学校別）」
  （筑紫野市・春日市・古賀市・福津市・粕屋町。表に市区町村名の列があるので1つの関数で読める）
- read_mizumaki: 水巻町「小・中学校の児童・生徒数及び学級数」（xlsx、学校ごとに「クラス別」「学年別」の2行）

年度は出典の設定 cfg["school_year"]。ファイルによって年度が違う出典は cfg["years"]（保存名 → 年度）で上書きする
（例: {"school_year": 2026, "years": {"junior_high.csv": 2025}}）。表の中の「調査年月日」は使わない
（古賀市の中学校の表は「2025/5/1」と書かれているが、人数は県の令和8年度学校基本調査速報の古賀市の値と同じで2026年度）。
"""
import csv
import io
import re
from pathlib import Path

from ..school_counts import SchoolCount, cell_int, cell_text, workbook

PREF = "40"


def _year(f: Path, cfg: dict) -> int:
    return int(cfg.get("years", {}).get(f.name, cfg["school_year"]))


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


def _school_type(name: str) -> str | None:
    if name.endswith("義務教育学校") or name.endswith("学園"):
        return "compulsory"
    if name.endswith("小学校"):
        return "elementary"
    if name.endswith("中学校"):
        return "junior_high"
    return None


# --- 久留米広域連携中枢都市圏の共通形式 -------------------------------------------------------------------------

def _read_kurume_area(files: list[Path], cfg: dict, municipality: str) -> list[SchoolCount]:
    """「市立学校児童生徒数一覧」CSV。1行1校で、小学校・中学校（久留米市は特別支援学校も）が1つの表にある。
    列: 時点（和暦）, 時点（西暦）, 学校名, 1学年児童・生徒数（人）…6学年児童・生徒数（人）, 学級数（学級）。
    総数の列はないので学年の和を総数にする（中学校は4〜6学年が空欄）。学校の種類は学校名の末尾で決める
    （「…小学校」「…中学校」、「…義務教育学校」「…学園」は義務教育学校）。「時点」の列は使わない（年度は cfg）。
    「特別小」「特別中」「特別高」の行（久留米市立久留米特別支援学校）は除く。休校の学校は全学年 0（大橋小・青峰小）で、
    値を作らない（total=0 で返す）。"""
    out = []
    for f in files:
        rows = _csv(f)
        head = [cell_text(h) for h in rows[0]]
        name_col = head.index("学校名")
        grade_cols = {int(m.group(1)): i for i, h in enumerate(head)
                      if (m := re.fullmatch(r"(\d)学年児童・生徒数\(人\)", h))}
        if not grade_cols:
            raise ValueError(f"{f.name}: 学年の列がない")
        for r in rows[1:]:
            name = cell_text(r[name_col])
            kind = _school_type(name)
            if kind is None:          # 「特別小」など特別支援学校の行
                continue
            n_grades = 6 if kind == "elementary" else 3
            vals = [cell_int(r[grade_cols[g]]) for g in range(1, n_grades + 1)]
            if any(v is None for v in vals):
                continue              # 読めない値は 0 にしない
            out.append(SchoolCount(pref=PREF, municipality=municipality, name=name, school_type=kind,
                                   year=_year(f, cfg), total=sum(vals),
                                   grades={f"{g}年": v for g, v in enumerate(vals, 1)}))
    return out


def read_kurume(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """久留米市「市立学校児童生徒数一覧（久留米市）」（BODIK 402036_0001200_00011、UTF-8）。形式は _read_kurume_area。
    令和8年度（2026年5月1日）は小学校44行（うち大橋小・青峰小は全学年 0 の休校）、中学校17校、特別支援学校3行。"""
    return _read_kurume_area(files, cfg, "久留米市")


def read_ogori(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """小郡市「児童生徒数（小郡市）（共通フォーマット）」（BODIK 402168_jidou、Shift_JIS）。形式は _read_kurume_area。
    2026年度は小学校8校・中学校5校。"""
    return _read_kurume_area(files, cfg, "小郡市")


# --- 福岡都市圏共通フォーマット ------------------------------------------------------------------------------

def read_fukuoka_toshiken(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """福岡都市圏共通フォーマット「公立小学校児童数・公立中学校生徒数（学校別）」CSV（小学校・中学校で別ファイル）。
    文字コードは市町で違う（筑紫野市・古賀市・福津市は Shift_JIS、春日市・粕屋町は UTF-8 BOM 付き）。福津市は見出しの
    セルの中に改行がある（cell_text で除いてから見る）。1行1校。列: 市区町村コード, 都道府県名, 市区町村名, 調査年月日, NO,
    学校名, 学校名_かな, 学校名_カナ, 総児童数（中学校は総生徒数）, 通常学級_学級数_1年…, 通常学級_児童数（総数）_1年,
    （男子）, （女子）…, 特別支援学級_学級数, 特別支援学級_児童数（総数）…, 通級指導教室_…, 備考。
    総数は「総児童数」「総生徒数」をそのまま使う（通常学級＋特別支援学級。通級指導教室は含まない）。
    学年別は「通常学級_児童数（総数）_N年」で、春日市は特別支援学級の在籍者を含めて書いている（学年の和＝総数）が、
    ほかの市町は特別支援学級を学年に分けていない（学年の和＋特別支援学級＝総数）ので、学年の和が総数と同じときだけ使う。
    学校の種類は「総児童数」「総生徒数」の列で決める。"""
    out = []
    for f in files:
        rows = _csv(f)
        head = [cell_text(h) for h in rows[0]]
        if "総児童数" in head:
            kind, total_col, word, n_grades = "elementary", head.index("総児童数"), "児童", 6
        elif "総生徒数" in head:
            kind, total_col, word, n_grades = "junior_high", head.index("総生徒数"), "生徒", 3
        else:
            raise ValueError(f"{f.name}: 総児童数・総生徒数の列がない")
        muni_col, name_col = head.index("市区町村名"), head.index("学校名")
        grade_cols = [head.index(f"通常学級_{word}数(総数)_{g}年") for g in range(1, n_grades + 1)]
        for r in rows[1:]:
            name = cell_text(r[name_col])
            total = cell_int(r[total_col])
            if not name or total is None:
                continue
            g = [cell_int(r[i]) for i in grade_cols]
            grades = {f"{k}年": v for k, v in enumerate(g, 1)} if None not in g and sum(g) == total else {}
            out.append(SchoolCount(pref=PREF, municipality=cell_text(r[muni_col]), name=name, school_type=kind,
                                   year=_year(f, cfg), total=total, grades=grades))
    return out


# --- 水巻町 ---------------------------------------------------------------------------------------------

MIZUMAKI_NAMES = {"朳": "杁"}   # 表は「朳」（U+6733）。学校名は水巻町立杁（いり）小学校（U+6741）


def read_mizumaki(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """水巻町「小・中学校の児童・生徒数及び学級数 令和6年度」xlsx（小学校 sg2024.xlsx・中学校 cg2024.xlsx の2ファイル）。
    1行目: 学校名, 学年, １学年（3列）, ２学年 …, 合計。2行目: クラス（１組・２組・３組）。3行目から学校ごとに2行:
    「<学校名>, クラス別, 学級ごとの人数…, 合計」と「(空), 学年別, 学年の人数（各学年の最初の列）…」。
    学校名は「伊左座」「水巻南」のように「小学校」「中学校」がない（ファイルの学年の数で種類を決め、付けて返す）。
    杁小学校は表では「朳」（別の字）になっているので「杁」に直す。
    総数は「クラス別」の行の合計の列。学年別は「学年別」の行。特別支援学級を含むかと時点は表に書かれていない
    （令和6年度の値は県の令和6年度学校基本調査（5月1日現在）の水巻町の値と小学校・中学校それぞれ1人違う）。"""
    out = []
    for f in files:
        for _, rows in workbook(f):
            head = [cell_text(c) for c in rows[0]]
            grade_cols = {int(m.group(1)): i for i, h in enumerate(head) if (m := re.fullmatch(r"(\d)学年", h))}
            total_col = next(i for i, h in enumerate(head) if h == "合計")
            kind = "elementary" if len(grade_cols) == 6 else "junior_high" if len(grade_cols) == 3 else None
            if kind is None:
                raise ValueError(f"{f.name}: 学年の列が6でも3でもない")
            for i, r in enumerate(rows):
                if cell_text(r[1]) != "クラス別" or not cell_text(r[0]):
                    continue
                total = cell_int(r[total_col])
                if total is None:
                    continue
                nxt = rows[i + 1] if i + 1 < len(rows) else []
                grades = {}
                if nxt and cell_text(nxt[1]) == "学年別":
                    g = [cell_int(nxt[grade_cols[k]]) for k in sorted(grade_cols)]
                    if None not in g and sum(g) == total:
                        grades = {f"{k}年": v for k, v in enumerate(g, 1)}
                name = MIZUMAKI_NAMES.get(cell_text(r[0]), cell_text(r[0]))
                out.append(SchoolCount(pref=PREF, municipality="遠賀郡水巻町",
                                       name=name + ("小学校" if kind == "elementary" else "中学校"),
                                       school_type=kind, year=_year(f, cfg), total=total, grades=grades))
    return out
