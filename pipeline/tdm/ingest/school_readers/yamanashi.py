import logging
import re
import statistics
import subprocess
import unicodedata
from pathlib import Path

from ..school_counts import SchoolCount

log = logging.getLogger(__name__)

# 表題の【】の中 → (学校の種類, 学年の数)
KINDS = {"小学校": ("elementary", 6), "中学校": ("junior_high", 3), "義務教育学校": ("compulsory", 9)}
NUM = re.compile(r"(?<![^\s])[0-9][0-9,]*(?![^\s])")   # 空白で区切られた数（全角数字は数えない）
PAREN_NUM = re.compile(r"（[\s0-9,]*）")                 # 特別支援学級の再掲「（ 12 ）」
ALIASES = {"都留文大附属": "都留文科大学附属"}


def _pdf_text(path: Path) -> str:
    """pdftotext（poppler-utils）でレイアウトを保ったテキストにする。-fixed 4 で列の位置をページ内でそろえる。"""
    return subprocess.run(["pdftotext", "-layout", "-fixed", "4", str(path), "-"], check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout


def _ends(line: str) -> list[int]:
    return [m.end() for m in NUM.finditer(line)]


def _template(lines: list[str], ncol: int) -> list[float] | None:
    """数の列の右端の位置（数は右寄せ）。全部の欄が埋まった行（市町村計など）の中央値。"""
    full = [e for e in map(_ends, lines) if len(e) == ncol]
    if len(full) < 2:
        return None
    return [statistics.median(c) for c in zip(*full)]


def _assign(line: str, cols: list[float]) -> list[int | None] | None:
    """行の数を、右端の位置がいちばん近い列に置く。行全体が1文字ずれることがあるので、ずれ（3つ以上の数の中央値、
    ±1文字まで）を引いてから。どの列か決まらない数があれば None。"""
    found = [(m.end(), int(m.group().replace(",", ""))) for m in NUM.finditer(line)]
    shift = 0.0
    if len(found) >= 3:
        shift = statistics.median(min((e - c for c in cols), key=abs) for e, _ in found)
        shift = max(-1.0, min(1.0, shift))
    gap = min(b - a for a, b in zip(cols, cols[1:]) if a > 0)
    tol = min(2.0, gap / 2 - 0.5)
    vals: list[int | None] = [None] * len(cols)
    for e, v in found:
        d = sorted((abs(e - shift - c), i) for i, c in enumerate(cols))
        (d0, i), (d1, _) = d[0], d[1]
        if d0 > tol or d1 - d0 < 2 or vals[i] is not None:
            return None
        vals[i] = v
    return vals


def _clean(name: str) -> str:
    name = re.sub(r"\s+", "", unicodedata.normalize("NFKC", name))
    if "→" in name:                      # 「西島→身延清稜」（数のある行は新しい名前）
        name = name.split("→")[-1]
        name = name.removesuffix("へ")
    name = re.sub(r"\([^()]*\)", "", name)  # 「富沢(R2.4月~)」
    return ALIASES.get(name, name)


def read_yamanashi(files: list[Path], cfg: dict) -> list[SchoolCount]:
    """山梨県教育委員会「山梨県内の学校・学級・児童生徒数等」の「学校別児童数【小学校】」「同【中学校】」
    「同【義務教育学校】」の PDF（保存名 elementary.pdf / junior_high.pdf / compulsory.pdf。学校の種類は表題の【】で判断）。

    形式（2026-10-17 に取得して確認。令和8年5月1日現在）: 1行1校。左から学校名（「押原」のように設置者・「小学校」なし）、
    前年度児童数、総数（学級数・児童数）、学年ごとの（学級数・児童数）、教員数（本務・兼務）、職員数。
    各校の行のすぐ上に特別支援学級の再掲「（ 12 ）」の行があるので読まない（括弧付きの数は数えない）。
    「〇〇市計」「〇〇郡計」「〇〇教育事務所計」の行のあとにその市町村の学校が並ぶ。「国立計」から下（国立・私立）は読まない。

    pdftotext -layout -fixed 4 でテキストにし、数は右寄せなので、各数の右端の位置で列を決める（列の位置はそのページの
    全部の欄が埋まった行の中央値。義務教育学校の表は前年度の欄が全部空なので、前年度を除いた行から決める）。
    空欄は「学級数」では複式学級、「児童数」ではその学年の児童がいないこと（表の注）。学年の児童数の空欄は 0 にする。

    確かめていること: 各校の学年別の合計が総数と一致すること（しない行は列の対応付けが怪しいので出さない）、
    市町村ごとの学校の合計（総数・学年別）が「〇〇市計」の行と一致すること（しない市町村の学校は出さない）。
    年度は表の「令和N年5月1日現在」から（読めなければ cfg の school_year）。

    注意:
    - 分校は親の学校の次の行に「（山城）」「（桜木）」のように書かれる。親と同じ名前なら「山城小学校分校」、
      違えば「中道南小学校桜木分校」とする（P29 の名前の付け方）。児童のいない分校（病院内の分校など）は出さない。
    - 休校（「神金第二(休校）」）・統合で閉じた学校（「睦合 →南部へ」。前年度の数だけある）は総数が空なので出さない。
    - 統合後の名前は「西島→身延清稜」のように矢印のあとに書かれる（数のある行は矢印のあとの名前を使う）。
    - 組合立（河口湖南中学校組合）は市町村を組合の名前にする。「都留文大附属」は「都留文科大学附属」にそろえる。
    - サイトは User-Agent のないリクエストに 404 を返す。
    """
    out: list[SchoolCount] = []
    for path in files:
        text = _pdf_text(path)
        head = unicodedata.normalize("NFKC", text[:2000])
        m = re.search(r"【(小学校|中学校|義務教育学校)】", head)
        if not m:
            log.warning("%s: 表題に学校の種類がない", path.name)
            continue
        school_type, ngrade = KINDS[m.group(1)]
        word = m.group(1)
        y = re.search(r"令和(\d+)年5月1日現在", re.sub(r"\s+", "", head))
        year = 2018 + int(y.group(1)) if y else cfg["school_year"]
        ncol = 3 + 2 * ngrade + 3
        pages = [[PAREN_NUM.sub(lambda x: " " * len(x.group()), ln) for ln in pg.split("\n")]
                 for pg in text.split("\f")]
        file_cols = _template([ln for pg in pages for ln in pg], ncol)
        if file_cols is None:   # 前年度の欄が全部空（新しくできた学校だけの表）
            cols = _template([ln for pg in pages for ln in pg], ncol - 1)
            file_cols = [-100.0] + cols if cols else None
        if file_cols is None:
            log.warning("%s: 列の位置が分からない", path.name)
            continue

        muni = gun = ""
        group = None            # 確かめる市町村計: [名前, 総数, 学年別, その市町村の学校（SchoolCount）, 全部読めたか]
        pending = ""            # 数のない行の名前（次の行の「計」につながる）
        parent = ""             # 直前の学校の名前（分校の親）
        stop = False

        def close(g):
            """市町村計の行と、その市町村の学校の合計（総数・学年別）が合えば学校を出す。"""
            if not g:
                return
            n = sum(s.total for s in g[3])
            gs = [sum(s.grades[f"{k + 1}年"] for s in g[3]) for k in range(ngrade)]
            if g[4] and (n, gs) == (g[1], g[2]):
                log.debug("%s %s: 計 %s %s と学校 %d 校の合計が一致", path.name, g[0], n, gs, len(g[3]))
                out.extend(g[3])
            else:
                log.warning("%s %s: 学校の合計 %s %s が計の行 %s %s と合わない（この市町村の学校は出さない）",
                            path.name, g[0], n, gs, g[1], g[2])

        for lines in pages:
            if stop:
                break
            cols = _template(lines, ncol) or file_cols
            for raw in lines:
                if "学校別" in raw or "令和" in raw or "＊" in raw:
                    continue
                first = NUM.search(raw)
                name = re.sub(r"\s+", "", raw[:first.start()] if first else raw)
                if not first:
                    if re.search(r"[^\s（）()]", name):
                        pending = name
                    continue
                prev, pending = pending, ""
                vals = _assign(raw, cols)
                if not name:
                    name = prev
                if not name:
                    log.warning("%s: 名前のない行 %r", path.name, raw.strip()[:80])
                    continue
                if re.search(r"(計|組合)$", name):           # 市町村計・郡計・組合計など
                    if prev and not re.search(r"(市|町|村|郡|公立|国立|私立|総)計$", name):
                        name = prev + name                   # 「富士東部教育事」＋「務所計」
                    label = name.removesuffix("計")
                    if label.startswith(("国立", "私立")):
                        stop = True
                        break
                    close(group)
                    group = None
                    if label.endswith("郡"):
                        gun, muni = label, ""
                    elif re.fullmatch(r".+[市町村]", label) or label.endswith("組合"):
                        gun = "" if label.endswith(("市", "組合")) else gun
                        muni = label if label.endswith(("市", "組合")) else gun + label
                        if vals is None or vals[2] is None:
                            log.warning("%s %s: 計の行が読めない", path.name, label)
                        else:
                            group = [label, vals[2], [vals[4 + 2 * g] or 0 for g in range(ngrade)], [], True]
                    else:                                    # 公立計・教育事務所計
                        gun = muni = ""
                    continue
                if not muni or not group:
                    log.warning("%s: 市町村（計の行）の分からない行 %s", path.name, name)
                    continue
                if vals is None:
                    log.warning("%s %s %s: 列が決まらない %r", path.name, muni, name, raw.strip()[:120])
                    group[4] = False                  # その市町村の学校は出さない
                    continue
                total = vals[2]
                if name.startswith("（") or name.startswith("("):    # 分校
                    inner = _clean(name[1:-1])
                    if not parent or "休校" in name:
                        continue
                    school = parent + word + ("分校" if inner == parent else inner + "分校")
                else:
                    school = parent = _clean(name)
                if total is None or total == 0:              # 閉校・休校・児童のいない分校
                    continue
                grades = [vals[4 + 2 * g] or 0 for g in range(ngrade)]   # 空欄＝その学年の児童がいない
                if sum(grades) != total:
                    log.warning("%s %s %s: 学年別の合計 %d が総数 %d と合わない", path.name, muni, school, sum(grades), total)
                    group[4] = False
                    continue
                group[3].append(SchoolCount(pref="19", municipality=muni, name=school, school_type=school_type,
                                            year=year, total=total,
                                            grades={f"{g + 1}年": n for g, n in enumerate(grades)}))
        close(group)
    # 中学校を先に出す。突き合わせは種類の違う同名の点にも対応させることがあり、2026年度に統合でできた
    # 「南部」小学校が先だと、P29 の南部中学校の点を取ってしまうため
    out.sort(key=lambda s: s.school_type == "elementary")
    return out
