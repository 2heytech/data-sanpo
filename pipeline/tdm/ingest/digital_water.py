"""デジタル庁「水道事業等の経営状況に関するダッシュボード」の公開データ（縦持ちデータテーブル、CSV の ZIP）から、
家庭用の水道料金（1か月20m³・口径20mm）を取り込む（docs/design-changes.md #213）。

形式（2026-07-03 更新の ZIP を 2026-11-07 に GitHub Actions から取得して確認）: 年度ごとの CSV（2014.csv〜2024.csv、
UTF-8）。1行が「年度・水道事業者・事業の区分・項目」の値で、列は fiscal_year, local_public_enterprise_code（6桁。
市区町村営は団体コード5桁＋検査数字）, local_public_enterprise_name, facility_code（001 末端給水事業・005 法適用簡易水道事業・
006 末端給水事業のうち同一会計内の簡易水道分）, cond_2_operating_entity（1:都道府県営・2:指定市営・3:市営・4:町村営・
5:企業団営）, item_name, item_value など。元は総務省「地方公営企業決算状況調査」。
  料金: item_name「6.料金__(2)料金(家庭用)__1か月20㎥当たり料金__口径20mm」（円、税抜き。ダッシュボードの定義）
  給水人口: item_name「4.施設__(3)現在給水人口(人)」
市区町村との対応（水道事業者のコードは市区町村のコードとは限らない）:
  1. 市区町村営の水道事業は、コードの先頭5桁の市区町村の料金にする（末端給水事業。ない市町村は法適用簡易水道事業）。
     料金が0か空欄の事業（小さな簡易水道）は値なしにする（0円にしない）。
     ただし、その市区町村の水道事業の給水人口の合計が住民（国勢調査の人口）の main_supplier_share（半分）未満なら、
     その料金は住民の多くには当てはまらないので値なしにする（県営水道や井戸・小さな簡易水道などが多い地域）。
  2. 出典の設定 suppliers（水道事業者のコード → 主に給水する市区町村のコード）に書いた市区町村は、その事業者の料金にする。
     都道府県営・企業団営の水道や、隣の市の水道が給水する市区町村。事業者の給水人口と市区町村の人口の合計が合うことを
     2026-11-07 に確かめて書いた（pipeline/config/sources.toml）。
  3. 出典の設定 area_tariffs（水道事業者のコード → 市区町村のコード）の企業団は、統合した市町村ごとに料金が違う（または
     統一を確かめられない）ので、給水する市区町村は値なしにして注記を書く。
政令指定都市は市全体の料金なので、区にも市の値を入れ、そのことを注記に書く（料金表で、数を割り振るものではない）。
都道府県の値は作らない。

元の表の誤り（#239）: 2024年度に初めて表に出た小さな簡易水道（法適用簡易水道事業）には、1m³あたりの単価を入れたものや、
20m³の料金に超過料金を1m³分しか足していないものがある。
  - 出典の設定 fee_fixes（水道事業者のコード → table: 元の表の料金、fee: 市町村の料金表から求めた料金、note: 注記）で直す。
    fee を書かなければ値なしにする。元の表の料金が table と違えば止める（表が直ったか、別の値になったので確かめ直す）。
  - 料金が low_fee_floor より安い事業者と、20m³の料金が10m³の料金より min_step 未満しか高くない事業者（超過料金を1m³分しか
    足していない型）は、fee_fixes か low_fees_checked（料金表で確かめて正しかった事業者 → 元の表の料金）に書いていなければ
    止める。前の年度と同じ料金の事業者は、毎年同じ値を報告しているので、20m³と10m³の差では止めない。
"""
from __future__ import annotations

import csv
import io
import sqlite3
import zipfile
from pathlib import Path

from ..db import insert_observation
from ..regions import designated_city_wards, map_municipalities

KIND = "digital_water_supply"
FEE_ITEM = "6.料金__(2)料金(家庭用)__1か月20㎥当たり料金__口径20mm"
FEE10_ITEM = "6.料金__(2)料金(家庭用)__1か月10㎥当たり料金__口径20mm"
POP_ITEM = "4.施設__(3)現在給水人口(人)"
MUNICIPAL = ("2", "3", "4")   # 指定市営・市営・町村営
NONE_NOTE = "市区町村の水道事業がなく、ほかの事業者（企業団など）や法の適用を受けない簡易水道・井戸などで給水している地域です"
LOW_NOTE = "市区町村の水道事業が給水しているのは住民の半分未満のため、値を表示しません（ほかは県営水道・簡易水道・井戸など）"
NO_FEE_NOTE = "市区町村の水道事業の料金（1か月20m³・口径20mm）が表にない（0円か空欄の）ため、値を表示しません"
AREA_NOTE = "{name}が給水していて、地域（統合前の市町村）ごとに料金が違うか、統一を確かめられないため、値を表示しません"


