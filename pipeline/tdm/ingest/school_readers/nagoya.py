import logging
import re
import statistics
import subprocess
import unicodedata
from pathlib import Path

from ..school_counts import SchoolCount

log = logging.getLogger(__name__)

NUM = re.compile(r"(?<![^\s])[0-9][0-9,]*(?![^\s])")   # 空白で区切られた数（括弧付きの再掲は数えない）
# 特別支援学級の種別の行（学校の行のすぐ下）
SPECIAL = re.compile(r"^(知的障害|肢体不自由|病弱・身体虚弱|弱視|難聴|言語障害|自閉症・情緒障害|情緒障害)$")
# 見開きの左ページの表題 → (学校の種類, 学年の数, 1学年の欄（男・女 か 男・女・計）)
KINDS = {"(2)小学校": ("elementary", 6, 2), "(3)中学校": ("junior_high", 3, 3)}
KINDS_N = {t: n for t, n, _ in KINDS.values()}
TYPE_WORD = {"elementary": "小学校", "junior_high": "中学校"}
# PDF の字体・略し方を P29（学校の正式名）にそろえる
ALIASES = {"御剱": "御劔", "たかしま小": "たかしま"}
BRANCH = re.compile(r"^(.+)\((分校|.*校舎)\)$")   # 「川原（分校）」「日比野（南校舎）」


