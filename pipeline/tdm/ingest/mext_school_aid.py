"""文部科学省「就学援助実施状況等調査」の市町村別実施状況（都道府県ごとの PDF）から、市区町村の就学援助率を取り込む。

形式（令和4〜7年度の東京都・北海道の PDF を 2026-10-14 に GitHub Actions から取得し、pdftotext -layout で確認）:
  都道府県ごとに1つの PDF。後ろの方のページに「就学援助率」の欄があり（令和7年度は「４．就学援助率」、
  令和4〜5年度は「６．就学援助率」）、見出しにその前の年度（例: 令和7年度の調査は「令和６年度」）が書いてある。
  1行に1市区町村で、行の頭に「東京都 千代田区」、行の末尾に就学援助率が「5%未満」「10%未満」「15%未満」…
  のような5%刻みの区分で書いてある（「10%未満」は5%以上10%未満）。「0%未満」は援助を受けた児童生徒が
  いない（0%）と読む。政令指定都市は市全体の行だけ。
  令和3年度以前の調査は形式が違う（令和2年度の就学援助率が行と別の位置にある、令和元年度以前は区分の欄がない）ため
  取り込まない。

値は区分の上の端（「15%未満」なら 15、「0%未満」なら 0）で持つ。元データより細かくしないよう、区分の中の値は作らない。
画面では定義の legend.band（5）を使って「10%以上15%未満」と書く。
政令指定都市は市全体の区分しかなく、区に割り振ると元データより細かくなるので、区には値を入れない。都道府県の値は作らない
（区分から平均は計算できない）。
PDF は pdftotext（poppler-utils）でテキストにしてから読む。テストの見本は同じ形のテキスト（.txt）を使う。
"""
from __future__ import annotations

import re
import sqlite3
import subprocess
import unicodedata
from pathlib import Path

from ..db import insert_observation
from ..regions import PREFECTURES

ERAS = {"平成": 1988, "令和": 2018}
_PREF = "|".join(sorted(PREFECTURES.values(), key=len, reverse=True))
ROW = re.compile(rf"^\s*({_PREF})\s*(\S+)\s")   # 「和歌山県かつらぎ町」のように間が空かない県もある
RATE = re.compile(r"(\d+)\s*%\s*未満\s*$")
YEAR = re.compile(r"(平成|令和)(元|\d+)年度\s*$")
# 市区町村名の書き方の違い（令和4〜7年度の PDF で確認）: 「岩瀬郡鏡石町」のような郡名付き、「羅臼町教育委員会」「東海村役場」、
# 「梼原町」「諌早市」のような字体の違い
SUFFIX = re.compile(r"(教育委員会|役場|役所)$")
GUN = re.compile(r"^.+?郡")
VARIANTS = str.maketrans({"梼": "檮", "諌": "諫", "ヶ": "ケ", "髙": "高", "﨑": "崎"})


def _norm(name: str) -> str:
    return SUFFIX.sub("", unicodedata.normalize("NFKC", name)).translate(VARIANTS)


def pdf_text(path: Path) -> str:
    """PDF ならレイアウトを保ったテキストにする（.txt はそのまま読む）。"""
    if path.suffix.lower() == ".txt":
        return path.read_text(encoding="utf-8")
    return subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout


FRAGMENT = re.compile(r"^\s{1,20}([^\s○\d]{1,8})(\s|$)")


def _fragment(lines: list[str], i: int, step: int) -> str:
    """折り返された市区町村名の一部（すぐ上・すぐ下の空でない行の、名前の欄にある短い語）。"""
    j = i + step
    while 0 <= j < len(lines) and not lines[j].strip():
        j += step
    if not 0 <= j < len(lines) or ROW.match(lines[j]):
        return ""
    m = FRAGMENT.match(lines[j])
    return m.group(1) if m else ""


def read_rates(text: str) -> tuple[int | None, dict[tuple[str, str], int | None]]:
    """(就学援助率の年度, (都道府県名, 市区町村名) → 区分の上の端（%）。区分が読めない行は None)。"""
    year: int | None = None
    out: dict[tuple[str, str], int | None] = {}
    for page in text.split("\f"):
        if "援助率" not in page:
            continue
        lines = [unicodedata.normalize("NFKC", l) for l in page.splitlines()]
        for i, line in enumerate(lines):
            if year is None and (m := YEAR.search(line)):
                year = ERAS[m.group(1)] + (1 if m.group(2) == "元" else int(m.group(2)))
            row = ROW.match(line)
            if not row:
                continue
            rate = RATE.search(line)
            muni = row.group(2)
            if muni.startswith("○"):
                # 長い名前は行の上下に折り返される（「多治見」／「岐阜県 ○ ○ … 10%未満」／「市」）
                muni = _fragment(lines, i, -1) + _fragment(lines, i, 1)
                if not muni:
                    continue
            key = (row.group(1), muni)
            if rate or key not in out:
                out[key] = int(rate.group(1)) if rate else None
    return year, out


def _entities(conn: sqlite3.Connection) -> dict[tuple[str, str], str]:
    out = {}
    for r in conn.execute("SELECT entity_id, name FROM entities WHERE entity_type = 'municipality'"):
        pref = PREFECTURES.get(r["entity_id"].split("-", 1)[1][:2])
        if pref:
            out[(pref, _norm(r["name"]))] = r["entity_id"]
    return out


def _match(entities: dict[tuple[str, str], str], pref: str, muni: str) -> str | None:
    """名前で市区町村を探す。見つからなければ頭の郡名を外して探す（「大和郡山市」などは先にそのままの名前で見つかる）。"""
    name = _norm(muni)
    return entities.get((pref, name)) or entities.get((pref, GUN.sub("", name, count=1)))


def ingest(conn: sqlite3.Connection, files: list[Path], source_id: str, catalog: dict,
           fiscal_year: int) -> dict:
    entities = _entities(conn)
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == "mext_school_aid"}
    result = {"rows": 0, "matched": 0, "no_rate": [], "unmatched": [], "year_mismatch": []}
    for path in files:
        year, rates = read_rates(pdf_text(path))
        if year != fiscal_year:
            # 見出しの年度が出典の設定と違う（ファイルの取り違え）ときは取り込まない
            result["year_mismatch"].append(f"{path.name}: {year}")
            continue
        result["rows"] += len(rates)
        for (pref, muni), upper in rates.items():
            entity_id = _match(entities, pref, muni)
            if entity_id is None:
                result["unmatched"].append(f"{pref}{muni}")   # 政令指定都市（地図の単位は区）など
                continue
            if upper is None:
                result["no_rate"].append(f"{pref}{muni}")
            result["matched"] += 1
            for indicator_id, d in targets.items():
                insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                                   definition_version=d["definition_version"],
                                   period_start=f"{fiscal_year}-04-01", period_end=f"{fiscal_year + 1}-03-31",
                                   period_kind="fiscal_year", source_id=source_id,
                                   value=None if upper is None else float(upper),
                                   status="missing" if upper is None else "observed")
    result["unmatched"] = result["unmatched"][:30]
    result["no_rate"] = result["no_rate"][:30]
    return result
