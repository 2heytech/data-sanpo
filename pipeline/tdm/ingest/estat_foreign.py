"""全国の外国人の数を取り込む（e-Stat のファイル）。

住民基本台帳（総務省「住民基本台帳に基づく人口、人口動態及び世帯数」、各年1月1日現在）
  「【外国人住民】市区町村別人口、人口動態及び世帯数」の xlsx（令和3〜8年、2026-10-05 に GitHub Actions から
  取得して確認）。1シートで、0〜5行目が見出し（3行目「人口」・4行目「男／女／計」・5行目「団体コード…」）、
  6行目が全国の「合計」。団体コードは検査数字付きの6桁（131016＝千代田区）。都道府県の行は「130001」のように
  市区町村コードの下3桁が 000、政令指定都市の市全体の行（141003 横浜市）と区の行（141011）がある。
  末尾に注記の行がある。平成26〜令和2年は古い .xls 形式なので使わない（東京都は都の「外国人人口」で補う）。

在留外国人統計（出入国在留管理庁、各年12月末現在）
  令和3・4年末「第3表 市区町村別 国籍・地域別 在留外国人」（横長）: 1行目が列名（市区町村コード,
  都道府県市区町村, 総数, 中国, ベトナム, 韓国, フィリピン, ブラジル, ネパール, インドネシア, 米国, 台湾, タイ,
  その他）。市区町村コードは5桁で、都道府県（13000）・特別区（13100）・政令指定都市の市全体（14100）の行がある。
  末尾に「未定・不詳」と注記の行がある。
  令和5年末「市区町村別 国籍・地域別 在留資格別 在留外国人数」（縦長、シート「令和５年末」）: 1行目が列名
  （市区町村コード, 都道府県, 市区町村, 国籍・地域, 在留資格, 在留外国人数）。国籍・在留資格の組み合わせごとの
  行なので、国籍ごとに合計する。総数が10人以下の市区町村は全国で1つの「その他」（コード 99999）にまとめられて
  いるので、その市区町村は値なしにする（その都道府県の値も、市区町村がそろわないので出さない）。
  表にない国籍は、その市区町村では0人。令和6年末以降は国籍別の市区町村の表が読める形で公表されていない。
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from ..db import insert_observation
from ..regions import municipality_entity_id, prefecture_entity_id
from ..xlsx import read_sheet, sheet_names

JUKI_KIND = "soumu_juki_foreign"
ZAIRYU_KIND = "moj_zairyu_foreign"
OTHER_CODE = "99999"   # 令和5年末の表で、総数10人以下の市区町村をまとめた行


def _entity(conn: sqlite3.Connection, code5: str) -> str | None:
    """5桁の市区町村コードから、この公開版にある地域ID（都道府県・市区町村）を返す。"""
    entity_id = prefecture_entity_id(code5[:2]) if code5.endswith("000") else municipality_entity_id(code5)
    if conn.execute("SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)).fetchone():
        return entity_id
    return None   # 政令指定都市の市全体・特別区の合計・今回の対象外の都道府県・区の再編後の新しい区


def _number(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "…", "x", "X", "***"):
        return None
    return float(s)


def _write(conn, entity_id, targets, values: dict, source_id, period) -> None:
    for indicator_id, d in targets.items():
        v = values.get(d["column"])
        insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                           definition_version=d["definition_version"],
                           period_start=period[0], period_end=period[1], period_kind=period[2],
                           value=v, status="observed" if v is not None else "missing",
                           source_id=source_id)


def ingest_juki(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict,
                period: tuple[str, str, str]) -> dict:
    """住民基本台帳の外国人住民（市区町村別）。列は「見出し3行目/見出し4行目」（例: 人口/計）で指定する。"""
    rows = read_sheet(path, 0)
    targets = {i: d for i, d in catalog.items() if d.get("source_kind") == JUKI_KIND}
    head = next(i for i, r in enumerate(rows) if r and str(r[0]).strip() == "団体コード")
    labels = {f"{rows[head - 2][j]}/{rows[head - 1][j]}": j for j in range(3, len(rows[head - 1]))
              if rows[head - 1][j] is not None}
    missing = [d["column"] for d in targets.values() if d["column"] not in labels]
    if missing:
        raise KeyError(f"{path.name}: 列 {missing} が見つかりません（{sorted(labels)}）")
    n, prefs, unmatched = 0, 0, []
    for r in rows[head + 1:]:
        code = str(r[0] or "").strip()
        if not re.fullmatch(r"\d{6}", code):
            continue   # 全国の合計・注記
        entity_id = _entity(conn, code[:5])
        if entity_id is None:
            if not code[:5].endswith("000"):
                unmatched.append(code[:5])   # 政令指定都市の市全体など。確認用に一部を返す
            continue
        values = {d["column"]: _number(r[labels[d["column"]]]) for d in targets.values()}
        _write(conn, entity_id, targets, values, source_id, period)
        if entity_id.startswith("pref-"):
            prefs += 1
        else:
            n += 1
    return {"municipalities": n, "prefectures": prefs, "unmatched": unmatched[:30]}


def ingest_zairyu(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict,
                  period: tuple[str, str, str], sheet: str | None = None) -> dict:
    """在留外国人統計の市区町村別・国籍別。横長（令和3・4年末）と縦長（令和5年末）の両方を読む。"""
    rows = read_sheet(path, sheet if sheet else sheet_names(path)[0])
    targets = {i: d for i, d in catalog.items() if d.get("source_kind") == ZAIRYU_KIND}
    head = next(i for i, r in enumerate(rows) if r and str(r[0]).strip() == "市区町村コード")
    labels = [str(c).strip() if c is not None else "" for c in rows[head]]
    by_code: dict[str, dict[str, float | None]] = {}
    if "国籍・地域" in labels:   # 縦長: 国籍・在留資格ごとの行を国籍ごとに合計する
        ci, ni, vi = labels.index("市区町村コード"), labels.index("国籍・地域"), labels.index("在留外国人数")
        wanted = {d["column"] for d in targets.values()}
        sums: dict[str, dict[str, float]] = defaultdict(lambda: dict.fromkeys(wanted, 0.0))
        for r in rows[head + 1:]:
            code = str(r[ci] or "").strip()
            if not re.fullmatch(r"\d{5}", code) or code == OTHER_CODE:
                continue
            acc = sums[code]   # 表に出てくる市区町村は、出てこない国籍を0人とする
            nat = str(r[ni]).strip()
            if nat in acc:
                acc[nat] += _number(r[vi]) or 0.0
        by_code = dict(sums)
        prefecture_rows = False
    else:   # 横長: 列が国籍
        cols = {l: j for j, l in enumerate(labels) if l}
        missing = [d["column"] for d in targets.values() if d["column"] not in cols]
        if missing:
            raise KeyError(f"{path.name}: 列 {missing} が見つかりません（{labels}）")
        for r in rows[head + 1:]:
            code = str(r[0] or "").strip()
            if re.fullmatch(r"\d{5}", code):
                by_code[code] = {d["column"]: _number(r[cols[d["column"]]]) for d in targets.values()}
        prefecture_rows = True
    n, prefs, unmatched = 0, 0, []
    for code, values in sorted(by_code.items()):
        if code.endswith("000") and not prefecture_rows:
            continue
        entity_id = _entity(conn, code)
        if entity_id is None:
            if not code.endswith("000"):
                unmatched.append(code)
            continue
        _write(conn, entity_id, targets, values, source_id, period)
        if entity_id.startswith("pref-"):
            prefs += 1
        else:
            n += 1
    return {"municipalities": n, "prefectures": prefs, "unmatched": unmatched[:30]}