ITEMS = {FEE_ITEM: "fee", FEE10_ITEM: "fee10", POP_ITEM: "population"}


def read_table(path: Path, year: int, required: bool = True) -> dict[tuple[str, str], dict]:
    """(水道事業者のコード, 事業の区分) → {"code", "facility", "name", "entity", "fee", "fee10", "population"}。
    required でなければ、その年度の CSV や料金の項目がなくても止めない（前の年度と比べるとき）。"""
    with zipfile.ZipFile(path) as z:
        name = next((n for n in z.namelist() if Path(n).name == f"{year}.csv"), None)
        if name is None:
            if not required:
                return {}
            raise ValueError(f"{path.name}: {year}.csv がありません（{z.namelist()}）")
        text = z.read(name).decode("utf-8-sig")
    out: dict[tuple[str, str], dict] = {}
    for r in csv.DictReader(io.StringIO(text)):
        key = ITEMS.get(r["item_name"])
        if key is None:
            continue
        if r["fiscal_year"] != str(year):
            raise ValueError(f"{path.name}: {year}.csv に {r['fiscal_year']} 年度の行があります")
        code, facility = r["local_public_enterprise_code"], r["facility_code"]
        u = out.setdefault((code, facility), {"code": code, "facility": facility, "name": r["local_public_enterprise_name"],
                                              "entity": r["cond_2_operating_entity"][:1]})
        value = r["item_value"].replace(",", "").strip()
        u[key] = float(value) if value else None
    if required and not any(u.get("fee") for u in out.values()):
        raise ValueError(f"{path.name}: 料金の項目「{FEE_ITEM}」がありません")
    return out


def _main(utilities: dict, code: str) -> dict | None:
    """水道事業者の料金の行（末端給水事業、なければ法適用簡易水道事業）。"""
    return next((utilities[(code, f)] for f in ("001", "005") if utilities.get((code, f), {}).get("fee")), None)


def _fee(main: dict, note: str | None) -> tuple[float | None, str | None]:
    """料金の行の料金と注記。設定の fee_fixes で直した行は、直した料金（または値なし）とそのことを書いた注記。"""
    if "fix" not in main:
        return main["fee"], note
    fee, fix_note = main["fix"]
    return fee, fix_note if note is None else f"{note}。{fix_note}"


def _apply_fixes(utilities: dict, cfg: dict, result: dict) -> None:
    """設定の fee_fixes を料金の行に付ける（元の表の料金が設定の table と違えば止める）。"""
    for code, fix in cfg.get("fee_fixes", {}).items():
        main = _main(utilities, code)
        if main is None:
            result["missing_fixes"].append(code)   # その年度の表にない（見本データなど）
            continue
        if main["fee"] != fix["table"]:
            raise ValueError(f"{main['name']}（{code}）の料金が {main['fee']:g} 円で、設定の table（{fix['table']} 円）と違います。"
                             "元の表が直った可能性があるので、料金表で確かめ直して設定を直してください")
        main["fix"] = (fix.get("fee"), fix["note"])


def _check_low_fees(used: dict[str, dict], previous: dict, cfg: dict) -> None:
    """入力の誤りと見られる料金（安すぎる・20m³と10m³の差が小さすぎる）が、設定で確かめたものだけかを確かめる。"""
    floor = float(cfg.get("low_fee_floor", 0))
    step = float(cfg.get("min_step", 0))
    checked = cfg.get("low_fees_checked", {})
    unchecked = []
    for code, main in sorted(used.items()):
        if "fix" in main:
            continue
        fee, fee10 = main["fee"], main.get("fee10")
        stable = previous.get((code, main["facility"]), {}).get("fee") == fee
        suspicious = fee < floor or (fee10 is not None and 0 < fee - fee10 < step and not stable)
        if code in checked:
            if checked[code] != fee:
                raise ValueError(f"{main['name']}（{code}）の料金が {fee:g} 円で、設定の low_fees_checked（{checked[code]} 円）と"
                                 "違います。料金表で確かめ直して設定を直してください")
        elif suspicious:
            unchecked.append(f"{main['name']}（{code}、20m³ {fee:g} 円・10m³ {fee10 if fee10 is None else f'{fee10:g}'} 円）")
    if unchecked:
        raise ValueError("料金が安すぎるか、20m³と10m³の差が小さすぎる水道事業者があります。料金表で確かめて、"
                         "出典の設定 fee_fixes か low_fees_checked に書いてください: " + "、".join(unchecked))


