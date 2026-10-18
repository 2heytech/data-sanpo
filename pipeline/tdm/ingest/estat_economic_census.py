"""経済センサス‐活動調査（令和3年6月1日現在）の町丁・大字別の民営事業所数・従業者数を取り込む。

e-Stat 統計GIS の小地域の表 T001167「産業（大分類）別民営事業所数及び男女別従業者数」（都道府県ごとの zip の中の
tblT001167Cxx.txt、cp932 の CSV。2026-10-10 に GitHub Actions から取得して確認）。
  1行目が列コード（KEY_CODE, CITY_NAME, AZA_CODE, AZA_NAME, T001167001, …）、2行目が列名
  （T001167001「AR_全産業（S_公務を除く）」の事業所数、T001167019 が同じ区分の従業者数）。
  KEY_CODE は市区町村コード5桁＋町丁・大字コード12桁。各市区町村の最後に「その他」（町丁・大字が分からない
  事業所）の行がある。「-」は該当なし（0）。2021年の表には秘匿（X）や空欄の値はない（あれば取込を止める）。

町丁・大字のコードは国勢調査の小地域のコードと体系が違うため、町丁・大字の名前で国勢調査の小地域（地図の境界）に
対応付ける。表記ゆれは犯罪の表と同じ正規化に加え、「条・丁・線・号・番・地割」の前の漢数字（札幌市の「北三条」、
堺市の「浅香山町一丁」）と旧字（澤・嶋など）をそろえて吸収する。経済センサスが丁目まで分けていて、地図では
丁目に分かれていない町（「令和島１丁目」と地図の「令和島」）は、丁目の行をその町に合計する（細かい単位を
粗い単位にまとめるだけで、割り振りはしない）。対応できない行（「その他」や名前の違う大字など）は
市区町村の合計にだけ入る。対応できない小地域は値なしにする（0にしない）。市区町村の値は全行の合計。
2026-10-10 の確認（北海道・東京都・大阪府）で、対応できない行の多くは札幌市の条・丁目の区切りの違いなど。

同じ調査の次の表も、同じやり方で取り込む（docs/design-changes.md #149）。
- 表31「経営組織(2区分)、産業(中分類)別全事業所数及び男女別従業者数－市区町村、町丁・大字」
  （kind = estat_economic_census_town_industry、都道府県ごとの Excel。2026-10-18 に全都道府県を取得して確認）。
  数百列・数十 MB あるので、取得するときに必要な列（fetch.reduce_xlsx）と経営組織「0_総数」の行だけの CSV にする。
  列は「市区町村・町丁大字コード」（市区町村コード5桁＋12桁、市区町村の合計の行は5桁）、「市区町村コード」、
  「町丁・大字名」（市区町村の合計の行は空）、「経営組織」と「75_宿泊業|事業所数」などの値。全事業所（国・地方公共団体の
  事業所を含む）の値。各市区町村に「その他」の行があり、町丁・大字の行の合計は市区町村の合計の行と一致する。
  「-」は該当なし（0）。秘匿はない。政令指定都市は市の合計の行と区ごとの行がある（区の行を使う）。
- 表9-1A「産業(小分類)別全事業所数－全国、都道府県、市区町村」（kind = estat_economic_census_municipal_industry、
  全国1ファイル）。小分類（「751_旅館，ホテル」など）の事業所数を市区町村・都道府県の値として入れる。
  「地域識別コード」（a 全国・都道府県、1 政令指定都市・特別区部、0 区、2 市、3 町村）と「地域区分」（「01101_札幌市中央区」）。
  政令指定都市の市全体の行と特別区部の行は使わない（区ごとの行がある）。
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from ..db import insert_observation
from .estat_small_area import parse_cell
from .keishicho_crime import _kanji_number, normalize_name

KIND = "estat_economic_census"
TOWN_INDUSTRY = "estat_economic_census_town_industry"
MUNICIPAL_INDUSTRY = "estat_economic_census_municipal_industry"
NO_MATCH_NOTE = "経済センサスの町丁・大字と地図の小地域を名前で対応付けられないため値なし"


OLD_KANJI = str.maketrans({"澤": "沢", "嶋": "島", "邊": "辺", "邉": "辺", "﨑": "崎", "髙": "高", "濱": "浜", "冨": "富"})
CHOME = re.compile(r"\d+丁目?$")


def town_key(name: str) -> str:
    """町丁・大字の名前を照合用にそろえる（両方の表に同じ処理をする）。"""
    s = normalize_name(name).translate(OLD_KANJI)
    return re.sub(r"[〇一二三四五六七八九十]+(?=(丁|条|線|号|番|地割))", lambda m: _kanji_number(m.group()), s)


def read_rows(path: Path, encoding: str = "cp932") -> tuple[list[str], list[list[str]]]:
    records = list(csv.reader(io.StringIO(path.read_bytes().decode(encoding))))
    return [c.strip() for c in records[0]], [r for r in records[2:] if r and r[0].strip()]


def _records_small_area(path: Path, columns: set[str], encoding: str):
    """統計GIS の小地域の表（T001167）の行。(市区町村コード5桁, 市区町村名, 町丁・大字名, 列 → セル)。"""
    labels, rows = read_rows(path, encoding)
    cols = {c: labels.index(c) for c in columns}
    name_col = labels.index("AZA_NAME")
    for r in rows:
        yield r[0].strip()[:5], r[1].strip(), r[name_col], {c: r[j] for c, j in cols.items()}


def _records_town_industry(path: Path, columns: set[str]):
    """表31（取得時に必要な列だけにした CSV）の町丁・大字の行（市区町村の合計の行は除く）。"""
    with path.open(encoding="utf-8", newline="") as f:
        rows = csv.reader(f)
        labels = next(rows)
        cols = {c: labels.index(c) for c in columns}
        c_code, c_muni, c_town = labels.index("市区町村コード"), labels.index("市区町村名"), labels.index("町丁・大字名")
        for r in rows:
            if r and r[c_town].strip():
                yield r[c_code].strip(), r[c_muni].strip(), r[c_town], {c: r[j] for c, j in cols.items()}


def ingest(conn: sqlite3.Connection, files: list[Path], source_id: str, catalog: dict,
           period: tuple[str, str, str], boundary_version: str, encoding: str = "cp932",
           kind: str = KIND) -> dict:
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == kind}
    columns = {d["column"] for d in targets.values()}
    munis = {r[0] for r in conn.execute("SELECT entity_id FROM entities WHERE entity_type = 'municipality'")}
    areas: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    # 地図に使う最新の境界にある小地域だけ（過去の国勢調査にしかない同じ名前の小地域と取り違えない）
    for r in conn.execute("""SELECT e.entity_id, e.name, e.parent_id FROM entities e
                             JOIN boundaries b ON b.entity_id = e.entity_id AND b.boundary_version = ?
                             WHERE e.entity_type = 'small_area'""", (boundary_version,)):
        areas[r["parent_id"]][town_key(r["name"])].append(r["entity_id"])
    result = {"municipalities": 0, "areas": 0, "rows": 0, "unmatched_rows": 0, "unmatched_areas": 0,
              "unmatched_examples": []}
    for path in files:
        records = (_records_town_industry(path, columns) if kind == TOWN_INDUSTRY
                   else _records_small_area(path, columns, encoding))
        muni_sum: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        area_sum: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for code, muni_name, town, raw in records:
            muni = f"muni-{code}"
            if muni not in munis:
                continue   # 対象外の都道府県・政令指定都市の市全体など
            result["rows"] += 1
            cells = {c: parse_cell(v) for c, v in raw.items()}   # 「-」は0
            if any(cell.value is None for cell in cells.values()):
                # 2021年の表には秘匿（X）・空欄がない（2026-10-15・10-18 に全都道府県で確認）。あれば0にせず止める
                raise ValueError(f"{path.name}: 秘匿・空欄のセルがあります（0 にしないよう取込を見直す）: {code} {town}")
            values = {c: cell.value for c, cell in cells.items()}
            for c, v in values.items():
                muni_sum[muni][c] += v
            key = town_key(town)
            ids = areas.get(muni, {}).get(key, [])
            if not ids and CHOME.search(key):
                # 地図では丁目に分かれていない町（丁目の行を町にまとめる）
                ids = areas.get(muni, {}).get(CHOME.sub("", key), [])
            if len(ids) != 1:   # 対応なし・同じ名前の小地域が複数（どちらか決められない）
                result["unmatched_rows"] += 1
                if len(result["unmatched_examples"]) < 30 and town.strip() not in ("", "その他"):
                    result["unmatched_examples"].append(muni_name + town.strip())
                continue
            for c, v in values.items():
                area_sum[ids[0]][c] += v
        for muni, sums in muni_sum.items():
            for indicator_id, d in targets.items():
                base = dict(indicator_id=indicator_id, definition_version=d["definition_version"],
                            period_start=period[0], period_end=period[1], period_kind=period[2],
                            source_id=source_id)
                insert_observation(conn, entity_id=muni, value=sums[d["column"]], status="observed", **base)
                for ids in areas.get(muni, {}).values():
                    for entity_id in ids:
                        got = area_sum.get(entity_id)
                        if got is not None:
                            insert_observation(conn, entity_id=entity_id, value=got[d["column"]],
                                               status="observed", **base)
                        else:
                            insert_observation(conn, entity_id=entity_id, value=None, status="missing",
                                               method_note=NO_MATCH_NOTE, **base)
            result["municipalities"] += 1
            result["areas"] += sum(1 for ids in areas.get(muni, {}).values() for e in ids if e in area_sum)
            result["unmatched_areas"] += sum(1 for ids in areas.get(muni, {}).values() for e in ids
                                             if e not in area_sum)
    return result


def ingest_municipal_industry(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict,
                              period: tuple[str, str, str]) -> dict:
    """表9-1A（取得時に必要な列だけにした CSV）。市区町村・都道府県の事業所数。"""
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == MUNICIPAL_INDUSTRY}
    result = {"municipalities": 0, "prefectures": 0}
    with path.open(encoding="utf-8", newline="") as f:
        rows = csv.reader(f)
        labels = next(rows)
        c_area = labels.index("地域区分")
        cols = {k: labels.index(d["column"]) for k, d in targets.items()}
        for r in rows:
            code = r[c_area].strip()[:5]
            if not re.fullmatch(r"\d{5}", code) or code == "00000":
                continue
            if code.endswith("000"):
                entity_id, counter = f"pref-{code[:2]}", "prefectures"
            else:
                entity_id, counter = f"muni-{code}", "municipalities"
            if not conn.execute("SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)).fetchone():
                continue   # 対象外の都道府県、政令指定都市の市全体・特別区部の行（区ごとの行を使う）
            for indicator_id, d in targets.items():
                cell = parse_cell(r[cols[indicator_id]])
                if cell.value is None:
                    raise ValueError(f"{path.name}: 秘匿・空欄のセルがあります（0 にしないよう取込を見直す）: {r[c_area]}")
                insert_observation(conn, entity_id=entity_id, indicator_id=indicator_id,
                                   definition_version=d["definition_version"], value=cell.value, status="observed",
                                   period_start=period[0], period_end=period[1], period_kind=period[2],
                                   source_id=source_id)
            result[counter] += 1
    return result
