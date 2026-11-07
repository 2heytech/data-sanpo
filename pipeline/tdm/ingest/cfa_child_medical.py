"""こども家庭庁「こどもに係る医療費の助成についての調査」の別紙3（全国の市区町村の実施状況、PDF）から、
子どもの医療費の助成の対象年齢を取り込む（docs/design-changes.md #212）。

形式（令和7年度（2025年4月1日時点）の PDF（32ページ）を 2026-11-07 に GitHub Actions から取得し、
pdftotext -layout で確認）: 1行が1市区町村（全国1,741。政令指定都市は市全体の行だけ、東京都の23区は区ごと）で、
「北海道 1 札幌市 18歳年度末 18歳年度末 有 有 有 有」のように、都道府県名・番号・市区町村名・対象年齢（通院・入院）・
所得制限（通院・入院）・一部自己負担（通院・入院）。対象年齢は「◯歳年度末」か「就学前」（6歳の年度末まで）。
ページごとに見出しの行がくり返される（ページの境目で同じ番号の同じ行がくり返されることもある）。
名前に「※」が付く市町村は、18歳の年度末より後は大学などに通う人だけが対象（注記）。番号は表の通し番号で、
市区町村コードではないので、都道府県の中の名前で地図の市区町村に合わせる。
PDF は pdftotext（poppler-utils）でテキストにしてから読む。テストの見本は同じ形のテキスト（.txt）を使う。
政令指定都市の助成は市全体の制度なので、区にも市の値を入れ、そのことを注記に書く（制度の内容で、数を割り振る
ものではない）。都道府県の値は作らない。
指標（definition の child_medical）: outpatient（通院の対象年齢）・inpatient（入院の対象年齢）。
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

from ..db import insert_observation
from ..regions import PREFECTURES
from .isj_geocode import normalize_municipality
from .mext_school_aid import pdf_text

KIND = "cfa_child_medical"
ROW = re.compile(r"^\s*(\S+?[都道府県])\s+\d+\s+(\S+)\s+(\S+)\s+(\S+)\s+([有無])\s+([有無])\s+([有無])\s+([有無])\s*$")
PREF_CODE = {name: code for code, name in PREFECTURES.items()}
ZEN = str.maketrans("０１２３４５６７８９", "0123456789")
STUDENT_NOTE = "18歳の年度末より後は、大学などに通う人だけが対象（一定の所得制限あり）"


def _age(s: str) -> tuple[float, str | None]:
    s = unicodedata.normalize("NFKC", s)
    if s == "就学前":
        return 6.0, "小学校に入る前（6歳の年度末）まで"
    if m := re.fullmatch(r"(\d+)歳年度末", s):
        return float(m.group(1)), None
    raise ValueError(f"対象年齢が読めません: {s}")


def _period(text: str) -> str:
    m = re.search(r"令和(\d+|元)年(\d+)月(\d+)日時点", unicodedata.normalize("NFKC", text[:2000]).translate(ZEN))
    if not m:
        raise ValueError("「令和◯年◯月◯日時点」が読めません")
    year = 2018 + (1 if m.group(1) == "元" else int(m.group(1)))
    return f"{year:04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def read_table(path: Path) -> tuple[str, dict[tuple[str, str], dict]]:
    """(時点, (都道府県コード, 市区町村名) → {"outpatient", "inpatient", "notes"})。"""
    text = pdf_text(path)
    out: dict[tuple[str, str], dict] = {}
    seen: dict[tuple[str, str], list[str]] = {}
    for line in text.splitlines():
        m = ROW.match(line)
        if not m:
            continue
        pref = PREF_CODE.get(m.group(1))
        if pref is None:
            raise ValueError(f"{path.name}: 都道府県名が読めません: {line}")
        name = m.group(2)
        (outpatient, out_note), (inpatient, in_note) = _age(m.group(3)), _age(m.group(4))
        income = _pair("所得制限", m.group(5), m.group(6))
        copay = _pair("一部自己負担", m.group(7), m.group(8))
        notes = [income, copay] + (["通院は" + out_note] if out_note else []) + (["入院は" + in_note] if in_note else [])
        if "※" in name:
            notes.append(STUDENT_NOTE)
        key = (pref, name.replace("※", ""))
        if key in out:
            if seen[key] == line.split():
                continue   # ページの境目でくり返された同じ番号の同じ行（令和7年度の奈良県安堵町）
            raise ValueError(f"{path.name}: {m.group(1)}{key[1]} の行が2つあります")
        out[key] = {"outpatient": outpatient, "inpatient": inpatient, "notes": notes}
        seen[key] = line.split()
    if not out:
        raise ValueError(f"{path.name}: 市区町村の行が読めません")
    return _period(text), out


def _pair(label: str, outpatient: str, inpatient: str) -> str:
    word = {"有": "あり", "無": "なし"}
    if outpatient == inpatient:
        return f"{label}{word[outpatient]}"
    return f"{label}は通院{word[outpatient]}・入院{word[inpatient]}"


def _municipalities(conn: sqlite3.Connection) -> tuple[dict, dict]:
    """((都道府県コード, 市区町村名) → 地域ID, (都道府県コード, 政令指定都市名) → 区の地域ID)。"""
    names, wards = {}, {}
    for r in conn.execute("SELECT entity_id, name, region FROM entities WHERE entity_type = 'municipality'"):
        pref = r["entity_id"][5:7]
        names[(pref, normalize_municipality(r["name"]))] = r["entity_id"]
        if r["region"] and pref != "13":
            wards.setdefault((pref, normalize_municipality(r["region"])), []).append(r["entity_id"])
    return names, wards


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict, period: str) -> dict:
    got, data = read_table(path)
    if got != period:
        raise ValueError(f"{path.name}: {got} 時点の表です（設定は {period}）")
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == KIND}
    names, wards = _municipalities(conn)
    base = dict(period_start=period, period_end=period, period_kind="point", source_id=source_id)
    result = {"municipalities": 0, "designated_cities": 0, "unmatched": []}
    for (pref, name), values in sorted(data.items()):
        key = (pref, normalize_municipality(name))
        if key in names:
            entities, extra = [names[key]], []
            result["municipalities"] += 1
        elif key in wards:
            entities, extra = wards[key], [f"{name}全体の制度"]
            result["designated_cities"] += 1
        else:
            result["unmatched"].append(f"{PREFECTURES[pref]}{name}")
            continue
        note = "。".join(extra + values["notes"])
        for entity_id in entities:
            for indicator_id, d in targets.items():
                insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                                   definition_version=d["definition_version"], value=values[d["child_medical"]],
                                   status="observed", method_note=note, **base)
    return result