def _population(conn: sqlite3.Connection) -> dict[str, float]:
    """市区町村コード → いちばん新しい国勢調査の人口（地図の市区町村。政令指定都市の区を含む）。"""
    out = {}
    for r in conn.execute(
            """SELECT entity_id, value FROM observations WHERE indicator_id = 'population_total'
                 AND entity_id LIKE 'muni-%' AND value IS NOT NULL ORDER BY period_start"""):
        out[r["entity_id"][5:]] = r["value"]
    return out


def ingest(conn: sqlite3.Connection, path: Path, source_id: str, catalog: dict, cfg: dict) -> dict:
    year = int(cfg["fiscal_year"])
    targets = {k: d for k, d in catalog.items() if d.get("source_kind") == KIND}
    utilities = read_table(path, year)
    previous = read_table(path, year - 1, required=False)
    population = _population(conn)
    known = {r["entity_id"][5:] for r in map_municipalities(conn)}
    share = float(cfg.get("main_supplier_share", 0.5))

    def area(code: str) -> list[str]:
        """市区町村コード → 地図の市区町村コード（政令指定都市は区）。"""
        if code in known:
            return [code]
        return [w[5:] for w in designated_city_wards(conn, code)]

    # 市区町村営の水道事業（市区町村コード → 料金の行と、その市区町村の水道事業の給水人口の合計）
    own: dict[str, tuple[dict, float]] = {}
    for (code, facility), u in utilities.items():
        if u["entity"] in MUNICIPAL:
            main = _main(utilities, code)
            served = own.get(code[:5], (None, 0.0))[1] + (u.get("population") or 0.0)
            own[code[:5]] = (main, served)
    values: dict[str, tuple[float | None, str | None]] = {}   # 地図の市区町村コード → (料金, 注記)
    result = {"own": 0, "suppliers": 0, "low_share": 0, "no_fee": 0, "area_tariffs": 0, "none": 0, "fixed": 0, "unmatched": [],
              "missing_suppliers": [], "missing_fixes": []}
    _apply_fixes(utilities, cfg, result)
    used: dict[str, dict] = {}   # 値に使った料金の行（水道事業者のコード → 行）
    for code, (main, served) in sorted(own.items()):
        wards = area(code)
        if not wards:
            result["unmatched"].append(code)   # 取り込む都道府県を絞ったとき
            continue
        if main is None:
            for w in wards:
                values[w] = (None, NO_FEE_NOTE)
            result["no_fee"] += 1
            continue
        residents = sum(population.get(w, 0.0) for w in wards)
        city = f"{main['name']}全体の料金" if wards != [code] else None
        if residents and served < residents * share:
            for w in wards:
                values[w] = (None, LOW_NOTE)
            result["low_share"] += 1
        else:
            for w in wards:
                values[w] = _fee(main, city)
            used[main["code"]] = main
            result["own"] += 1
    for supplier, codes in cfg.get("suppliers", {}).items():
        main = _main(utilities, supplier) if len(supplier) == 6 else own.get(supplier, (None, 0))[0]
        if main is None:
            result["missing_suppliers"].append(supplier)   # その年度の表にない（見本データなど）
            continue
        for code in codes:
            wards = area(code)
            if not wards:
                result["unmatched"].append(code)   # 取り込む都道府県を絞ったとき
                continue
            for w in wards:
                values[w] = _fee(main, f"{main['name']}の水道の料金")
            used[main["code"]] = main
            result["suppliers"] += 1
    for supplier, codes in cfg.get("area_tariffs", {}).items():
        name = next((u["name"] for (c, _), u in utilities.items() if c == supplier), supplier)
        for code in codes:
            for w in area(code):
                values[w] = (None, AREA_NOTE.format(name=name))
            result["area_tariffs"] += 1
    _check_low_fees(used, previous, cfg)
    result["fixed"] = sum(1 for m in used.values() if "fix" in m)
    base = dict(period_start=f"{year}-04-01", period_end=f"{year + 1}-03-31", period_kind="fiscal_year",
                source_id=source_id)
    for code in sorted(known):
        fee, note = values.get(code, (None, NONE_NOTE))
        if code not in values:
            result["none"] += 1
        for indicator_id, d in targets.items():
            insert_observation(conn, entity_id=f"muni-{code}", indicator_id=indicator_id,
                               definition_version=d["definition_version"], value=fee,
                               status="observed" if fee is not None else "missing", method_note=note, **base)
    return result
