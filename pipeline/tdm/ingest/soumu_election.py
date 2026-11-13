"""総務省の国政選挙の結果調（市区町村別・都道府県別の比例代表の得票数、都道府県別の投票率）を全国分取り込む。

形式（2026-10-14 に GitHub Actions から取得して確認。いずれも総務省「選挙関連資料」の結果調）:
  比例代表の市区町村別得票数（layout = "party"）:
    衆院選は比例代表のブロックごとに1ファイル。令和6年（第50回）は都道府県ごとのシートで、「市区町村名＼政党名」の
    行の右に政党名、最後の列が「得票数計」。令和8年（第51回）はシート名が都道府県名（北海道は「Sheet1」）で、
    「党派名」の行の次の行に政党名が並ぶ。参院選（令和7年・第27回）は都道府県ごとに1ファイルで、「党派名」の行に
    政党名があり、政党ごとに3列（得票総数・政党等の得票総数・名簿登載者の得票総数）。政党名の列の値が得票総数
    （政党名の票＋候補者名の票）。宮城・栃木にある2枚目のシート（別紙）は内訳なので読まない。
    開票区名は1列目か2列目（北海道の振興局・郡・政令指定都市の市全体の行は1列目、その中の市区町村・区は2列目）。
    小選挙区で分かれる市区は「大田区第４区」「札幌市北区第１」のような行に分かれ、市区全体の行がある回とない回がある。
    数値は「6,170.858」「53,072       」のように桁区切り・末尾の空白つきの文字列か数値。按分による小数を含む。
    参院選の表は、16の市区町（葛飾区・福井市・豊橋市・吹田市など）の行が空欄で、県計もその市区町を含まない。
  比例代表の都道府県別得票数（layout = "party_prefecture"）: 政党が数党ずつ縦に並ぶ表。政党名の行の下に都道府県の
    行が続き、政党名と同じ列が得票数（参院選は得票総数）。表の最後に見出しが「合計」だけの欄（全政党の合計）がある。市区町村の表の県計は上の空欄の市を含まないので、
    都道府県の値はこの表から作る。
  都道府県別の有権者数・投票者数（layout = "turnout"）: 「男・女・計」の見出しの行の、1つ目の「計」が選挙当日の
    有権者数、2つ目の「計」が投票者数。都道府県名は1列目か2列目（衆院選は1列目がブロック名）。
  令和6年衆院選の都道府県別の表は旧形式の Excel（.xls）なので xlrd で読む。

総務省は市区町村別の有権者数・投票者数を公表していないので、投票率は都道府県の値だけ（市区町村の投票率は
東京都の選挙管理委員会のデータ、tokyo_election.py）。

指標（definition の election_value で選ぶ）:
  party: その政党の得票数 ÷ 全政党の得票数の合計（有効投票）。政党は definition の party。
    その選挙に名簿を出していない政党は値を入れない（0 にしない）。
  turnout: 投票者数 ÷ 選挙当日の有権者数（都道府県だけ）。
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
import zipfile
from pathlib import Path

from ..db import insert_observation
from ..regions import PREFECTURES, prefecture_entity_id
from ..xlsx import read_sheet, sheet_names

PREF_CODE = {name: code for code, name in PREFECTURES.items()}
HEADS = ("党派名", "市区町村名＼政党名")
LABELS = {"党派名", "市区町村名＼政党名", "開票区名", "得票数計", "合計", "計", "全党派計", "届出番号"}
# 小選挙区で分かれた市区の行（「大田区第４区」「札幌市北区第１」）
PART = re.compile(r"^(.+?)第[0-9]+区?$")
# 選挙の表と地図（国勢調査）で字体の違う地名の字（鯵ケ沢町・梼原町）と、表の誤記（令和6年衆院選の「佐伯氏」）
VARIANTS = str.maketrans({"ヶ": "ケ", "鯵": "鰺", "梼": "檮"})
TYPOS = {"佐伯氏": "佐伯市"}
# 都道府県別の表の見出しの語（政党名の行と見分ける）
HEAD_WORDS = ("得票", "名簿", "政党等", "率", "区分", "都道府県", "選挙区", "比例代表", "を除く", "党派別")
# 地図の区と開票区が合わない市（2024年1月に区を再編。地図は2020年国勢調査の区）
REORGANIZED = {"浜松市": "2024年1月の区の再編で、選挙の開票区と地図の区（2020年国勢調査の区）が一致しないため値なし"}


def norm(name: str) -> str:
    """地名の表記の揺れをそろえる（全角・半角、空白、「ヶ」と「ケ」、字体の違い）。"""
    s = unicodedata.normalize("NFKC", str(name or ""))
    s = re.sub(r"[\s　★☆]", "", s).translate(VARIANTS)
    return TYPOS.get(s, s)


def _num(cell) -> float | None:
    if isinstance(cell, (int, float)):
        return float(cell)
    s = (str(cell or "")).replace(",", "").strip()
    if not s or s in ("-", "－"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _text(cell) -> str:
    return cell.strip() if isinstance(cell, str) else ""


def _sheets(path: Path) -> list[tuple[str, list[list]]]:
    if not zipfile.is_zipfile(path) or "xl/workbook.xml" not in zipfile.ZipFile(path).namelist():
        import xlrd   # 旧形式の Excel（.xls。令和6年衆院選の都道府県別の表）
        book = xlrd.open_workbook(str(path))
        return [(s.name, [s.row_values(i) for i in range(s.nrows)]) for s in book.sheets()]
    return [(name, read_sheet(path, name)) for name in sheet_names(path)]


def _prefecture(sheet: str, rows: list[list]) -> str | None:
    """シートの都道府県コード（シート名か「〇〇県選挙管理委員会」の文字から）。"""
    if sheet.strip() in PREF_CODE:
        return PREF_CODE[sheet.strip()]
    for r in rows[:12]:
        for c in r:
            m = re.match(r"^(.+?[都道府県])選挙管理委員会$", _text(c))
            if m and m.group(1) in PREF_CODE:
                return PREF_CODE[m.group(1)]
    return None


def _party_columns(rows: list[list]) -> tuple[int, dict[str, int]]:
    """(政党名の行の位置, {政党名: 列})。政党名が見出しと同じ行にない（第51回衆院選）ときは次の行。"""
    at = next(i for i, r in enumerate(rows) if any(_text(c) in HEADS for c in r))
    for i in (at, at + 1):
        cols = {norm(c): j for j, c in enumerate(rows[i]) if j >= 1 and _text(c) and _text(c) not in LABELS}
        if cols:
            return i, cols
    raise ValueError("政党名の行が見つかりません")


def read_party_votes(path: Path) -> dict[str, dict[str, dict[str, float]]]:
    """都道府県コード → 開票区名（表記をそろえたもの） → {政党名: 得票数}。
    値が空欄の行・都道府県の計などの行も名前のまま入る（市区町村に対応させるのは municipality_votes）。"""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for sheet, rows in _sheets(path):
        pref = _prefecture(sheet, rows)
        if pref is None or "別紙" in sheet or not any(_text(c) in HEADS for r in rows for c in r):
            continue   # 政党の一覧・内訳のシート
        at, parties = _party_columns(rows)
        got = out.setdefault(pref, {})
        for r in rows[at + 1:]:
            name = next((_text(c) for c in r[:2] if _text(c)), "")
            if not name or name in LABELS:
                continue
            votes = {p: v for p, j in parties.items() if j < len(r) and (v := _num(r[j])) is not None}
            got.setdefault(norm(name), votes)
    return out


def read_prefecture_party_votes(path: Path) -> dict[str, dict[str, float]]:
    """都道府県コード → {政党名: 得票数}（都道府県別の表）。"""
    out: dict[str, dict[str, float]] = {}
    for _, rows in _sheets(path):
        parties: dict[str, int] = {}
        for r in rows:
            pref = next((PREF_CODE[_text(c)] for c in r[:2] if _text(c) in PREF_CODE), None)
            if pref is None:
                # 政党名の行: 数値がなく、見出しの語（「区分」「得票総数」など）でない文字がある行
                names = {j: _text(c) for j, c in enumerate(r) if j >= 1 and _text(c) and _text(c) not in LABELS
                         and not any(w in _text(c) for w in HEAD_WORDS)}
                if not any(_num(c) is not None for c in r):
                    if names:
                        parties = {norm(t): j for j, t in names.items()}
                    elif any(_text(c) in ("合計", "計") for c in r[1:]):
                        parties = {}   # 表の最後の「合計」の欄（全政党の合計）。前の政党の列と取り違えない
                continue
            for p, j in parties.items():
                if j < len(r) and (v := _num(r[j])) is not None:
                    out.setdefault(pref, {})[p] = v
    return out


def read_turnout(path: Path) -> dict[str, tuple[float, float]]:
    """都道府県コード → (投票者数, 選挙当日の有権者数)。"""
    out: dict[str, tuple[float, float]] = {}
    for _, rows in _sheets(path):
        head = next((r for r in rows if [_text(c) for c in r].count("計") >= 2
                     and "男" in [_text(c) for c in r]), None)
        if head is None:
            continue
        sums = [j for j, c in enumerate(head) if _text(c) == "計"]
        electorate_col, voters_col = sums[0], sums[1]
        for r in rows:
            # 衆院選は1列目がブロック名で、東京都・北海道は1列目と2列目が同じ都道府県名
            pref = next((PREF_CODE[_text(c)] for c in r[:2] if _text(c) in PREF_CODE), None)
            if pref is None or pref in out or voters_col >= len(r):
                continue
            voters, electorate = _num(r[voters_col]), _num(r[electorate_col])
            if voters is not None and electorate:
                out[pref] = (voters, electorate)
    return out


def municipality_votes(rows: dict[str, dict[str, float]],
                       names: dict[str, str]) -> dict[str, dict[str, float]]:
    """開票区の行を市区町村に対応させる。names は 表記をそろえた市区町村名 → 地域ID。
    市区全体の行があればそれを使い、なければ「…第N区」の行を合計する。市区町村でない行（振興局・郡・政令指定都市の
    市全体・計）と、値が空欄の行は使わない。"""
    out: dict[str, dict[str, float]] = {}
    for name, votes in rows.items():
        if name in names and votes:
            out[names[name]] = dict(votes)
    for name, votes in rows.items():
        m = PART.match(name)
        if not m or not votes or name in names or m.group(1) not in names or rows.get(m.group(1)):
            continue
        acc = out.setdefault(names[m.group(1)], {})
        for p, v in votes.items():
            acc[p] = acc.get(p, 0.0) + v
    return out


def _municipalities(conn: sqlite3.Connection, pref: str) -> dict[str, str]:
    return {norm(r["name"]): r["entity_id"] for r in conn.execute(
        "SELECT entity_id, name FROM entities WHERE entity_type = 'municipality' AND entity_id LIKE ?",
        (f"muni-{pref}%",))}


def _has_entity(conn: sqlite3.Connection, entity_id: str) -> bool:
    return conn.execute("SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)).fetchone() is not None


def _missing_note(name: str, row: dict | None) -> str:
    for city, note in REORGANIZED.items():
        if name.startswith(city):
            return note
    if row is not None:
        return "総務省の開票区別の表でこの市区町村の欄が空欄のため値なし"
    return "総務省の開票区別の表にこの市区町村の行がないため値なし"


def ingest(conn: sqlite3.Connection, paths: list[Path], source_id: str, catalog: dict, cfg: dict,
           prefs: list[str]) -> dict:
    """出典1つ（1つの選挙の1つの表。市区町村別の得票数はブロック・都道府県ごとの複数のファイル）を取り込む。
    cfg は sources.toml の設定（period・layout）。"""
    period = cfg["period"]
    obs = dict(period_start=period, period_end=period, period_kind="point", source_id=source_id,
               denominator_source_id=source_id)
    layout = cfg["layout"]
    result: dict = {}
    if layout == "turnout":
        targets = {k: d for k, d in catalog.items() if d.get("election_value") == "turnout"}
        turnout = {p: v for path in paths for p, v in read_turnout(path).items()
                   if p in prefs and _has_entity(conn, prefecture_entity_id(p))}
        for indicator_id, d in targets.items():
            for pref, (voters, electorate) in turnout.items():
                insert_observation(conn, entity_id=prefecture_entity_id(pref), indicator_id=indicator_id,
                                   definition_version=d["definition_version"],
                                   value=voters / electorate * d.get("scale", 1), status="derived",
                                   numerator=voters, denominator=electorate, **obs)
        result["prefectures"] = len(turnout)
        return result

    targets = {norm(d["party"]): (k, d) for k, d in catalog.items()
               if d.get("source_kind") == "soumu_election" and d.get("election_value") == "party"}
    units: list[tuple[str, dict[str, float] | None, str | None]] = []   # (地域ID, 得票数, 値なしの理由)
    if layout == "party_prefecture":
        data = {p: v for path in paths for p, v in read_prefecture_party_votes(path).items() if p in prefs}
        units = [(prefecture_entity_id(p), v, None) for p, v in sorted(data.items())
                 if _has_entity(conn, prefecture_entity_id(p))]
        result["prefectures"] = len(units)
    elif layout == "party":
        data: dict[str, dict[str, dict[str, float]]] = {}
        for path in paths:
            for p, rows in read_party_votes(path).items():
                if p in prefs:
                    data.setdefault(p, {}).update(rows)
        unmatched: list[str] = []
        for pref, rows in sorted(data.items()):
            names = _municipalities(conn, pref)
            munis = municipality_votes(rows, names)
            for name, entity_id in sorted(names.items()):
                if entity_id in munis:
                    units.append((entity_id, munis[entity_id], None))
                else:
                    unmatched.append(f"{PREFECTURES[pref]}{name}")
                    units.append((entity_id, None, _missing_note(name, rows.get(name))))
        result["municipalities"] = sum(1 for _, v, _ in units if v)
        result["unmatched"] = unmatched[:50]
        result["unmatched_count"] = len(unmatched)
    else:
        raise ValueError(f"不明な layout: {layout}")
    seen = {p for _, votes, _ in units if votes for p in votes}
    for party, (indicator_id, d) in targets.items():
        if party not in seen:
            continue   # この選挙には名簿を出していない（値を入れない）
        for entity_id, votes, note in units:
            total = sum(votes.values()) if votes else 0
            v = votes.get(party) if votes else None
            if total and v is not None:
                insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                                   definition_version=d["definition_version"], value=v / total * d.get("scale", 1),
                                   status="derived", numerator=v, denominator=total, **obs)
            else:
                insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                                   definition_version=d["definition_version"], value=None, status="missing",
                                   method_note=note, **obs)
        result[indicator_id] = len(units)
    result["parties_not_listed"] = sorted(seen - set(targets))
    return result
