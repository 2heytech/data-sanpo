"""国土交通省「下水道データ室」の「市町村別汚水処理及び下水道処理人口普及率」（PDF）から、
汚水処理人口普及率を取り込む（docs/design-changes.md #211）。

形式（令和7年度末の PDF（4ページ）を 2026-11-07 に GitHub Actions から取得し、pdftotext -bbox で確認）:
  題名「全国市町村別 汚水処理及び下水道処理人口普及率一覧（令和７年度末）」。1ページに縦の表が5列並び、
  それぞれ上から「北海道」（都道府県の見出し）、「市町村名 汚水 下水」、「札幌市 99.9% 99.9%」…と続き、
  都道府県の終わりに「北海道 96.8% 92.3%」（都道府県の値）の行がある。列の途中や次の列・次のページへ続く。
  東京都の23区は「区部」の1行（23区全体）、政令指定都市は市全体の行だけ。名前に「※」が付く市町村は、
  四捨五入して100.0%になったもの（100%未満）。「下水」の「＊」は下水道がない市町村（汚水の列には出ない）。
  市町村のコードはないので、都道府県の中の名前で地図の市区町村に合わせる。
文字の位置で表を読むので、PDF は pdftotext -bbox（単語ごとの座標の HTML）にしてから読む。
テストの見本は同じ形の HTML（.html）を使う。
政令指定都市・東京都区部は全体の値しかないので、区には値を入れず注記を付ける（元データより細かく割り振らない）。
都道府県の値は表の都道府県の行（国土交通省の公表値）。
"""
from __future__ import annotations

import html
import re
import sqlite3
import subprocess
import unicodedata
from pathlib import Path

from ..db import insert_observation
from ..regions import PREFECTURES
from .isj_geocode import normalize_municipality

KIND = "mlit_sewerage"
WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="[\d.]+" yMax="[\d.]+">([^<]*)</word>')
VALUE = re.compile(r"(\d+(?:\.\d+)?)%|[＊*\-－…]")
PREF_CODE = {name: code for code, name in PREFECTURES.items()}
ZEN = str.maketrans("０１２３４５６７８９", "0123456789")
WARD_NOTE = "政令指定都市は市全体の値だけが公表されているため、区の値はありません"
TOKYO_WARDS_NOTE = "東京都の23区は区部全体の値（{value}%）だけが公表されているため、区ごとの値はありません"
ROUNDED_NOTE = "四捨五入して100.0%（実際は100%に少し足りない）"


