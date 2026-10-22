"""在留外国人統計（出入国在留管理庁、各年12月末現在）の都道府県別・市区町村別の表から、都道府県ごと・市区町村ごとの
国籍・地域別の人数をまとめる（docs/design-changes.md #155）。

令和6年末以降の「在留外国人統計テーブルデータ（国籍・地域別 在留資格別 市区町村別）」（24-12-t2.xlsx・25-12-t2.xlsx）は、
シートには市区町村ごとの合計（ピボットテーブル）しかなく、国籍・地域別 在留資格別 年齢別 性別の行は Excel の
データモデル（Power Pivot、xl/model/item.data）の中にある。公開版の取込のたびにこれを読むと、読むためのライブラリ
（pbixray。pandas などを使う）が公開版の取込に要るので、Actions「Prepare derived sources」で読んで小さな CSV にし、
Release「derived-sources」に置く。

市区町村別の表（データモデル、2026-10-22 に確認）の列: 国籍・地域（「01_023：中国」のようにコード付き）, 在留資格,
年齢（５歳階級）, 年齢, 性別, 市区町村コード（5桁）, 都道府県（「13：東京都」）, 政令指定都市, 市区町村, 在留外国人数。
1行は国籍・地域 × 在留資格 × 年齢 × 性別 × 市区町村の人数で、人数が0の組み合わせの行はない。市区町村ごとの合計は、
シートのピボットテーブルの値と全市区町村で一致する（令和6・7年末）。
  - 在留外国人が10人以下の市区町村（令和6年末58・令和7年末52）は、国籍・地域と在留資格が「-」の行だけになっていて、
    国籍・地域別の人数はわからない（令和5年末の表で全国の「その他」にまとめられていたもの）。
  - 市区町村コード 99999 は「未定・不詳」（住所の市区町村がわからない人。都道府県は空のことがある）。
都道府県別の表（24-12-t1.xlsx・25-12-t1.xlsx「在留外国人統計テーブルデータ（国籍・地域別 在留資格別 都道府県別
年齢・性別）」）は、隠したシート（「令和7年12月末」など）に行がある（列: 国籍・地域, 在留資格, 性別, 年齢（５歳階級）,
年齢, 都道府県, 在留外国人数）。こちらは国籍・地域を伏せた行がなく、市区町村が未定・不詳の人も都道府県に入っている
（都道府県の「48：未定・不詳」もある）。全国の合計は市区町村別の表と同じ。

まとめた CSV（gzip）の列: 市区町村コード, 都道府県, 市区町村, 国籍・地域, 在留外国人数。
国籍・地域はコードを除いた名前（中国、台湾、（朝鮮）など）。国籍・地域を伏せた行は「-」のまま残す（取込で値なしにする）。
都道府県の行（コードは「13000」のように下3桁が 000、市区町村は空）は都道府県別の表から、市区町村の行（未定・不詳の
99999 を含む）は市区町村別の表から作る。
"""
from __future__ import annotations

import csv
import gzip
import re
import time
from collections import defaultdict
from pathlib import Path

from ..fetch import download
from ..progress import progress
from ..xlsx import iter_sheet_rows, sheet_names

HEAD = ["市区町村コード", "都道府県", "市区町村", "国籍・地域", "在留外国人数"]
PREFECTURE_HEAD = ("国籍・地域", "都道府県", "在留外国人数")


def read_model(path: Path) -> list[dict]:
    """xlsx のデータモデル（Power Pivot）の表を読み、行（列名 → 値）の一覧を返す。"""
    from pbixray import PBIXRay   # Actions「Prepare derived sources」だけで使う（pyproject の prepare）
    from pbixray.meta.xml_source import XmlMetadataSource, XMObjectDocument

    # pbixray 0.15.5 は表の情報のファイル（〜.tbl.xml）を名前が「H」「R」で始まらないものに限っていて、
    # 表の名前が「R712 テーブルデータ用…」の令和7年末の表では行数が0になり、何も読めない。
    # 除きたいのは「H$」「R$」で始まる内部の表だけなので、そのように読み直す。
    def extract_tbl_metadata(self):
        self._load_xml_collection(re.compile(r"^(?!H\$|R\$)([^$]*?)\.(\d+)\.tbl\.xml$"),
                                  lambda s: XMObjectDocument.from_xml_string(s).root_object,
                                  self._tbl_objects, "table")
    XmlMetadataSource._extract_tbl_metadata = extract_tbl_metadata

    model = PBIXRay(str(path))
    tables = list(model.tables)
    if len(tables) != 1:
        raise ValueError(f"{path.name}: データモデルの表が1つではありません（{tables}）")
    df = model.get_table(tables[0])
    if df.empty:
        raise ValueError(f"{path.name}: データモデルの表 {tables[0]} に行がありません")
    return df.to_dict("records")