def _pdf_text(path: Path) -> str:
    """pdftotext（poppler-utils）でレイアウトを保ったテキストにする。-fixed 4 で列の位置をページ内でそろえる。"""
    return subprocess.run(["pdftotext", "-layout", "-fixed", "4", str(path), "-"], check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def _assign(found: list[tuple[int, int]], cols: list[float]) -> list[int | None] | None:
    """数（右端の位置, 値）を、右端の位置がいちばん近い列に置く。行全体のずれ（3つ以上の数の中央値、±1文字まで）を
    引いてから。どの列か決まらない数があれば None。"""
    shift = 0.0
    if len(found) >= 3:
        shift = statistics.median(min((e - c for c in cols), key=abs) for e, _ in found)
        shift = max(-1.0, min(1.0, shift))
    gap = min(b - a for a, b in zip(cols, cols[1:]))
    tol = min(2.0, gap / 2 - 0.5)
    vals: list[int | None] = [None] * len(cols)
    for e, v in found:
        d = sorted((abs(e - shift - c), i) for i, c in enumerate(cols))
        (d0, i), (d1, _) = d[0], d[1]
        if d0 > tol or d1 - d0 < 2 or vals[i] is not None:
            return None
        vals[i] = v
    return vals


def _left_rows(page: str) -> list[tuple[str, list[tuple[int, int]]]]:
    """見開きの左ページ: 行の名前（学校名・種別・区計）と、学年別の数（右端の位置, 値）。"""
    rows = []
    for line in page.split("\n"):
        first = NUM.search(line)
        if not first:
            if SPECIAL.match(_norm(line)) or BRANCH.match(_norm(line)):
                rows.append((_norm(line), []))  # 児童・生徒のいない種別（右ページは学級数だけ）・分校（右ページは教員数だけ）
            continue
        name = _norm(line[:first.start()])
        if not name or "再掲" in name:        # ページ番号・「特別支援計（再掲）」
            continue
        rows.append((name, [(m.end(), int(m.group().replace(",", ""))) for m in NUM.finditer(line)]))
    return rows


def _right_rows(page: str) -> list[tuple[str, list[int]]]:
    """見開きの右ページ: 行の名前（行の右端）と、括弧の付かない数（男・女・合計・学級数…）。"""
    rows = []
    for line in page.split("\n"):
        m = re.match(r"^(.*?)\s+(\S+)\s*$", line)
        if not m or not NUM.search(m.group(1)):
            continue
        name = _norm(m.group(2))
        if "再掲" in name or NUM.fullmatch(name):
            continue
        body = re.sub(r"\(\s*[0-9,]*\s*\)", " ", unicodedata.normalize("NFKC", m.group(1)))
        rows.append((name, [int(x.replace(",", "")) for x in NUM.findall(body)]))
    return rows


def _right_total(name: str, vals: list[int]) -> int | None:
    """右ページの行の合計（児童・生徒数）。学校の行・区計は「男 女 合計 学級数…」、種別の行は
    「男 女 計 学級数 特別支援学級数」（男か女が空欄なら4つ）。男＋女＝合計を確かめる。"""
    if SPECIAL.match(name):
        if len(vals) == 5 and vals[0] + vals[1] == vals[2]:
            return vals[2]
        if len(vals) == 4 and vals[0] == vals[1]:
            return vals[1]
        if len(vals) == 2:                     # 学級数・特別支援学級数だけ（児童・生徒がいない）
            return 0
        return None
    if len(vals) >= 3 and vals[0] + vals[1] == vals[2]:
        return vals[2]
    if BRANCH.match(name) and len(vals) == 1:  # 分校の行に教員数だけ（児童・生徒は特別支援学級の行だけ）
        return 0
    return None


def read_nagoya(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """名古屋市教育委員会「教育調査統計」（BODIK「【名古屋市】教育調査統計」の PDF。保存名 kyouiku_toukei.pdf）の
    「12 幼児・児童・生徒数、学級数、教員数の学校（園）別一覧」の「（２）小学校」「（３）中学校」。

    形式（2026-10-17 に取得して確認。No.220、令和7年5月1日現在。年度は表紙の「令和N年5月1日現在」から）:
    見開き2ページで1行。左ページに学校名と学年別・男女別の人数（小学校は各学年の男・女、中学校は男・女・計）、
    右ページに男女別の合計・合計・学級数・教員数と、行の右端に学校名。学校の行は通常の学級の人数だけで、
    すぐ下に特別支援学級の種別ごとの行（「知的障害」「情緒障害」など）が続く。区ごとに「〇〇区計」の行
    （特別支援学級を含む）と「特別支援計（再掲）」の行（括弧付き。読まない）がある。

    学校の総数＝学校の行の合計＋種別の行の計（区計と同じ数え方。再掲を足すのではない）。学年別も同じく足す。
    pdftotext -layout -fixed 4 でテキストにし、左ページの数は右端の位置で列（学年・男女）を決める（列の位置はその
    ページの全部の欄が埋まった行の中央値）。左右のページの行は同じ順に並ぶので、名前が全部一致することを確かめて組にする。

    確かめていること（合わない学校・区は出さない）: 左右のページの行の名前が同じ順で一致すること、各行の左ページの
    合計が右ページの合計と一致すること（男＋女＝合計も）、中学校は学年ごとに男＋女＝計、学年別の合計が総数と一致すること、
    区ごとに学校の合計（学年・男女別）が「〇〇区計」の行と一致すること。

    注意: 設置者はすべて名古屋市（municipality は「名古屋市」。区は区計の行で分かるが SchoolCount に欄がない）。
    PDF は年1回（8月ごろ）の発行で、BODIK のデータセットに年度ごとのファイルが足される（最新を使う）。
    """
    out: list[SchoolCount] = []
    for path in files:
        pages = _pdf_text(path).split("\f")
        m = re.search(r"令和\s*(\d+)\s*年\s*5\s*月\s*1\s*日現在", unicodedata.normalize("NFKC", pages[0]))
        year = 2018 + int(m.group(1)) if m else cfg["school_year"]
        rows: dict[str, list] = {}
        i = 0
        while i + 1 < len(pages):
            head = next((_norm(ln) for ln in pages[i].split("\n") if ln.strip()), "")
            if head not in KINDS:
                i += 1
                continue
            school_type, ngrade, per = KINDS[head]
            rows.setdefault(school_type, []).extend(
                _spread(f"{path.name} p.{i + 1}", pages[i], pages[i + 1], ngrade, per))
            i += 2
        for school_type, rs in rows.items():
            out += _schools(path.name, rs, school_type, KINDS_N[school_type], year)
    return out


def _spread(where: str, left: str, right: str, ngrade: int, per: int) -> list[tuple]:
    """見開き1つの行: (名前, 右ページの合計, 学年別, 左右が合うか)。"""
    lrows, rrows = _left_rows(left), _right_rows(right)
    if [n for n, _ in lrows] != [n for n, _ in rrows]:
        log.warning("%s: 左右のページの行の名前が合わない %s / %s", where,
                    [n for n, _ in lrows][:5], [n for n, _ in rrows][:5])
        return [("(読めない見開き)", None, None, False)]
    ncol = ngrade * per
    full = [[e for e, _ in f] for _, f in lrows if len(f) == ncol]
    if len(full) < 3:
        log.warning("%s: 列の位置が分からない", where)
        return [("(読めない見開き)", None, None, False)]
    cols = [statistics.median(c) for c in zip(*full)]

    def grades_of(found) -> list[int] | None:
        vals = _assign(found, cols)
        if vals is None:
            return None
        out = []
        for g in range(ngrade):
            v = [x or 0 for x in vals[g * per:(g + 1) * per]]
            if per == 3:                                 # 中学校: 男・女・計
                if v[0] + v[1] != v[2]:
                    return None
                out.append(v[2])
            else:
                out.append(v[0] + v[1])
        return out

    out = []
    for (name, found), (_, rvals) in zip(lrows, rrows):
        rtotal, grades = _right_total(name, rvals), grades_of(found)
        ok = rtotal is not None and grades is not None and sum(grades) == rtotal
        if not ok:
            log.warning("%s %s: 左右のページの合計が合わない（左 %s 右 %s）", where, name, grades, rtotal)
        out.append((name, rtotal, grades, ok))
    return out


def _schools(fname: str, rows: list[tuple], school_type: str, ngrade: int, year: int) -> list[SchoolCount]:
    """学校の行に種別の行を足し、区ごとに区計の行と合うことを確かめる。"""
    result: list[SchoolCount] = []
    ward: list[list] = []      # この区の学校: [名前, 総数, 学年別, 正しく読めたか]
    cur = None
    for name, rtotal, grades, ok in rows:
        if name == "市合計":
            n = sum(s.total for s in result)
            (log.debug if n == rtotal else log.warning)("%s %s 市合計 %s / 出した学校の合計 %s", fname, school_type, rtotal, n)
            continue
        if name.endswith("区計"):
            sums = [sum(s[2][g] for s in ward if s[2]) for g in range(ngrade)]
            if not ok or any(not s[3] for s in ward) or sums != grades or sum(s[1] or 0 for s in ward) != rtotal:
                log.warning("%s %s %s: 区計の行と学校の合計が合わない（この区の学校は出さない） 計 %s %s / 学校 %s",
                            fname, school_type, name, rtotal, grades, sums)
            else:
                log.debug("%s %s %s: 区計 %s %s と学校 %d 校の合計が一致", fname, school_type, name, rtotal, grades, len(ward))
                result += [SchoolCount(pref="23", municipality="名古屋市", name=s[0], school_type=school_type,
                                       year=year, total=s[1], grades={f"{g + 1}年": n for g, n in enumerate(s[2])})
                           for s in ward if s[1]]
            ward, cur = [], None
        elif SPECIAL.match(name):
            if cur is None:
                log.warning("%s %s: 学校の前に種別の行がある", fname, name)
                continue
            cur[1] = (cur[1] or 0) + (rtotal or 0)
            cur[2] = [a + b for a, b in zip(cur[2], grades)] if cur[2] and grades else None
            cur[3] = cur[3] and ok
        else:
            if (b := BRANCH.match(name)):           # P29 は「川原小学校分校」「日比野中学校分校」
                name = b.group(1) + TYPE_WORD[school_type] + "分校"
            cur = [ALIASES.get(name, name), rtotal, grades, ok]
            ward.append(cur)
    if ward:
        log.warning("%s %s: 区計の行がないまま終わった学校 %s", fname, school_type, [s[0] for s in ward])
    return result