def pdf_words(path: Path) -> str:
    """PDF なら単語ごとの座標の HTML にする（.html はそのまま読む）。"""
    if path.suffix.lower() == ".html":
        return path.read_text(encoding="utf-8")
    return subprocess.run(["pdftotext", "-bbox", str(path), "-"], check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout


def _rows(page: str) -> list[list[str]]:
    """1ページの単語を、縦の表（列）ごとに上から1行ずつの単語のリストにする。"""
    words = [(float(x), float(y), html.unescape(t)) for x, y, t in WORD.findall(page)]
    heads = sorted(x for x, _, t in words if t == "市町村名")
    starts: list[float] = []
    for x in heads:
        if not starts or x - starts[-1] > 30:
            starts.append(x)
    if not starts:
        return []
    # 都道府県の行・市町村名は見出しの「市町村名」より少し左から始まる
    bounds = [s - 20 for s in starts]
    columns: list[list[tuple[float, float, str]]] = [[] for _ in bounds]
    for x, y, t in words:
        i = max((k for k, b in enumerate(bounds) if b <= x), default=None)
        if i is not None:
            columns[i].append((x, y, t))
    out = []
    for col in columns:
        line: list[tuple[float, float, str]] = []
        for w in sorted(col, key=lambda w: (w[1], w[0])):
            if line and w[1] - line[0][1] > 2:
                out.append([t for _, _, t in sorted(line)])
                line = []
            line.append(w)
        if line:
            out.append([t for _, _, t in sorted(line)])
    return out


def _value(s: str) -> float | None:
    m = VALUE.fullmatch(s)
    if m is None:
        raise ValueError(f"普及率が読めません: {s}")
    return float(m.group(1)) if m.group(1) else None


def read_table(path: Path) -> tuple[str, dict[tuple[str, str], tuple[float | None, bool]], dict[str, float | None]]:
    """(年度末の日付, (都道府県コード, 市町村名) → (汚水処理人口普及率, 名前の※), 都道府県コード → 普及率)。"""
    text = pdf_words(path)
    words = unicodedata.normalize("NFKC", " ".join(t for _, _, t in WORD.findall(text)))
    m = re.search(r"令和(\d+|元)年度末", words.translate(ZEN))
    if not m:
        raise ValueError(f"{path.name}: 題名に「令和◯年度末」がありません")
    period = f"{2019 + (0 if m.group(1) == '元' else int(m.group(1))):04d}-03-31"
    munis: dict[tuple[str, str], tuple[float | None, bool]] = {}
    prefs: dict[str, float | None] = {}
    pref = None
    headers: list[str] = []
    for page in text.split("<page ")[1:]:
        for row in _rows(page):
            if row == ["市町村名", "汚水", "下水"]:
                continue
            if len(row) == 1 and row[0] in PREF_CODE:
                pref = PREF_CODE[row[0]]
                headers.append(pref)
                continue
            if len(row) != 3 or not VALUE.fullmatch(row[1]) or not VALUE.fullmatch(row[2]):
                continue   # 題名・注記
            if row[0] in PREF_CODE:
                if PREF_CODE[row[0]] != pref:
                    raise ValueError(f"{path.name}: {row[0]} の行が {pref} の見出しの下にあります")
                prefs[pref] = _value(row[1])
                continue
            if pref is None:
                raise ValueError(f"{path.name}: 都道府県の見出しより前に市町村の行があります: {row}")
            name = row[0].replace("※", "")
            munis[(pref, name)] = (_value(row[1]), "※" in row[0])
    lacking = [PREFECTURES[p] for p in headers if p not in prefs]
    if not munis or lacking:
        raise ValueError(f"{path.name}: 表が読めません（市町村 {len(munis)} 件。都道府県の値がない: {lacking}）")
    return period, munis, prefs


def _municipalities(conn: sqlite3.Connection) -> tuple[dict, dict]:
    """((都道府県コード, 市区町村名) → 地域ID, (都道府県コード, 政令指定都市名・区部) → 区の地域ID)。"""
    names, wards = {}, {}
    for r in conn.execute("SELECT entity_id, name, region FROM entities WHERE entity_type = 'municipality'"):
        pref = r["entity_id"][5:7]
        names[(pref, normalize_municipality(r["name"]))] = r["entity_id"]
        if r["region"] and (pref != "13" or r["region"] == "区部"):
            wards.setdefault((pref, normalize_municipality(r["region"])), []).append(r["entity_id"])
    return names, wards


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict, period: str) -> dict:
    got, munis, prefs = read_table(path)
    if got != period:
        raise ValueError(f"{path.name}: {got} の表です（設定は {period}）")
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == KIND}
    names, wards = _municipalities(conn)
    base = dict(period_start=period, period_end=period, period_kind="point", source_id=source_id)
    result = {"municipalities": 0, "designated_cities": 0, "prefectures": 0, "unmatched": []}

    def write(entity_id: str, value: float | None, note: str | None = None, status: str | None = None) -> None:
        for indicator_id, d in targets.items():
            insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                               definition_version=d["definition_version"], value=value,
                               status=status or ("observed" if value is not None else "missing"),
                               method_note=note, **base)

    for (pref, name), (value, rounded) in sorted(munis.items()):
        key = (pref, normalize_municipality(name))
        if key in names:
            write(names[key], value, ROUNDED_NOTE if rounded else None)
            result["municipalities"] += 1
        elif key in wards:
            note = TOKYO_WARDS_NOTE.format(value=f"{value:.1f}") if pref == "13" else WARD_NOTE
            for ward in wards[key]:
                write(ward, None, note, "not_applicable")
            result["designated_cities"] += 1
        else:
            result["unmatched"].append(f"{PREFECTURES[pref]}{name}")
    for pref, value in sorted(prefs.items()):
        if conn.execute("SELECT 1 FROM entities WHERE entity_id = ?", (f"pref-{pref}",)).fetchone():
            write(f"pref-{pref}", value)
            result["prefectures"] += 1
    return result