def _name(v) -> str:
    """「01_023：中国」→「中国」、「13：東京都」→「東京都」。"""
    s = v.strip() if isinstance(v, str) else ""   # 未定・不詳の行は都道府県が空（pandas の NA）のことがある
    return s.split("：", 1)[1].strip() if "：" in s else s


def _count(r: dict) -> int:
    try:
        return int(r["在留外国人数"])
    except (TypeError, ValueError):   # 人数が欠けている行は0にしない
        raise ValueError(f"人数がない行があります: {r}") from None


def read_prefecture_table(path: Path) -> list[dict]:
    """都道府県別の表の、隠したシートの行（列名 → 値）。"""
    for i, _ in enumerate(sheet_names(path)):
        rows = iter_sheet_rows(path, i)
        head = [str(c).strip() if c is not None else "" for c in next(rows, [])]
        if all(h in head for h in PREFECTURE_HEAD):
            return [dict(zip(head, r)) for r in rows if any(c is not None for c in r)]
    raise ValueError(f"{path.name}: 列 {PREFECTURE_HEAD} のあるシートが見つかりません")


def summarize_prefectures(rows: list[dict]) -> list[list]:
    """都道府県ごとの国籍・地域別の人数（CSV の行）。未定・不詳の都道府県は除く。"""
    prefs: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        m = re.fullmatch(r"(\d{2})：(.+)", str(r["都道府県"] or "").strip())
        if not m:
            raise ValueError(f"都道府県の形が違います: {r}")
        n = _count(r)
        if int(m.group(1)) > 47:   # 48：未定・不詳
            continue
        prefs[(m.group(1) + "000", m.group(2))][_name(r["国籍・地域"])] += n
    return [[code, pref, "", nat, n] for (code, pref), nats in sorted(prefs.items()) for nat, n in sorted(nats.items())]


def summarize_municipalities(rows: list[dict]) -> list[list]:
    """市区町村ごとの国籍・地域別の人数（CSV の行）。国籍・地域を伏せた行は「-」のまま。"""
    munis: dict[tuple[str, str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        code = str(r["市区町村コード"]).strip()
        if not re.fullmatch(r"\d{5}", code):
            raise ValueError(f"市区町村コードの形が違います: {code!r}")
        munis[(code, _name(r["都道府県"]), _name(r["市区町村"]))][_name(r["国籍・地域"])] += _count(r)
    return [[code, pref, muni, nat, n] for (code, pref, muni), nats in sorted(munis.items()) for nat, n in sorted(nats.items())]


def write(path: Path, rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(HEAD)
        w.writerows(rows)


def _fetch(url: str, path: Path, downloader) -> Path:
    if not path.exists():
        data = downloader(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.rename(path)
    return path


def prepare(cfg: dict, outputs: dict[str, Path], work: Path, prefs: list[str], load_towns,
            downloader=download, reader=read_model, prefecture_reader=read_prefecture_table) -> dict:
    """prefs は使わない（表は全国で1つ。都道府県を絞ったときも全国をまとめる）。
    cfg["files"] は役割（outputs と同じ名前）ごとの { municipal = 市区町村別の表, prefecture = 都道府県別の表 }。"""
    result = {}
    for role, urls in cfg["files"].items():
        started = time.monotonic()
        muni_rows = reader(_fetch(urls["municipal"], work / f"{role}-municipal.xlsx", downloader))
        pref_rows = prefecture_reader(_fetch(urls["prefecture"], work / f"{role}-prefecture.xlsx", downloader))
        total, pref_total = sum(map(_count, muni_rows)), sum(map(_count, pref_rows))
        if total != pref_total:   # 読み違い（データモデルの読み落としなど）に気づくため
            raise ValueError(f"{role}: 全国の合計が市区町村別の表 {total:,} 人と都道府県別の表 {pref_total:,} 人で違います")
        out = summarize_prefectures(pref_rows) + summarize_municipalities(muni_rows)
        write(outputs[role], out)
        masked = sorted({r[0] for r in out if r[3] == "-"})
        progress(f"在留外国人 {role}: {total:,} 人、市区町村別 {len(muni_rows):,} 行・都道府県別 {len(pref_rows):,} 行 → "
                 f"{len(out):,} 行、国籍・地域を伏せた市区町村 {len(masked)}（{time.monotonic() - started:.0f} 秒）")
        result[role] = {"rows": len(out), "total": total, "masked_municipalities": len(masked)}
    return result
