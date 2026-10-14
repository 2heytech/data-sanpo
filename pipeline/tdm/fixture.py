"""開発・テスト用の架空データ（e-Stat と同じファイル形式）を作る。

実在しない団体コード（13199・13299・13499、全国版の確認用に神奈川県の 14199）と架空の地名を使う。
国勢調査の表と境界は都道府県ごとに data/raw/<キー>/<都道府県>/ に置く（design-changes #52）。
都の機関のデータ（犯罪・昼間人口など）と e-Stat「ファイル」の表は東京都の区市町村だけ。
本番の取込処理をそのまま通すことで、取込から公開ファイル生成までを検証できる。
"""
from __future__ import annotations

import csv
import json
import random
import zipfile
from pathlib import Path

import shapefile

FIXTURE_SOURCE = {
    "title": "開発用の架空データ（実在の統計ではありません）",
    "provider": "tokyo-data-map 開発用",
    "url": None,
    "license": "CC0 1.0",
    "license_url": "https://creativecommons.org/publicdomain/zero/1.0/deed.ja",
    "attribution": "架空データ（実在の地域・統計ではありません）",
    "modification_note": None,
    "redistributable": True,
}

# (団体コード5桁, 市区町村名, 町名の接頭辞, 西端経度, 南端緯度)
MUNICIPALITIES = [
    ("13199", "サンプル区", "見本町", 139.70, 35.66),
    ("13299", "ためし市", "試験町", 139.64, 35.66),
    ("13499", "かりの村", "仮置", 139.36, 34.70),
]
# 東京都以外の都道府県の例（国勢調査の統計GISの表と境界だけ作る）。政令指定都市の区の例として市の名前を持つ
OTHER_MUNICIPALITIES = [
    ("14199", "みほん市中区", "標本町", 139.60, 35.45),
]
PREF_NAMES = {"13": "東京都", "14": "神奈川県"}
GRID = 4
CELL = 0.015  # 度

# 列名は 2020年国勢調査 小地域集計の実ファイル（T001081・T001082）に合わせる
POP_CODES = ["T001081001", "T001081002", "T001081003", "T001081004"]
POP_LABELS = ["人口総数", "男", "女", "世帯総数"]
AGE_CODES = ["T001082001", "T001082017", "T001082018", "T001082019"]
AGE_LABELS = ["総数、年齢「不詳」含む", "総数１５歳未満", "総数１５～６４歳", "総数６５歳以上"]
HEAD_CODES = ["KEY_CODE", "HYOSYO", "CITYNAME", "NAME", "HTKSYORI", "HTKSAKI", "GASSAN"]

KANJI = "一二三四五六七八九"


def _cells(city5: str, town: str, west: float, south: float):
    """(KEY_CODE, 名称, 正方形の座標) を返す。最後の行は丁目のない町（末尾00）にする。"""
    for i in range(GRID):
        for j in range(GRID):
            x0, y0 = west + j * CELL, south + i * CELL
            ring = [(x0, y0), (x0, y0 + CELL), (x0 + CELL, y0 + CELL), (x0 + CELL, y0), (x0, y0)]
            if i == GRID - 1:
                s_area, name = f"{(GRID) * 10:04d}{j:02d}", f"{town}{KANJI[i]}番{j + 1}"
                if j == 0:
                    s_area, name = f"{900:04d}00", f"{town}字はずれ"
            else:
                s_area, name = f"{(i + 1) * 10:04d}{j + 1:02d}", f"{town}{i + 1}丁目" if j == 0 \
                    else f"{town}{KANJI[i]}丁目{KANJI[j]}"
            yield city5 + s_area, name, ring


# 暮らし方の表（統計GISの小地域集計。2020年の実ファイルの列名。2015年は先頭に全角空白がある）
HOUSEHOLD_TABLES = {
    "household_size": ["一般世帯数（世帯人員６人以上含む）", "世帯人員１人", "世帯人員２人", "世帯人員３人",
                       "世帯人員４人", "世帯人員５人", "一般世帯人員", "１世帯当たり人員"],
    "family_type": ["一般世帯総数", "親族のみの世帯", "核家族世帯", "うち夫婦のみの世帯",
                    "うち夫婦と子供から成る世帯", "核家族以外の世帯", "６歳未満世帯員のいる一般世帯総数",
                    "１８歳未満世帯員のいる一般世帯総数", "６５歳以上世帯員のいる一般世帯総数"],
    "tenure": ["住宅に住む一般世帯", "持ち家", "民営借家"],
    "building_type": ["主世帯数", "一戸建", "長屋建", "共同住宅", "共同住宅１・２階建", "共同住宅３～５階建",
                      "共同住宅６～１０階建", "共同住宅１１階建以上", "その他"],
    # 働き方（2015・2020年）。産業の内訳は省き、総数と従業上の地位だけにする
    "industry_status": ["総数", "Ａ農業、林業", "雇用者（役員を含む）", "自営業主（家庭内職者を含む）", "家族従業者"],
    "occupation": ["総数", "Ａ管理的職業従事者", "Ｂ専門的・技術的職業従事者", "Ｃ事務従事者", "Ｄ販売従事者",
                   "Ｅサービス職業従事者", "Ｆ保安職業従事者", "Ｇ農林漁業従事者", "Ｈ生産工程従事者",
                   "Ｉ輸送・機械運転従事者", "Ｊ建設・採掘従事者", "Ｋ運搬・清掃・包装等従事者", "Ｌ分類不能の職業"],
}


def _household_keys(year: str, ids: dict[str, str]) -> dict[str, tuple[str, str]]:
    return {t: (f"census{year}_small_area_{t}", f"tbl{sid}C13.txt") for t, sid in ids.items()}


_HOUSEHOLD_IDS = {"household_size": 0, "family_type": 1, "tenure": 2, "building_type": 3}


# 2010年・2015年の架空データ: 値は2020年から少し変え、境界は1地域だけ面積を変える（比較不可の例）。
# また1地域は過去の時点には存在しない（2020年に新設された例）。
YEARS = {
    "2020": {"boundary": "census2020_small_area_boundary",
             "population": ("census2020_small_area_population", "tblT001081C13.txt"),
             "age": ("census2020_small_area_age", "tblT001082C13.txt"),
             "education": ("census2020_small_area_education", "h13_13.csv"),
             "households": _household_keys("2020", {**{t: f"T00108{3 + i}" for t, i in _HOUSEHOLD_IDS.items()},
                                                            "industry_status": "T001103", "occupation": "T001104"})},
    "2015": {"boundary": "census2015_small_area_boundary",
             "population": ("census2015_small_area_population", "tblT000848C13.txt"),
             "age": ("census2015_small_area_age", "tblT000849C13.txt"),
             "households": _household_keys("2015", {**{t: f"T00085{i}" for t, i in _HOUSEHOLD_IDS.items()},
                                                            "industry_status": "T000865", "occupation": "T000866"})},
    "2010": {"boundary": "census2010_small_area_boundary",
             "population": ("census2010_small_area_population", "tblT000572C13.txt"),
             "age": ("census2010_small_area_age", "tblT000573C13.txt"),
             "households": _household_keys("2010", {t: f"T00057{4 + i}" for t, i in _HOUSEHOLD_IDS.items()})},
}
CHANGED_CELL = 2   # 過去の時点は面積が異なる（比較不可）
NEW_CELL = 3       # 過去の時点には存在しない


def write(directory: Path, seed: int = 42) -> dict[str, Path]:
    rnd = random.Random(seed)
    base = _base_values(rnd)
    out = {}
    for year, keys in YEARS.items():
        factor_rnd = random.Random(f"{seed}-{year}")
        out.update(_write_year(directory, year, keys, base, factor_rnd, "13", MUNICIPALITIES))
        other = _write_year(directory, year, {k: v for k, v in keys.items() if k != "education"}, base,
                            random.Random(f"{seed}-{year}-14"), "14", OTHER_MUNICIPALITIES)
        out.update({f"{k}_14": v for k, v in other.items()})
    out["daytime"] = _write_daytime(directory, base, random.Random(f"{seed}-daytime"))
    out.update(_write_census2025(directory, base))
    out.update(_write_census_foreign(directory))
    out["daytime_2015"] = _write_daytime_past(directory, 2015, base, random.Random(f"{seed}-daytime-2015"))
    out["daytime_2010"] = _write_daytime_past(directory, 2010, base, random.Random(f"{seed}-daytime-2010"))
    out["foreign_census"] = _write_foreign_census(directory, base, random.Random(f"{seed}-foreign"))
    out.update(_write_mobility(directory, base, random.Random(f"{seed}-mobility")))
    for year in FOREIGN_YEARS:
        out[f"foreign_{year}"] = _write_foreign(directory, year, base, random.Random(f"{seed}-foreign-{year}"))
    for year in JUKI_FOREIGN_YEARS:
        out[f"juki_foreign_{year}"] = _write_juki_foreign(directory, year, random.Random(f"{seed}-juki-{year}"))
        out[f"juki_total_{year}"] = _write_juki_foreign(directory, year, random.Random(f"{seed}-juki-{year}"),
                                                        total=True)
    for year in ZAIRYU_YEARS:
        out[f"zairyu_{year}"] = _write_zairyu(directory, year, random.Random(f"{seed}-zairyu-{year}"))
    for year in TRAFFIC_YEARS:
        out[f"traffic_{year}"] = _write_traffic(directory, year, random.Random(f"{seed}-traffic-{year}"))
    for year in CRIME_YEARS:
        out[f"crime_{year}"] = _write_crime(directory, year, random.Random(f"{seed}-crime-{year}"))
    out["stations"] = _write_stations(directory, random.Random(f"{seed}-stations"))
    out.update(_write_schools(directory, random.Random(f"{seed}-schools")))
    out["land_price"] = _write_land_prices(directory, random.Random(f"{seed}-land"))
    out.update(_write_mlit_facilities(directory))
    out["street_trees"] = _write_street_trees(directory, random.Random(f"{seed}-trees"))
    for year, years in CHILDCARE_FILES.items():
        out[f"childcare_{year}"] = _write_childcare(directory, year, years, random.Random(f"{seed}-childcare-{year}"))
    for year in TAX_YEARS:
        out[f"tax_{year}"] = _write_tax(directory, year, random.Random(f"{seed}-tax-{year}"))
    out.update(_write_elections(directory, random.Random(f"{seed}-elections")))
    out["nurseries"] = _write_nurseries(directory)
    out["furusato"] = _write_furusato(directory, random.Random(f"{seed}-furusato"))
    out["jhs_progress"] = _write_jhs_progress(directory)
    out["inbound"] = _write_inbound(directory)
    out.update(_write_gakuryoku(directory))
    out.update(_write_school_basic(directory))
    out.update(_write_housing(directory))
    out.update(_write_vital(directory))
    out["census_history"] = _write_census_history(directory)
    out.update(_write_economic_census(directory))
    out["land_survey"] = _write_land_survey(directory, random.Random(f"{seed}-land-survey"))
    out.update(_write_npa_crime_stats(directory))
    out.update(_write_police_crime_opendata(directory))
    return out


# 警察庁「犯罪統計」の都道府県別（第3表 刑法犯・第4表 窃盗犯・第6表 重要犯罪）。北海道は「計」の行と方面ごとの行、
# 東京都は2列目が空の行、ほかは2列目が都道府県名（1列目は管区）
def npa_crime_values(year: int, pref: str) -> tuple[int, int, int]:
    total = 1000 + int(pref) * 37 + (year - 2020) * 11
    return total, total * 7 // 10, 10 + int(pref)


def _write_npa_crime_stats(directory: Path) -> dict[str, Path]:
    from .regions import PREFECTURES
    out = {}
    for year in range(2020, 2026):
        lines = ["第１表,,,,刑法犯　罪種別　認知・検挙件数,,", ",罪種,\"2025年\n1～12月\",\"2024年\n1～12月\",増減",
                 "刑法犯総数,,99,98,1"]
        for no, k in ((3, 0), (4, 1), (6, 2)):
            vals = {p: npa_crime_values(year, p)[k] for p in PREFECTURES}
            lines += [f"第{str(no).translate(FULLWIDTH)}表,,,,都道府県別　認知件数", f"全国,,{sum(vals.values())},0,0"]
            for code, name in PREFECTURES.items():
                if code == "01":
                    lines += [f"北海道,計,{vals[code]},0,0", f"北海道,札幌方面,{vals[code] - 5},0,0", "北海道,函館方面,5,0,0"]
                elif code == "13":
                    lines.append(f"東京都,,{vals[code]},0,0")
                else:
                    lines.append(f"関東,{name},{vals[code]},0,0")
            lines.append("関東,計,1,0,0")
        path = directory / f"npa_crime_stats_{year}" / f"npa_crime_stats_{year}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("\r\n".join(lines) + "\r\n").encode("cp932"))
        out[f"npa_crime_stats_{year}"] = path
    return out


# 都道府県警察の犯罪オープンデータ（窃盗7手口、1件1行）。ファイル名は sources.toml の download_files にそろえる。
# 1ファイルごとに: サンプル区は「見本町１丁目」2件・「見本町一丁目二」1件・町丁目が空1件、ためし市は
# 「試験町字はずれ１丁目」（地図では丁目に分かれていない町）1件と「試験町1丁目」1件と「遠い町」1件、かりの村は0件
POLICE_OD_HEAD = ["罪名", "手口", "管轄警察署（発生地）", "管轄交番・駐在所（発生地）", "市区町村コード（発生地）",
                  "都道府県（発生地）", "市区町村（発生地）", "町丁目（発生地）", "発生年月日（始期）"]
POLICE_OD_ROWS = {   # 都道府県 → (市区町村コード6桁, 市区町村名, 町丁目)
    "13": [("131997", "サンプル区", "見本町１丁目"), ("131997", "サンプル区", "見本町１丁目"),
           ("131997", "サンプル区", "見本町一丁目二"), ("131997", "サンプル区", ""),
           ("132993", "ためし市", "試験町字はずれ１丁目"), ("132993", "ためし市", "試験町1丁目"),
           ("132993", "ためし市", "遠い町")],   # 地図にない町名（位置参照情報の代表点で小地域に入れる）
    "14": [("141992", "みほん市中区", "標本町1丁目")],
}


def _write_police_crime_opendata(directory: Path) -> dict[str, Path]:
    import tomllib
    sources = tomllib.loads((Path(__file__).resolve().parents[1] / "config" / "sources.toml").read_text(encoding="utf-8"))
    out = {}
    for key, cfg in sources.items():
        if cfg.get("kind") != "police_crime_opendata" or cfg["prefectures"][0] not in POLICE_OD_ROWS:
            continue
        pref = cfg["prefectures"][0]
        for name in cfg["download_files"]:
            year, tech = name.split(".")[0].split("_")
            path = directory / key / pref / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="cp932", newline="") as f:
                wr = csv.writer(f)
                wr.writerow(POLICE_OD_HEAD)
                for code, muni, town in POLICE_OD_ROWS[pref]:
                    wr.writerow(["窃盗", tech, "見本警察署", "見本交番", code, PREF_NAMES[pref], muni, town, f"{year}0105"])
            out[f"{key}_{name}"] = path
    out.update(_write_weather(directory))
    return out


# 経済センサス（町丁・大字別の民営事業所数・従業者数）。名前で地図の小地域に対応付ける。
# 「見本町1丁目」は全角数字の表記ゆれ、「見本町旧名」は地図にない名前、「その他」は町丁・大字が分からない事業所
ECONOMIC_CENSUS_ROWS = [   # (KEY_CODE の市区町村, 市区町村名, 町丁・大字名, 事業所数, 従業者数)
    ("13199", "サンプル区", "見本町１丁目", "120", "3400"),
    ("13199", "サンプル区", "見本町一丁目二", "15", "-"),
    ("13199", "サンプル区", "見本町旧名", "7", "40"),
    ("13199", "サンプル区", "その他", "3", "12"),
    ("13299", "ためし市", "試験町1丁目", "30", "210"),
    ("13299", "ためし市", "試験町字はずれ１丁目", "2", "9"),   # 地図では丁目に分かれていない町 → 町にまとめる
    ("13299", "ためし市", "試験町字はずれ２丁目", "1", "4"),
    ("14199", "みほん市中区", "標本町1丁目", "44", "500"),
]


def _write_economic_census(directory: Path) -> dict[str, Path]:
    out = {}
    head = "KEY_CODE,CITY_NAME,AZA_CODE,AZA_NAME,T001167001,T001167002,T001167019,T001167020"
    labels = ",,,,AR_全産業（S_公務を除く）,AB_農林漁業,AR_全産業（S_公務を除く）,AB_農林漁業"
    for pref in ("13", "14"):
        lines = [head, labels]
        for i, (city5, city, town, n, emp) in enumerate(r for r in ECONOMIC_CENSUS_ROWS if r[0][:2] == pref):
            aza = f"{i + 1:04d}00000{i + 1:03d}"
            lines.append(f"{city5}{aza},{city},{aza},{town},{n},-,{emp},-")
        path = directory / "economic_census2021_small_area" / pref / f"tblT001167C{pref}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("\r\n".join(lines) + "\r\n").encode("cp932"))
        out[f"economic_census_{pref}"] = path
    return out


# 都道府県地価調査（L02）。1983年からの価格の推移の欄（L02_055〜）は、基準地でなかった年が 0
LAND_SURVEY_POINTS = [   # (市区町村, 市区町村名, 用途, 連番, 経度, 緯度, 基準地になった年)
    ("13199", "サンプル", "000", "001", 139.712, 35.668, 1983),
    ("13299", "ためし", "005", "001", 139.648, 35.663, 2010),
]


def _write_land_survey(directory: Path, rnd: random.Random) -> Path:
    d = directory / "mlit_l02_2025"
    features: dict[str, list] = {}
    for city5, city_name, use, seq, lon, lat, since in LAND_SURVEY_POINTS:
        level = {"000": 380_000, "005": 1_500_000}[use]
        prices = [0 if y < since else int(level * (1 + (y - 2000) * 0.01) * rnd.uniform(0.95, 1.05))
                  for y in range(1983, 2026)]
        props = {"L02_001": use, "L02_002": seq, "L02_005": 2025, "L02_006": prices[-1],
                 "L02_007": round((prices[-1] / prices[-2] - 1) * 100, 1), "L02_020": city5, "L02_021": city_name,
                 "L02_022": f"東京都{city_name}見本町２丁目{seq}番", "L02_024": 150, "L02_025": "住宅",
                 "L02_044": "見本", "L02_045": 800, "L02_046": "1住居"}
        props.update({f"L02_{55 + i:03d}": v for i, v in enumerate(prices)})
        features.setdefault(city5[:2], []).append(_point(props, lon, lat))
    for pref, feats in features.items():
        _write_geojson(d / pref / f"L02-25_{pref}.geojson", feats)
    return d


# 国勢調査 時系列 第1表（都道府県の人口、1920〜2020年）。沖縄県の1945年のように調査のない年は「-」。
# 見本では神奈川県の1945年を「-」にする
def census_history_values() -> dict[str, dict[int, float | None]]:
    out = {}
    for pref, base in (("13", 3_699_428), ("14", 1_323_390)):
        out[pref] = {y: float(round(base * (1 + (y - 1920) * 0.03))) for y in range(1920, 2021, 5)}
    out["14"][1945] = None
    return out


def _write_census_history(directory: Path) -> Path:
    from .xlsx import write_sheets
    vals = census_history_values()
    years = list(range(1920, 2021, 5))
    head = ["地域"] + [x for y in years for x in (f"{y}年", "和暦", "")]
    rows: list[list] = [["国勢調査 時系列データ"], ["第１表"], [], ["1) 昭和20年において…"], ["（人）"], head,
                        [None] + ["総数", "男", "女"] * len(years),
                        ["00000_全国"] + [1000.0] * 3 * len(years),
                        ["00000_全国（人口集中地区）"] + ["-"] * 3 * len(years)]
    for pref, name in (("13", "東京都"), ("14", "神奈川県")):
        cells = []
        for y in years:
            v = vals[pref][y]
            cells += ["-", "-", "-"] if v is None else [v, round(v / 2), v - round(v / 2)]
        rows.append([f"{pref}000_{name}"] + cells)
    d = directory / "census_history_prefecture"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "census_history_prefecture.xlsx"
    write_sheets(path, {"人口": rows, "人口性比": [["見本"]]})
    return path


# 住宅・土地統計調査（市区町村別）。かりの村は人口1万5千人未満の町村として表に載せない。
# 収入階級は令和5年が10区分（100〜150・150〜200万円に分かれる）、平成30年が9区分
HOUSING_INCOME_CLASSES = {
    2023: ["01_100万円未満", "02_100～150万円未満", "03_150～200万円未満", "05_200～300万円未満",
           "06_300～400万円未満", "07_400～500万円未満", "08_500～700万円未満", "09_700～1000万円未満",
           "10_1000～1500万円未満", "11_1500万円以上"],
    2018: ["01_100万円未満", "02_100～200万円未満", "04_200～300万円未満", "05_300～400万円未満",
           "06_400～500万円未満", "07_500～700万円未満", "08_700～1000万円未満", "09_1000～1500万円未満",
           "10_1500万円以上"],
}
HOUSING_AREAS = [("13000", "東京都"), ("13199", "サンプル区"), ("13299", "ためし市"),
                 ("14000", "神奈川県"), ("14190", "みほん市"), ("14199", "みほん市\u3000中区")]


def housing_income_values(year: int) -> dict[str, list[float]]:
    """地域コード → 収入階級ごとの主世帯数（10世帯単位）。ためし市の2023年の1500万円以上は「-」（該当なし）。"""
    rnd = random.Random(f"housing-income-{year}")
    out = {c: [float(rnd.randint(10, 300) * 10) for _ in HOUSING_INCOME_CLASSES[year]]
           for c, _ in HOUSING_AREAS if not c.endswith("000")}
    if year == 2023:
        out["13299"][-1] = None   # 「-」
    for pref in ("13", "14"):
        members = [v for c, v in out.items() if c[:2] == pref and c != "14190"]
        out[f"{pref}000"] = [sum(v[i] or 0 for v in members) + 1000 for i in range(len(HOUSING_INCOME_CLASSES[year]))]
    return out


def housing_stock_values(year: int) -> dict[str, tuple[float, float]]:
    """地域コード → (住宅総数, 空き家数)。"""
    rnd = random.Random(f"housing-stock-{year}")
    out = {c: (float(rnd.randint(3000, 9000) * 10), float(rnd.randint(200, 1500) * 10))
           for c, _ in HOUSING_AREAS if not c.endswith("000")}
    for pref in ("13", "14"):
        members = [v for c, v in out.items() if c[:2] == pref and c != "14190"]
        out[f"{pref}000"] = (sum(v[0] for v in members) + 5000, sum(v[1] for v in members) + 700)
    return out


def _write_housing(directory: Path) -> dict[str, Path]:
    from .xlsx import write_sheet
    out = {}
    for year in (2023, 2018):
        classes = HOUSING_INCOME_CLASSES[year]
        vals = housing_income_values(year)
        rows: list[list] = [[f"住宅・土地統計調査（{year}年）"], ["世帯の年間収入階級…別主世帯数"], [], []]
        for code, name in [("00000", "全国")] + HOUSING_AREAS:
            v = vals.get(code, [1000.0] * len(classes))
            level = "a" if code.endswith("000") else "0"
            for tenure in ("0_総数", "1_持ち家"):
                for label, x in [("00_総数", sum(c or 0 for c in v) + 30)] + list(zip(classes, v)):
                    cell = "-" if x is None else (x if tenure == "0_総数" else round(x / 2))
                    if year == 2023:
                        rows.append([level, f"{code}_{name}", tenure, label, cell, 2.1, 4.0, 30.0])
                    else:   # 平成30年: 行番号などの列と「世帯の種類」の列がある
                        for kind in ("1_主世帯", "2_同居世帯・住宅以外の建物に居住する世帯"):
                            rows.append([float(len(rows)), "D", None, None, level, f"{code}_{name}", 1.0, kind,
                                         1.0, tenure, 1.0, label, cell if kind == "1_主世帯" else 10.0,
                                         2.1, 4.0, 30.0])
        d = directory / f"housing_income_{year}"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"housing_income_{year}.xlsx"
        write_sheet(path, rows, "e043_4" if year == 2023 else "e044_4")
        out[f"housing_income_{year}"] = path

        stock = housing_stock_values(year)
        labels = ["0_総数", "1_居住世帯あり", "2_居住世帯なし", "22_空き家", "23_建築中"]
        pad = [] if year == 2023 else [None, "D", None, None]
        rows = [[f"住宅・土地統計調査（{year}年）"], ["第１－２表"], [], [],
                pad[:4] + [None, "項目名"] + labels if year == 2023 else [None] * 6 + labels]
        for code, name in [("00000", "全国")] + HOUSING_AREAS:
            total, vacant = stock.get(code, (100000.0, 9000.0))
            level = "a" if code.endswith("000") else "0"
            rows.append(pad + [level, f"{code}_{name}", total, total - vacant - 100, vacant + 100, vacant, "-"])
        d = directory / f"housing_stock_{year}"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"housing_stock_{year}.xlsx"
        write_sheet(path, rows, "e001_2")
        out[f"housing_stock_{year}"] = path
    return out


# 合計特殊出生率（ベイズ推定値）と市区町村別生命表。かりの村は出生率の表で「-」（値なし）
TFR_VALUES = {"13": 1.11, "13199": 0.98, "13299": 1.25, "13499": None, "14": 1.20, "14199": 1.31}
LIFE_VALUES = {"13000": (81.8, 87.9), "13199": (82.4, 88.3), "13299": (81.6, 87.7), "13499": (80.9, 87.2),
               "14000": (82.0, 87.9), "14199": (82.3, 88.0)}


def _write_vital(directory: Path) -> dict[str, Path]:
    from .xlsx import write_sheet, write_sheets
    names = {c: n for c, n, *_ in MUNICIPALITIES + OTHER_MUNICIPALITIES} | {"13": "東京都", "14": "神奈川県"}
    rows: list[list] = [["第２表"], [None, "合計特殊出生率（ベイズ推定値）"], ["全国\u3000\u3000", 1.33, 2.0]]
    for code in ("13", "1327", "13199", "13299", "13499", "14", "14100", "14199"):
        name = names.get(code, "見本保健所" if len(code) == 4 else "みほん市")
        v = TFR_VALUES.get(code, 1.5)
        rows.append([f"{code}{name}\u3000\u3000 ", "-" if v is None else v, 3.0, 20.0])
    d = directory / "mhlw_tfr_2018_2022"
    d.mkdir(parents=True, exist_ok=True)
    tfr = d / "tfr_2018_2022.xlsx"
    write_sheet(tfr, rows, "第２表")

    sheet: list[list] = []
    for code, (male, female) in [("00000", (81.5, 87.6))] + list(LIFE_VALUES.items()):
        sheet += [[f"表{code}", names.get(code, names.get(code[:2], "全国"))],
                  ["年齢(x)", "死亡率", "生存数", "死亡数", "定常人口", None, "平均余命"],
                  [None, "nqx", "lx", "ndx", "nLx", "Tx", "ex"]]
        for sex, ex in (("男", male), ("女", female)):
            sheet += [[sex], [0.0, 0.002, 100000.0, 200.0, 99800.0, ex * 100000, ex],
                      [" 1～ 4", 0.0006, 99800.0, 60.0, 399000.0, (ex - 1) * 99800, ex - 0.8]]
    d = directory / "mhlw_life_table_2020"
    d.mkdir(parents=True, exist_ok=True)
    life = d / "life_table_2020.xlsx"
    write_sheets(life, {"目次": [["【目次】"]], "生命表1": sheet})
    return {"mhlw_tfr_2018_2022": tfr, "mhlw_life_table_2020": life}


# 公立小学校卒業者の進路（都教委 進路状況調査 小学校 第1表の形式）。1区分3列（計・男・女）
JHS_PROGRESS = {   # 地区名 → (卒業者, 公立, 国立, 私立, 都外)
    "サンプル区": (200, 120, 4, 70, 3),
    "ためし市": (300, 270, 0, 25, 2),
    "かりの村": (5, 5, 0, 0, 0),          # 卒業者が10人未満
}


def _write_jhs_progress(directory: Path) -> Path:
    from .xlsx import write_sheet
    d = directory / "tokyo_jhs_progress_2025"
    d.mkdir(parents=True, exist_ok=True)

    def cols(*vals):   # 計・男・女の3列（男女は見本なので計を半分に分けるだけ）
        return [x for v in vals for x in (v, v // 2, v - v // 2)]
    head3 = ["地区名", "調査対象校数", None, "卒業者", None, None, "都内中学校等への進学者"] + [None] * 17 \
        + ["都外中学校等への進学者", None, None, "その他", None, None]
    head4 = [None, None, "卒業者", None, None, None, "計", None, None, "公立", None, None,
             None, None, None, None, None, None, "国立", None, None, "私立", None, None]
    head5 = [None, None, "を出し", None, None, None, None, None, None, None, None, None, "（再掲）都立"]
    head6 = [None, None, "た学校"] + ["計", "男", "女"] * 9
    rows = [["小学校"], ["第１表　状況別卒業者数"], [], head3, head4, head5, head6,
            ["令和元年度", 1.0, 1.0] + [float(x) for x in cols(500, 395, 395, 4, 95, 5, 0)]]
    rows.append(["区　　　部", 1.0, 1.0] + [float(x) for x in cols(200, 197, 120, 0, 4, 70, 3)])
    for name, (g, pub, nat, pri, out) in JHS_PROGRESS.items():
        rows.append([name, 1.0, 1.0] + [float(x) for x in cols(g, pub + nat + pri, pub, 0, 0, nat, pri, out, g - pub - nat - pri - out)])
    rows.append(["（再掲）都立", 1.0, 1.0] + [0.0] * 27)
    path = d / "sotsugo01_2025.xlsx"
    write_sheet(path, rows, "第1表")
    return path


# ふるさと納税の受入額（総務省の現況調査「各団体一覧」の形式）。見本は3年度だけ
FURUSATO_YEARS = ("令和５年度", "令和６年度", "令和７年度")


def _write_furusato(directory: Path, rnd: random.Random) -> Path:
    from .xlsx import write_sheet
    d = directory / "soumu_furusato_2026"
    d.mkdir(parents=True, exist_ok=True)
    rows = [[None] * (2 + 2 * len(FURUSATO_YEARS)) + ["（単位：千円、件）"],
            ["団体名", None] + [c for y in FURUSATO_YEARS for c in (y, None)],
            [],
            [None, None] + ["金額", "件数"] * len(FURUSATO_YEARS),
            ["北海道", None, 4660.0, 54.0, 5000.0, 60.0, 5200.0, 61.0],
            ["北海道", "札幌市", 397800.5, 385.0, 400000.0, 400.0, 410000.0, 420.0],
            ["東京都", None, 1200.0, 10.0, 1500.0, 12.0, 1800.0, 15.0],
            ["神奈川県", None, 300.0, 3.0, 350.0, 4.0, 400.0, 5.0],
            ["神奈川県", "みほん市", 20000.0, 100.0, 21000.0, 110.0, 22000.0, 120.0]]   # 政令指定都市は市全体の行だけ
    for _, name, *_ in MUNICIPALITIES:
        vals = []
        for _ in FURUSATO_YEARS:
            vals += [round(rnd.uniform(100, 90000), 3), float(rnd.randint(5, 900))]
        if name == "かりの村":
            vals[0:2] = [None, None]   # 空欄の年度は値なし
        rows.append(["東京都", name] + vals)
    rows.append(["全国合計", None, 1.0, 1.0])
    path = d / "001084990.xlsx"
    write_sheet(path, rows, "各団体一覧")
    return path


# 外国人延べ宿泊者数（観光庁「宿泊旅行統計調査」年の確定値 第2表(年計) の形式）。値は都道府県コードから作る
def inbound_values(pref: str) -> tuple[float, float]:
    """(延べ宿泊者数, 外国人延べ宿泊者数)（人泊）。"""
    n = int(pref)
    return 1_000_000.0 * (n + 10), 100_000.0 * n


def _write_inbound(directory: Path) -> Path:
    from .regions import PREFECTURES
    from .xlsx import write_sheet
    d = directory / "mlit_inbound_2025"
    d.mkdir(parents=True, exist_ok=True)
    head = ["施設所在地（47区分\n及び運輸局等）", "延べ\n宿泊者数\n1)", "従業者数（4区分）、宿泊目的割合（2区分）"] \
        + [None] * 13 + ["うち\n外国人延べ\n宿泊者数\n1)", "宿泊目的割合（2区分）", None]
    rows = [["第２表　年、月（12区分）、施設所在地(47区分及び運輸局等)…別延べ宿泊者数"], ["　　並びに…外国人延べ宿泊者数"],
            [], head, [None, None, None, None, "0～9人"], [None, None, "観光目的の\n宿泊者が\n50％以上"],
            ["令和7年 1～12月  計", 1.0] + [0.0] * 14 + [1.0, 0.0, 0.0]]
    for code, name in PREFECTURES.items():
        total, foreign = inbound_values(code)
        label = name if code == "14" else f"{code}{name}"   # 2015・2016年の版は都道府県名だけ
        rows.append([f"\u3000{label}", total] + [0.0] * 14 + [foreign, 0.0, 0.0])
    rows.append(["\u3000北海道運輸局", 1.0] + [0.0] * 14 + [1.0, 0.0, 0.0])
    path = d / "shukuhaku_2025.xlsx"
    write_sheet(path, rows, "第2表(年計)")
    return path


# 学力テスト（国立教育政策研究所 都道府県別「調査結果概況」の形式）。都道府県ごとのフォルダに置く
GAKURYOKU = {   # (都道府県, 校種) → {教科: (児童生徒数, 平均正答数, 問題数, 平均正答率)}
    ("13", "p"): {"国語": (93881.0, 9.8, 14.0, 70.0), "算数": (93933.0, 10.2, 16.0, 64.0)},
    ("14", "p"): {"国語": (60000.0, 9.3, 14.0, 66.0), "算数": (60000.0, 9.0, 16.0, 56.0)},
    ("13", "m"): {"国語": (70618.0, 8.0, 14.0, 57.0), "数学": (70646.0, 8.0, 15.0, 53.0)},
    ("14", "m"): {"国語": (50000.0, 7.5, 14.0, 54.0), "数学": (50000.0, 7.0, 15.0, 47.0)},
}


def _write_gakuryoku(directory: Path) -> dict[str, Path]:
    from .xlsx import write_sheets
    out = {}
    for (pref, school), subjects in GAKURYOKU.items():
        name = PREF_NAMES[pref]
        key, suffix = ("nier_gakuryoku_2025_p", "p_25r") if school == "p" else ("nier_gakuryoku_2025_m", "m_25rs")
        d = directory / key / pref
        d.mkdir(parents=True, exist_ok=True)
        sheets = {}
        for subject, (n, avg, questions, rate) in subjects.items():
            sheets[subject] = [["令和７年度全国学力・学習状況調査", "小学校調査"], [f"調査結果概況　［{subject}］"],
                               [f"{name}－児童（公立）"], [], [], [],
                               [None, None, "児童数", "平均正答数", None, None, "平均正答率\n(％)", "中央値", "標準偏差"],
                               [None, f"{name}（公立）", n, avg, "/", questions, rate, 10.0, 3.0],   # 1列目は空
                               [None, "全国（公立）", 936137.0, 9.4, "/", questions, 66.8, 10.0, 3.0]]
        # 中学校の理科は IRT スコアで平均正答率がない（読み飛ばす）
        sheets["理科 " if school == "m" else "理科"] = [[f"{name}（公立）", 68954.0, 2.9, "/", 6.0, 1.4]]
        path = d / f"{pref}{suffix}.xlsx"
        write_sheets(path, sheets)
        out[f"gakuryoku_{pref}{school}"] = path
    return out


# 中学校の生徒数（学校基本調査 市町村別学年別生徒数の形式）。type → {(都道府県, 区市町村コード3桁): 生徒数}
SCHOOL_BASIC = {
    "total": {("13", "199"): 1000.0, ("13", "299"): 2000.0, ("13", "499"): 0.0, ("14", "199"): 800.0},
    "national": {("13", "199"): 100.0, ("13", "299"): 0.0, ("13", "499"): 0.0, ("14", "199"): 0.0},
    "public": {("13", "199"): 500.0, ("13", "299"): 1900.0, ("13", "499"): 0.0, ("14", "199"): 700.0},
    "private": {("13", "199"): 400.0, ("13", "299"): 100.0, ("13", "499"): 0.0, ("14", "199"): 100.0},
}


def _write_school_basic(directory: Path) -> dict[str, Path]:
    from .xlsx import write_sheets
    d = directory / "estat_school_basic_2025"
    d.mkdir(parents=True, exist_ok=True)
    names = {"13": {c[2:]: n for c, n, *_ in MUNICIPALITIES}, "14": {c[2:]: n for c, n, *_ in OTHER_MUNICIPALITIES}}
    out = {}
    for t, counts in SCHOOL_BASIC.items():
        sheets = {"全国": [["中学校　市町村別学年別生徒数　計"], ["全国"], [], [], ["計", sum(counts.values())]]}
        for pref, pname in PREF_NAMES.items():
            rows = [["中学校　市町村別学年別生徒数　計"], [pname], [None, None, "計", "計", "計", "1学年"],
                    [None, None, "計", "男", "女", "計"],
                    ["計", "計", sum(v for (p, _), v in counts.items() if p == pref), 0.0, 0.0]]
            for (p, code), v in counts.items():
                if p == pref:
                    rows.append([code, names[pref][code], v, v // 2, v - v // 2])
            rows.append(["999", f"{pname}外", 0.0, 0.0, 0.0])
            sheets[pname] = rows
        path = d / f"{t}.xlsx"
        write_sheets(path, sheets)
        out[f"school_basic_{t}"] = path
    return out


# 認可保育所（福祉局「社会福祉施設等一覧」のシート「認可保育所」の形式）。13列目は区市町村コードの下3桁
NURSERIES = [
    ("営利法人", "見本ほいくえん", "サンプル区見本町１－２－３", 87.0, 199.0),        # 街区
    ("社会福祉法人", "見本第二保育園", "サンプル区見本町一丁目99番地", 120.0, 199.0),  # 町丁目の代表点
    ("区市町村", "ためし保育園", "ためし市どこにもない町1-1", 60.0, 299.0),        # 位置なし
    ("区市町村", "かりの保育所", "仮島かりの村仮置10", 30.0, 499.0),              # 島名から書く住所
]


def _write_nurseries(directory: Path) -> Path:
    from .xlsx import write_sheet
    d = directory / "tokyo_nurseries_2025"
    d.mkdir(parents=True, exist_ok=True)
    rows = [["社会福祉施設等一覧（令和7年10月1日時点）"], [],
            ["設置", "施設名", "郵便番号", None, None, "所在地", "電話番号", None, None, None, None, "認可定員"]]
    for founder, name, address, cap, code in NURSERIES:
        rows.append([founder, name, "100", "-", "0000", address, "03", "-", "0000", "-", "0000", cap, code])
    path = d / "shisetsu_2025.xlsx"
    write_sheet(path, rows, "認可保育所")
    return path


# 都道の街路樹（建設局の CSV 形式、cp932）。区部の見本の区だけ（多摩のファイルはなし）
TREE_SPECIES = ["イチョウ", "ソメイヨシノ", "ケヤキ", "ハナミズキ", "モミジバスズカケノキ", "トウカエデ", "トキワマンサク"]


def _write_street_trees(directory: Path, rnd: random.Random) -> Path:
    d = directory / "tokyo_street_trees_ku"
    d.mkdir(parents=True, exist_ok=True)
    head = ["樹種", "区分", "樹高(m)", "枝張(m)", "幹周(cm）", "行政区", "種別", "整理番号", "路線名", "通称道路名", "経度", "緯度"]
    city5, city_name, town, west, south = MUNICIPALITIES[0]
    rows = []
    # 南北の1列（j = 1）に沿った都道だけ。ほかの列の町丁目は0本
    for n in range(300):
        i = rnd.randrange(GRID)
        lon = west + (1 + rnd.uniform(0.2, 0.8)) * CELL
        lat = south + (i + rnd.uniform(0.1, 0.9)) * CELL
        sp = TREE_SPECIES[0] if i == 0 else rnd.choice(TREE_SPECIES)   # 南端の町丁目はイチョウ並木
        rows.append([sp, "高木", 8, 3, 90, city_name, "特例都道", "318", "環状七号線", "環七通り", f"{lon:.6f}", f"{lat:.6f}"])
    rows.append(["イチョウ", "高木", 8, "", "", city_name, "特例都道", "318", "環状七号線", "", "", ""])   # 位置なし
    path = d / "tokyo_gairoju.csv"
    with path.open("w", encoding="cp932", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(head)
        wr.writerows(rows)
    return d


# 都内の保育サービスの状況 表4（都の Excel 形式）。1ファイルに当年・前年の2時点。
# 2026年の発表は時点が日付のセル、2023年の発表は「令和5年4月1日」のような文字列の例
CHILDCARE_FILES = {2026: (2026, 2025), 2023: (2023, 2022)}


def _write_childcare(directory: Path, year: int, years: tuple[int, int], rnd: random.Random) -> Path:
    import datetime as dt
    from .xlsx import write_sheet
    d = directory / f"tokyo_childcare_{year}"
    d.mkdir(parents=True, exist_ok=True)
    when = [(dt.date(y, 4, 1) - dt.date(1899, 12, 30)).days if year >= 2024 else f"令和{y - 2018}年4月1日"
            for y in years]
    group = ["就学前\n児童人口\n（a）", "保育サービス利用児童数\n（b）", "保育\nサービス\n利用率\n（b/a）", "待機\n児童数"]
    rows = [["表４　区市町村別の状況"], [],
            ["区市町村名", when[0], None, None, None, when[1], None, None, None, "増減"],
            [None, *group, *group, *group[:2], group[3]]]
    total = [0] * 8
    for city5, city_name, *_ in MUNICIPALITIES:
        vals = []
        for _ in years:
            kids = rnd.randint(300, 20000)
            users = round(kids * rnd.uniform(0.4, 0.7))
            vals += [kids, users, round(users / kids, 3), rnd.choice([0, 0, 3, 41])]
        total = [a + b for a, b in zip(total, vals)]
        rows.append([city_name, *vals, vals[0] - vals[4], vals[1] - vals[5], vals[3] - vals[7]])
    rows.append(["区部計", *total])   # 合計の行は使わない
    path = d / f"hoiku_{year}.xlsx"
    write_sheet(path, rows, "表４")
    return d


# 都選管の選挙結果（CSV、UTF-8 BOM つき）。開票区名は全角空白で字下げし、都計には★、区部計などには☆がつく。
# サンプル区は小選挙区で分かれる区の形（「…計」と「…4区」の行）にする。区市町村の投票率だけに使う
def _write_elections(directory: Path, rnd: random.Random) -> dict[str, Path]:
    import csv
    out = {}

    def write(key: str, name: str, rows: list[list]) -> None:
        d = directory / f"tokyo_election_{key}"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / name, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(rows)
        out[f"election_{key}"] = d

    def names(split: bool) -> list[str]:
        rows = ["\u3000★都計", "\u3000☆区部計"]
        for _, n, *_ in MUNICIPALITIES:
            if split and n == "サンプル区":
                rows += [f"\u3000\u3000{n}計", f"\u3000\u3000{n}4区", f"\u3000\u3000{n}26区"]
            else:
                rows.append(f"\u3000\u3000{n}")
        return rows

    for key, name, split in [("2024_tochiji_touhyou", "r6_tochiji_touhyo.csv", False),
                             ("2024_shugiin_touhyou", "r6_syuugiin_hirei_touhyou.csv", True)]:
        rows = [["令和6年 執行"], ["投票結果"], [], [" 20時00分 現在　確定"],
                ["", "開\u3000票\u3000区\u3000名", "選 挙 当 日 有 権 者 数"],
                ["", "", "男", "女", "計", "男", "女", "計", "男", "女", "計", "男", "女", "平均", "順位"]]
        for n in names(split):
            m, w = rnd.randint(2000, 90000), rnd.randint(2000, 90000)
            vm, vw = round(m * rnd.uniform(0.4, 0.7)), round(w * rnd.uniform(0.4, 0.7))
            rows.append(["", n, f"{m:,}", f"{w:,}", f"{m + w:,}", f"{vm} ", f"{vw} ", f"{vm + vw} ",
                         m - vm, w - vw, m + w - vm - vw, "", "", "", "-"])
        write(key, name, rows)
    out.update(_write_soumu_elections(directory, rnd))
    return out


# 総務省の国政選挙の結果調（全国、Excel）。形式は pipeline/tdm/ingest/soumu_election.py を参照。
# 令和6年衆院選: ブロックごとのファイルで都道府県ごとのシート。サンプル区は小選挙区で分かれた行（「…第４区」「…第２６区」）だけ
# 令和7年参院選: 都道府県ごとのファイル。政党ごとに3列。かりの村は空欄の行（総務省の表に実際にある形）
# 令和8年衆院選: 「党派名」の次の行に政党名。みほん市（政令指定都市）の市全体の行と区の行、サンプル区は区全体の行と「…第１」の行
ELECTION_PARTIES = {"2024-10-27": ["日本共産党", "立憲民主党", "公明党", "自由民主党", "みんなでつくる党"],
                    "2025-07-20": ["日本共産党", "参政党", "自由民主党", "日本誠真会"],
                    "2026-02-08": ["自由民主党", "中道改革連合", "チームみらい"]}


def election_votes(period: str, name: str) -> list[float]:
    """見本の得票数（政党の順）。小数は按分の票。"""
    seed = sum(ord(c) for c in name) + int(period[:4])
    return [round(100 + (seed * (k + 3)) % 9000 + (0.25 if k == 1 else 0), 3)
            for k in range(len(ELECTION_PARTIES[period]))]


def election_prefecture_votes(period: str, pref: str) -> list[float]:
    """都道府県別の表の得票数（市区町村の合計とは別の値。都道府県の値はこちらから作ることを確かめる）。"""
    return [round(50000 + int(pref) * 1000 + k * 3000, 3) for k in range(len(ELECTION_PARTIES[period]))]


def election_turnout(period: str, pref: str) -> tuple[int, int]:
    """都道府県の (投票者数, 有権者数)。"""
    electorate = 1_000_000 + int(pref) * 10_000 + int(period[:4])
    return round(electorate * (0.5 + int(pref) / 1000)), electorate


def _write_soumu_elections(directory: Path, rnd: random.Random) -> dict[str, Path]:
    from .xlsx import write_sheets
    out = {}
    tokyo = [n for _, n, *_ in MUNICIPALITIES]

    def save(key: str, name: str, sheets: dict) -> None:
        d = directory / f"soumu_election_{key}"
        d.mkdir(parents=True, exist_ok=True)
        write_sheets(d / name, sheets)
        out[f"soumu_election_{key}"] = d

    def fmt(v: float) -> str:   # 「6,170.858」「53,072       」の形
        return f"{v:,.3f}" if v != int(v) else f"{int(v):,}       "

    # 令和6年衆院選（第50回）
    period, parties = "2024-10-27", ELECTION_PARTIES["2024-10-27"]

    def sheet50(pref_name: str, munis: list[str]) -> list[list]:
        rows = [["令和６年１０月２７日執行"], ["衆議院議員総選挙（比例代表）\u3000名簿届出政党別市区町村別得票数"],
                [pref_name, "（ブロック）"], ["市区町村名＼政党名", *parties, "得票数計"]]
        total = [0.0] * len(parties)
        for n in munis:
            parts = [f"{n}第４区", f"{n}第２６区"] if n == "サンプル区" else [n]
            for part in parts:
                v = [x / len(parts) for x in election_votes(period, n)]
                rows.append([part, *v, sum(v)])
                total = [a + b for a, b in zip(total, v)]
        rows.append([f"{pref_name} 合計", *total, sum(total)])
        return rows
    save("2024_shugiin_hirei", "tokyo.xlsx", {"東京都": sheet50("東京都", tokyo)})
    save("2024_shugiin_hirei", "minamikanto.xlsx", {"神奈川県": sheet50("神奈川県", ["みほん市中区"]),
                                                     "リスト": [["No", "都道府県名"], [14, "神奈川県"]]})

    def pref_table(period: str, head: list[str]) -> list[list]:
        rows = [["（７）比例代表選挙区別都道府県別党派別得票数"], [], [], [*head, *ELECTION_PARTIES[period]], []]
        rows.append(["東京都", "東京都", *map(fmt, election_prefecture_votes(period, "13"))])
        rows.append(["南関東", "神奈川県", *map(fmt, election_prefecture_votes(period, "14"))])
        rows.append(["", "計", *map(fmt, election_prefecture_votes(period, "14"))])
        rows += [[*head, "合計"], []]   # 最後に全政党の合計の欄（政党の得票数ではない）
        rows += [[b, n, fmt(sum(election_prefecture_votes(period, c)))]
                 for b, n, c in [("東京都", "東京都", "13"), ("南関東", "神奈川県", "14")]]
        return rows

    def turnout_table(period: str) -> list[list]:
        rows = [["（２）都道府県別有権者数、投票者数（比例代表）"], ["選挙区", "都道府県"],
                ["", "", "", "選挙当日の有権者数", "", "", "投票者数"], [],
                ["", "", "男", "女", "計", "男", "女", "計", "男", "女", "計"]]
        for block, pref, name in [("東京都", "13", "東京都"), ("南関東", "14", "神奈川県")]:
            voters, electorate = election_turnout(period, pref)
            rows.append([block, name, electorate // 2, electorate - electorate // 2, electorate,
                         voters // 2, voters - voters // 2, voters, 0, 0, electorate - voters])
        return rows
    # 旧形式の Excel（.xls）の表だが、見本は .xlsx の中身で作る（取込は中身で読み分ける）
    save("2024_shugiin_hirei_pref", "000979128.xls", {"5210": pref_table(period, ["比例代表区", "区分"])})
    save("2024_shugiin_turnout", "000979120.xls", {"Sheet1": turnout_table(period)})

    # 令和7年参院選（第27回）
    period, parties = "2025-07-20", ELECTION_PARTIES["2025-07-20"]

    def sheet27(pref_name: str, munis: list[str]) -> list[list]:
        head = [None, "党派名"]
        sub = [None, None]
        for p in parties:
            head += [p, None, None]
            sub += ["得票総数", "政党等の", "名簿登載者（特定枠"]
        rows = [["令和７年７月２０日執行", None, None, "参議院比例代表選出議員選挙\u3000開票結果（党派別開票区別得票数）"],
                [f"{pref_name}選挙管理委員会"], [None, "届出番号", None, "1"], head, sub,
                ["開票区名", None, None, "得票総数", "を除く）の得票総数"]]
        for n in munis:
            if n == "かりの村":
                rows.append([n, None, *[""] * (3 * len(parties))])
                continue
            r = [n, None]
            for v in election_votes(period, n):
                r += [fmt(v), fmt(round(v * 0.9)), fmt(v - round(v * 0.9))]
            rows.append(r)
        rows += [["指定都市計", None], ["その他の市計", None, "1"], ["県計", None, "1"]]
        return rows
    save("2025_sangiin_hirei", "13.xlsx", {"開票区別": sheet27("東京都", tokyo),
                                            "開票区別（別紙）": [[None, None, "内訳"], ["党派名", None, parties[0]],
                                                                ["サンプル区", None, "1"]]})
    save("2025_sangiin_hirei", "14.xlsx", {"開票区別": sheet27("神奈川県", ["みほん市中区"])})
    rows = [["（６）都道府県別党派別得票数（比例代表）"], [" "], ["政党等の名称"]]
    for start in range(0, len(parties), 2):   # 政党が2党ずつ縦に並ぶ
        chunk = parties[start:start + 2]
        rows.append([None, *[c for p in chunk for c in (p, None, None, None)]])
        rows.append(["都道府県", *[c for _ in chunk for c in ("得票総数", None, "政党等の", "名簿登載者（特定枠")]])
        rows.append([None, *[c for _ in chunk for c in (None, "得票率（％）", "得票総数", "を除く）の得票総数")]])
        for pref, name in [("13", "東京都"), ("14", "神奈川県")]:
            v = election_prefecture_votes(period, pref)[start:start + 2]
            rows.append([name, *[c for x in v for c in (fmt(x), "10.00", fmt(x), "0")]])
        rows.append(["計", "1", "100.00"])
    rows += [[None, "合計"], [None, ""], ["都道府県", "得票総数"]]   # 最後に全政党の合計の欄
    rows += [[name, fmt(sum(election_prefecture_votes(period, pref)))] for pref, name in [("13", "東京都"), ("14", "神奈川県")]]
    save("2025_sangiin_hirei_pref", "001027818.xlsx", {"都道府県別": rows})
    rows = turnout_table(period)
    save("2025_sangiin_turnout", "001027809.xlsx", {"Sheet1": [r[1:] for r in rows]})   # 1列目に都道府県名

    # 令和8年衆院選（第51回）
    period, parties = "2026-02-08", ELECTION_PARTIES["2026-02-08"]

    def sheet51(pref_name: str, munis: list[tuple[str | None, str | None, list[float]]]) -> list[list]:
        rows = [[], ["令和８年２月８日執行", None, "衆議院比例代表選出議員選挙\u3000開票結果（党派別開票区別得票数）"], [],
                [f"{pref_name}選挙管理委員会"], ["届出番号", None, *range(1, len(parties) + 1)], ["党派名"],
                [None, None, *parties], ["開票区名"]]
        rows += [[c0, c1, *map(fmt, v)] for c0, c1, v in munis]
        rows.append(["県計" if pref_name != "東京都" else "都計", None, "1"])
        return rows
    v = election_votes(period, "サンプル区")
    tokyo51 = [("サンプル区", None, v), (None, "サンプル区第１", [x - 1 for x in v]), (None, "サンプル区第２", [1] * len(v))]
    tokyo51 += [(n, None, election_votes(period, n)) for n in tokyo[1:]]
    v = election_votes(period, "みほん市中区")
    save("2026_shugiin_hirei", "tokyo.xlsx", {"東京都": sheet51("東京都", tokyo51)})
    save("2026_shugiin_hirei", "minamikanto.xlsx",
         {"Sheet1": sheet51("神奈川県", [("みほん市", None, [x * 3 for x in v]), (None, "みほん市中区", v)])})
    save("2026_shugiin_hirei_pref", "001061481.xlsx", {"Sheet1": pref_table(period, ["選挙区", "都道府県"])})
    save("2026_shugiin_turnout", "001061473.xlsx", {"Sheet1": turnout_table(period)})
    return out


# 市町村税課税状況等の調 第11表（総務省の Excel 形式）。1つの市区町村に市町村民税・道府県民税の2行
TAX_YEARS = (2024, 2025)
TAX_HEAD = ["年度", "団体コード", "都道府県名", "団体名", "表側", "所得割の納税義務者数", "総所得金額等",
            "分離長期譲渡所得金額に係る所得金額", "課税対象所得", "課税標準額", "所得割額（税額控除・減免後）"]


def _write_tax(directory: Path, year: int, rnd: random.Random) -> Path:
    from .xlsx import write_sheet
    d = directory / f"soumu_tax_{year}"
    d.mkdir(parents=True, exist_ok=True)
    rows = [[f"〔市町村別内訳〕第11表　課税標準額段階別令和{year - 2018}年度分所得割額等に関する調（合計）"], TAX_HEAD,
            ["", "", "", "", "", "", "（ア）", "（イ）", "（ア～キの計）"],
            ["", "", "", "", "", "人", "千円", "千円", "千円", "千円", "千円"],
            [str(year), "011002", "北海道", "札幌市", "市町村民税", 952921, 1, 1, 3418111236, 1, 157038732],
            # 政令指定都市は市全体の行だけ（地図の単位の区 14199 には割り振らない）
            [str(year), "141909", "神奈川県", "みほん市", "市町村民税", 30000, 1, 0, 150000000, 1, 9000000],
            [str(year), "141909", "神奈川県", "みほん市", "道府県民税", 30000, 1, 0, 150000000, 1, 6000000]]
    for city5, city_name, *_ in MUNICIPALITIES:
        payers = rnd.randint(2000, 90000)
        income = round(payers * rnd.uniform(3500, 9000))     # 千円
        levy = round(income * 0.06)
        for side, share in (("市町村民税", 1.0), ("道府県民税", 0.4 / 0.6)):
            rows.append([str(year), f"{city5}0", "東京都", city_name, side, payers - (side == "道府県民税"),
                         income, 0, income, round(income * 0.7), round(levy * share)])
    path = d / f"J51-{year - 2000}-b.xlsx"
    write_sheet(path, rows, f"令和{year - 2018}年度_第11表市町村別データ")
    return d


# 地価公示（国土数値情報 L01 の GeoJSON 形式）。L01_062〜L01_105 が 1983〜2026年の価格（標準地でない年は 0）。
# (市区町村コード, 市区町村名, 用途, 連番, 経度, 緯度, 標準地になった年)
LAND_POINTS = [
    ("13199", "サンプル", "000", 1, 139.705, 35.665, 1983),
    ("13199", "サンプル", "000", 2, 139.725, 35.685, 2008),   # 途中から標準地になった例
    ("13199", "サンプル", "005", 1, 139.712, 35.668, 1983),   # 商業地（サンプル5-1）
    ("13299", "ためし", "000", 1, 139.650, 35.670, 1995),
    ("13299", "ためし", "009", 1, 139.680, 35.700, 2001),     # 工業地
    ("13901", "どこか", "000", 1, 139.900, 35.900, 1990),     # 境界データにない市区町村（取り込まない）
    ("14199", "みほん中", "000", 1, 139.620, 35.470, 1990),   # 神奈川県（都道府県ごとのファイル）
]


def _write_land_prices(directory: Path, rnd: random.Random) -> Path:
    """地価公示（都道府県ごとのファイル。data/raw/mlit_l01_2026/<都道府県>/L01-26_<都道府県>.geojson）。"""
    d = directory / "mlit_l01_2026"
    features: dict[str, list] = {}
    for city5, city_name, use, seq, lon, lat, since in LAND_POINTS:
        level = {"000": 400_000, "005": 2_000_000, "009": 250_000}[use]
        prices = []
        for y in range(1983, 2027):
            boom = 2.2 if 1988 <= y <= 1992 else 1.0
            prices.append(0 if y < since else int(level * boom * (1 + (y - 2000) * 0.01) * rnd.uniform(0.95, 1.05)))
        props = {"L01_001": city5, "L01_002": use, "L01_003": seq, "L01_007": 2026,
                 "L01_008": prices[-1], "L01_009": round((prices[-1] / prices[-2] - 1) * 100, 1),
                 "L01_024": city_name, "L01_025": f"東京都{city_name}見本町１丁目{seq}番", "L01_026": "_",
                 "L01_027": 120 + seq, "L01_028": "住宅", "L01_048": "見本", "L01_050": 600, "L01_051": "1中専"}
        props.update({f"L01_{62 + i:03d}": v for i, v in enumerate(prices)})
        features.setdefault(city5[:2], []).append({"type": "Feature", "properties": props,
                                                   "geometry": {"type": "Point", "coordinates": [lon, lat]}})
    for pref, feats in features.items():
        _write_geojson(d / pref / f"L01-26_{pref}.geojson", feats)
    return d


def _write_geojson(path: Path, features: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
                    encoding="utf-8")


def _point(props: dict, lon: float, lat: float) -> dict:
    return {"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [lon, lat]}}


# 国土数値情報 学校データ（P29）。東京都以外の公立小中学校の位置だけを使う
MLIT_SCHOOLS = [   # (都道府県, 市区町村, 学校コード, 分類, 名称, 管理者, 休校区分, 経度, 緯度)
    ("14", "14199", "B114199000001", "16001", "みほん市立標本小学校", "3", "1", 139.615, 35.465),
    ("14", "14199", "B114199000002", "16002", "みほん市立標本中学校", "3", "1", 139.625, 35.468),
    ("14", "14199", "B114199000003", "16014", "みほん市立標本学園", "3", "1", 139.630, 35.470),
    ("14", "14199", "C114199000004", "16001", "標本学院小学校", "4", "1", 139.618, 35.462),   # 私立（除く）
    ("14", "14199", "D114199000005", "16004", "神奈川県立標本高等学校", "2", "1", 139.622, 35.461),  # 高校（除く）
    ("14", "14199", "B114199000006", "16001", "みほん市立旧標本小学校", "3", "9", 139.611, 35.466),  # 休校（除く）
    ("13", "13199", "B113199000001", "16001", "サンプル区立見本小学校", "3", "1", 139.705, 35.665),  # 東京都（除く）
]
# 国土数値情報 福祉施設データ（P14）。保育所（050401）の位置だけを使う。14199 は神奈川県の所管として利用条件で除かれる
MLIT_WELFARE = [   # (都道府県, 市区町村名, 市区町村, 小分類, 名称, 経度, 緯度)
    ("14", "みほん市中区", "14199", "050401", "標本保育園", 139.617, 35.466),
    ("14", "みほん市中区", "14199", "050400", "標本幼稚園", 139.619, 35.467),
    ("13", "サンプル区", "13199", "050401", "見本保育園", 139.706, 35.666),
]


def _write_mlit_facilities(directory: Path) -> dict[str, Path]:
    schools: dict[str, list] = {}
    for pref, city5, code, kind, name, founder, open_, lon, lat in MLIT_SCHOOLS:
        schools.setdefault(pref, []).append(_point({
            "P29_001": city5, "P29_002": code, "P29_003": kind, "P29_004": name,
            "P29_005": f"{PREF_NAMES[pref]}{name[:3]}標本町1-1", "P29_006": founder, "P29_007": open_,
            "P29_008": "00", "P29_009": None}, lon, lat))
    for pref, feats in schools.items():
        _write_geojson(directory / "mlit_p29_2023" / pref / f"P29-23_{pref}_GML" / f"P29-23_{pref}.geojson", feats)
    welfare: dict[str, list] = {}
    for pref, city_name, city5, cls, name, lon, lat in MLIT_WELFARE:
        welfare.setdefault(pref, []).append(_point({
            "P14_001": PREF_NAMES[pref], "P14_002": city_name, "P14_003": city5, "P14_004": "標本町1-2",
            "P14_005": "05", "P14_006": cls[:4], "P14_007": cls, "P14_008": name, "P14_009": 5, "P14_010": 1},
            lon, lat))
    for pref, feats in welfare.items():
        _write_geojson(directory / "mlit_p14_2023" / pref / f"P14-23_{pref}_GML" / f"P14-23_{pref}.geojson", feats)
    return {"mlit_schools": directory / "mlit_p29_2023", "mlit_welfare": directory / "mlit_p14_2023"}


# 公立学校一覧（東京都教育委員会の CSV 形式、cp932）と位置参照情報（街区レベル）。
# (学校番号, 学校種別, 設置者, 学校名, 住所, 掲載年度, 想定)
# 使うのは東京都オープンデータカタログに載っている令和5年度分だけ（sources.toml の tokyo_schools_2023）。
SCHOOL_YEARS = (2023,)
SCHOOLS = [
    ("990010", "elementary", "サンプル区", "見本", "見本町1-2", SCHOOL_YEARS, "街区"),
    ("990020", "elementary", "サンプル区", "見本第二", "見本町1-99", SCHOOL_YEARS, "町丁目"),
    ("990030", "elementary", "ためし市", "ためし", "どこにもない町1-1", SCHOOL_YEARS, "位置なし"),
    ("990040", "elementary", "サンプル区", "見本第三", "見本町1-3", SCHOOL_YEARS, "街区"),
    ("990110", "junior_high", "サンプル区", "見本", "見本町1-3-5", SCHOOL_YEARS, "街区"),
    ("990110", "junior_high", "東京都", "(見本・通信制）", "サンプル区見本町1-3-5", SCHOOL_YEARS, "通信制"),
    ("990120", "junior_high", "東京都", "見本高等学校附属", "ためし市試験町2-5-1", SCHOOL_YEARS, "都立"),
    ("990210", "compulsory", "かりの村", "かりの小中学校", "仮置10", SCHOOL_YEARS, "義務教育学校"),
    ("990050", "elementary", "ためし市", "遠方", "遠い町500", SCHOOL_YEARS, "大字レベル"),
    ("990060", "elementary", "かりの村", "かりの", "22", SCHOOL_YEARS, "大字を書かない住所"),
]
SCHOOL_HEAD = {
    "elementary": ["学校番号", "設置者", "学校名", "児童数(通級生を除く。)/総数"]
                  + [f"児童数(通級生を除く。)/{g}学年" for g in "１２３４５６"]
                  + ["児童数(通級生を除く。)/(再掲)特別支援学級", "教員数", "職員数"],
    "junior_high": ["学校番号", "設置者", "学校名", "生徒数(通級生を除く。)/総数"]
                   + [f"生徒数(通級生を除く。)/{g}学年" for g in "１２３"]
                   + ["学級数(通級指導学級を含む。)/総数", "教員数", "職員数"],
    "compulsory": ["学校番号", "設置者", "学校名", "児童・生徒数(通級生を除く。)/総数",
                   "児童・生徒数(通級生を除く。)/前期課程/計"]
                  + [f"児童・生徒数(通級生を除く。)/前期課程/{g}学年" for g in "１２３４５６"]
                  + ["児童・生徒数(通級生を除く。)/後期課程/計"]
                  + [f"児童・生徒数(通級生を除く。)/後期課程/{g}学年" for g in "７８９"]
                  + ["教員数", "職員数"],
}
ADDRESS_HEAD = ["学校番号", "設置者", "学校名", "郵便番号", "住所", "電話番号", "学校名(フリガナ)"]
ISJ_HEAD = ["都道府県名", "市区町村名", "大字・丁目名", "小字・通称名", "街区符号・地番", "座標系番号",
            "Ｘ座標", "Ｙ座標", "緯度", "経度", "住居表示フラグ", "代表フラグ", "更新前履歴フラグ", "更新後履歴フラグ"]
# (市区町村, 大字・丁目, 街区, 経度, 緯度, 代表フラグ)
ISJ_ROWS = [
    ("サンプル区", "見本町一丁目", "2", 139.7050, 35.6650, "1"),
    ("サンプル区", "見本町一丁目", "2", 139.7052, 35.6652, "0"),
    ("サンプル区", "見本町一丁目", "3", 139.7100, 35.6680, "1"),
    ("ためし市", "試験町二丁目", "5", 139.6500, 35.6700, "1"),
    ("かりの村", "仮置", "10", 139.3700, 34.7100, "1"),
]


def _write_schools(directory: Path, rnd: random.Random) -> dict[str, Path]:
    out = {}
    d = directory / "mlit_isj_2025"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "13_2025.csv").open("w", encoding="cp932", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(ISJ_HEAD)
        for muni, town, block, lon, lat, rep in ISJ_ROWS:
            w.writerow(["東京都", muni, town, "", block, "9", "0", "0", f"{lat:.6f}", f"{lon:.6f}", "1", rep, "0", "0"])
    out["isj"] = d / "13_2025.csv"
    d = directory / "mlit_isj_oaza_2025" / "13000-19.0b"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "13_2025.csv").open("w", encoding="cp932", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["都道府県コード", "都道府県名", "市区町村コード", "市区町村名", "大字町丁目コード",
                    "大字町丁目名", "緯度", "経度", "原典資料コード", "大字・字・丁目区分コード"])
        w.writerow(["13", "東京都", "13299", "ためし市", "132990099000", "遠い町", "35.700000", "139.680000", "0", "1"])
        w.writerow(["13", "東京都", "13499", "かりの村", "134990001000", "仮置", "34.720000", "139.380000", "0", "1"])
    out["isj_oaza"] = d / "13_2025.csv"
    # 犯罪オープンデータの町丁目の照合に使う全国版（都道府県ごと）。同じ内容を東京都分として置く
    d = directory / "mlit_isj_oaza_national" / "13" / "13000-19.0b"
    d.mkdir(parents=True, exist_ok=True)
    (d / "13_2025.csv").write_bytes((out["isj_oaza"]).read_bytes())
    grades = {"elementary": 6, "junior_high": 3, "compulsory": 9}
    for year in SCHOOL_YEARS:
        d = directory / f"tokyo_schools_{year}"
        d.mkdir(parents=True, exist_ok=True)
        for school_type, head in SCHOOL_HEAD.items():
            rows, addresses, total_all = [], [], 0
            for number, t, founder, name, address, years, _ in SCHOOLS:
                if t != school_type or year not in years:
                    continue
                g = [rnd.randint(0, 120) for _ in range(grades[t])]
                if number == "990210":
                    g[1] = 0   # 該当なし（「-」）の学年
                cells = ["-" if v == 0 else str(v) for v in g]
                if t == "compulsory":
                    cells = [str(sum(g[:6]))] + cells[:6] + [str(sum(g[6:]))] + cells[6:]
                rows.append([number, founder, name, str(sum(g))] + cells
                            + [str(x) for x in [rnd.randint(0, 9), 20, 2]][:len(head) - 4 - len(cells)])
                total_all += sum(g)
                # 区市町村名から書かれた住所の例（令和3年度の実データにあった書き方）
                written = founder + address if number == "990020" else address
                addresses.append([number, founder, name, "100-0000", written, "03-0000-0000", "ミホン"])
            rows.append(["合計", "", "", str(total_all)] + [""] * (len(head) - 4))
            _write_cp932(d / f"{school_type}_counts.csv", head, rows)
            _write_cp932(d / f"{school_type}_address.csv", ADDRESS_HEAD, addresses)
        out[f"schools_{year}"] = d
    return out


def _write_cp932(path: Path, head: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="cp932", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(rows)


# 駅別乗降客数（国土数値情報 S12 の GeoJSON 形式、2011〜2024年度）。
# (駅名, 駅コード, グループコード, 運営会社, 路線名, 経度, 緯度, 年度ごとの記載方法)
# 記載方法: "value"=値あり、"other"=他路線駅に記載、"nodata"=データなし、"private"=非公開、
#          "opened2015"=2015年度開業（それより前は駅なし）
STATION_YEARS = range(2011, 2025)
STATIONS = [
    ("見本中央", "900010", "900010", "東日本旅客鉄道", "見本線", 139.7300, 35.6900, "value"),
    ("見本中央", "900010", "900010", "東日本旅客鉄道", "見本線", 139.7302, 35.6901, "dup"),  # 同じ駅コードの別のホーム
    ("見本中央", "900011", "900010", "東日本旅客鉄道", "試験線", 139.7305, 35.6898, "other"),
    ("見本中央", "900012", "900010", "東京地下鉄", "1号線見本線", 139.7298, 35.6905, "value"),
    ("見本中央", "900013", "900010", "東京地下鉄", "2号線試験線", 139.7310, 35.6903, "value"),
    ("見本中央", "900014", "900010", "東京都", "3号線仮置線", 139.7295, 35.6895, "other"),
    ("見本中央", "900015", "900015", "東日本旅客鉄道", "遠方線", 139.7350, 35.6880, "other"),  # 300m超離れたホーム
    ("ためし", "900020", "900020", "京王電鉄", "ためし線", 139.6700, 35.6800, "nodata2013"),
    ("試験公園", "900030", "900030", "架空鉄道", "公園線", 139.6550, 35.6950, "private"),
    ("見本新町", "900040", "900040", "東日本旅客鉄道", "見本線", 139.7450, 35.6700, "opened2015"),
    ("県外", "900050", "900050", "架空鉄道", "県外線", 139.0000, 36.5000, "value"),
    ("標本", "900060", "900060", "架空鉄道", "標本線", 139.6200, 35.4700, "value"),   # 神奈川県（全国版の確認用）
]


def _write_stations(directory: Path, rnd: random.Random) -> Path:
    d = directory / "mlit_s12_2024" / "UTF-8"
    d.mkdir(parents=True, exist_ok=True)
    feats = []
    for name, code, group, operator, line, lon, lat, how in STATIONS:
        props = {"S12_001": name, "S12_001c": code, "S12_001g": group, "S12_002": operator,
                 "S12_003": line, "S12_004": 11, "S12_005": 2}
        base_value = rnd.randint(2000, 300000)
        for y in STATION_YEARS:
            f = 6 + 4 * (y - 2011)
            dup, has, note, value = 1, 1, None, round(base_value * (0.7 if y == 2020 else 1) * rnd.uniform(0.95, 1.05))
            if how in ("other", "dup"):
                dup, value = 2, 0
            elif how == "nodata2013" and y <= 2013:
                has, value = 2, 0
            elif how == "private":
                has, value = 3, 0
            elif how == "opened2015" and y < 2015:
                has, value = 4, 0
            if code == "900010" and how == "value":
                note = "試験線・遠方線を含む"
            if code == "900013":
                note = "東京都・3号線仮置線を含む"
            props.update({f"S12_{f:03d}": dup, f"S12_{f + 1:03d}": has,
                          f"S12_{f + 2:03d}": note, f"S12_{f + 3:03d}": value})
        feats.append({"type": "Feature", "properties": props, "geometry": {
            "type": "LineString", "coordinates": [[lon - 0.0005, lat], [lon + 0.0005, lat]]}})
    path = d / "S12-25_NumberOfPassengers.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False),
                    encoding="utf-8")
    return path


# 昼間人口（東京都の統計 表1 の形式、UTF-8 BOM付き）
def census2025_values(base: dict, seed: int = 42) -> dict[str, dict[str, int]]:
    """2025年国勢調査（人口等基本集計）の見本の値。市区町村 → 列名 → 値（テストでも使う）。"""
    rnd = random.Random(f"{seed}-census2025")
    out = {}
    for city5, _, town, west, south in MUNICIPALITIES + OTHER_MUNICIPALITIES:
        before = sum(base[k][0][0] for k, _, _ in _cells(city5, town, west, south))
        pop = round(before * rnd.uniform(0.95, 1.06))
        young = round(pop * rnd.uniform(0.08, 0.14))
        old = round(pop * rnd.uniform(0.18, 0.3))
        unknown = round(pop * 0.01)
        hh = round(pop / rnd.uniform(1.7, 2.2))
        general = hh - 3
        out[city5] = {"人口": pop, "世帯数": hh, "一般世帯数": general, "15歳未満": young,
                      "15～64歳": pop - young - old - unknown, "65歳以上": old,
                      "単独世帯": round(general * rnd.uniform(0.3, 0.6)),
                      "18歳未満世帯員のいる": round(general * rnd.uniform(0.1, 0.25))}
    return out


def _write_census2025(directory: Path, base: dict) -> dict[str, Path]:
    """令和7年国勢調査 人口等基本集計の e-Stat の Excel（表1-1・2-7・6-3・9-1 の形式）。
    地域識別コード 1（政令指定都市の市全体）・9（2000年の市区町村）の行は取り込まない。a は全国（使わない）と都道府県。"""
    from .xlsx import write_sheet
    vals = census2025_values(base)
    pnames = {"00": "全国", **PREF_NAMES}
    names = {c: n for c, n, *_ in MUNICIPALITIES + OTHER_MUNICIPALITIES}
    areas = [("a", "00", "00000", "全国"), ("a", "13", "13000", "東京都"), ("a", "14", "14000", "神奈川県"), ("1", "14", "14190", "みほん市")]
    areas += [("0" if c.startswith("131") or c.startswith("141") else "2" if c[2] == "2" else "3", c[:2], c, names[c])
              for c in vals]
    total = lambda pref, key: sum(v[key] for c, v in vals.items() if c[:2] == pref)
    def value(code, key):
        if code in vals:
            return vals[code][key]
        if code == "00000":
            return sum(v[key] for v in vals.values()) + 11
        # 都道府県・市全体の行。区の再編などで市区町村の合計と合わないことがあるので少しずらす
        return total(code[:2], key) + 7
    out = {}

    def save(key: str, fname: str, rows: list[list]) -> None:
        d = directory / key
        d.mkdir(parents=True, exist_ok=True)
        write_sheet(d / fname, rows, fname.removesuffix(".xlsx"))
        out[key] = d

    title = [["令和７年国勢調査　人口等基本集計"], ["見本"], [], ["1) 注記"]]
    # 表1-1: 地域の列は 2000年と2025年の両方。地域名の先頭は並び順の番号（コードではない）
    rows = title + [[None] * 6 + ["表章項目", "人口", "人口", "人口", "世帯数", "世帯数"],
                    [None] * 6 + ["事項名", "男女", "男女", "男女", "世帯の種類", "世帯の種類"],
                    [None] * 6 + ["項目名", "0_総数", "1_男", "2_女", "0_総数", "1_一般世帯"],
                    [None] * 6 + ["表章単位", "人", "人", "人", "世帯", "世帯"],
                    ["地域識別コード", "2000年_都道府県", "2000年_地域コード", "2000年地域", "2025年_都道府県",
                     "2025年_地域コード", "地域名", " "]]
    for k, (level, pref, code, label) in enumerate(areas):
        pop = value(code, "人口")
        rows.append([level, f"{pref}_{pnames[pref]}", code, "2000", f"{pref}_{pnames[pref]}", code,
                     f"{1000 + k}_{label}", pop, pop // 2, pop - pop // 2, value(code, "世帯数"), value(code, "一般世帯数")])
    rows.append(["9", "13_東京都", "13199", "2000", "13_東京都", "13199", "9999_旧サンプル町", 5, 3, 2, 2, 2])
    save("census2025_municipal_population", "b01_01.xlsx", rows)
    # 表2-7: 国籍総数か日本人・男女の分類の列が地域の前にある
    rows = title + [[None] * 8 + ["表章項目"] + ["人口"] * 4,
                    [None] * 8 + ["事項名"] + ["年齢"] * 4,
                    [None] * 8 + ["項目名", "00_総数", "R1_（再掲）15歳未満", "R2_（再掲）15～64歳", "R3_（再掲）65歳以上"],
                    [None] * 8 + ["表章単位"] + ["人"] * 4,
                    ["国籍総数か日本人", "男女", "地域識別コード", "2000年_都道府県", "2000年_地域コード", "2000年地域",
                     "2025年_都道府県", "2025年_地域コード", "地域名", " "]]
    for nat, ratio in (("0_国籍総数", 1.0), ("1_うち日本人", 0.9)):
        for sex, share in (("0_総数", 1.0), ("1_男", 0.48), ("2_女", 0.52)):
            for level, pref, code, label in areas:
                f = ratio * share
                rows.append([nat, sex, level, f"{pref}_{pnames[pref]}", code, "2000", f"{pref}_{pnames[pref]}",
                             code, f"{code}_{label}", round(value(code, "人口") * f)]
                            + [round(value(code, c) * f) for c in ("15歳未満", "15～64歳", "65歳以上")])
    save("census2025_municipal_age", "b02_07.xlsx", rows)
    # 表6-3: 地域名の先頭が市区町村コード
    rows = title + [[None, None, "表章項目", "一般世帯数", "一般世帯数", "一般世帯人員"],
                    [None, None, "事項名", "世帯人員の人数", "世帯人員の人数", None],
                    [None, None, "項目名", "00_総数", "01_世帯人員が1人", None],
                    [None, None, "表章単位", "世帯", "世帯", "人"],
                    ["地域識別コード", "都道府県", "地域名", " "]]
    for level, pref, code, label in areas:
        rows.append([level, f"{pref}_{pnames[pref]}", f"{code}_{label}", value(code, "一般世帯数"),
                     value(code, "単独世帯"), value(code, "人口") - 10])
    save("census2025_municipal_household_size", "b06_03.xlsx", rows)
    # 表9-1: 世帯の家族類型の分類の列が地域の後ろにある
    rows = title + [[None] * 4 + ["表章項目", "一般世帯数", "一般世帯数"],
                    [None] * 4 + ["事項名", "世帯員の年齢による世帯の種類", "世帯員の年齢による世帯の種類"],
                    [None] * 4 + ["項目名", "0_総数", "4_うち18歳未満世帯員のいる一般世帯"],
                    [None] * 4 + ["表章単位", "世帯", "世帯"],
                    ["地域識別コード", "都道府県", "地域名", "階層レベル（世帯の家族類型）", "世帯の家族類型", " "]]
    for level, pref, code, label in areas:
        rows.append([level, f"{pref}_{pnames[pref]}", f"{code}_{label}", "1", "0_総数",
                     value(code, "一般世帯数"), value(code, "18歳未満世帯員のいる")])
        rows.append([level, f"{pref}_{pnames[pref]}", f"{code}_{label}", "1", "3_単独世帯",
                     value(code, "単独世帯"), "-"])
    save("census2025_municipal_family_type", "b09_01.xlsx", rows)
    return out


# 国勢調査 人口等基本集計の男女・国籍別人口（#102）。年ごとの国籍の区分（その年の表にある国籍だけ）
CENSUS_FOREIGN_NATIONS = {
    2010: ["韓国・朝鮮", "中国", "フィリピン", "タイ", "インドネシア", "ベトナム", "イギリス", "アメリカ", "ブラジル", "ペルー"],
    2015: ["韓国・朝鮮", "中国", "フィリピン", "タイ", "インドネシア", "ベトナム", "インド", "イギリス", "アメリカ",
           "ブラジル", "ペルー"],
    2020: ["韓国・朝鮮", "中国", "フィリピン", "タイ", "インドネシア", "ベトナム", "インド", "ネパール", "イギリス",
           "アメリカ", "ブラジル", "ペルー"],
    2025: ["韓国・朝鮮", "中国", "フィリピン", "タイ", "インドネシア", "ベトナム", "インド", "ネパール", "カンボジア",
           "スリランカ", "パキスタン", "バングラデシュ", "マレーシア", "ミャンマー", "モンゴル", "イギリス", "フランス",
           "ロシア", "アメリカ", "カナダ", "ブラジル", "ペルー", "オーストラリア"],
}


def census_foreign_values(year: int) -> dict[str, dict[str, int]]:
    """男女・国籍別人口の表の見本の値（男女計）。地域コード（都道府県は5桁の 13000 など）→ 列名 → 値。
    都道府県の行は市区町村の合計より少し多くする（公表の都道府県の行を使うことを確かめる）。
    かりの村（13499）は人口50人未満で、外国人は0人（「-」）。"""
    rnd = random.Random(f"census-foreign-{year}")
    nations = CENSUS_FOREIGN_NATIONS[year]
    out: dict[str, dict[str, int]] = {}
    for city5, *_ in MUNICIPALITIES + OTHER_MUNICIPALITIES:
        total = 30 + year % 7 if city5 == "13499" else rnd.randint(50_000, 400_000)
        by_nation = {n: (0 if city5 == "13499" else rnd.randint(0, 3_000)) for n in nations}
        foreign = sum(by_nation.values()) + (0 if city5 == "13499" else rnd.randint(0, 500))   # その他を含む
        out[city5] = {"総数": total, "外国人人口": foreign, **by_nation}
    for pref in ("13", "14"):
        members = [v for c, v in out.items() if c[:2] == pref]
        out[pref + "000"] = {k: sum(v[k] for v in members) + 3 for k in members[0]}
    return out


def _write_census_foreign(directory: Path) -> dict[str, Path]:
    """2025・2020年は Excel（2020年は「表章項目」「項目名」の見出しの文字がない）、2015・2010年は CSV（cp932）。"""
    from .xlsx import write_sheet
    names = {c: n for c, n, *_ in MUNICIPALITIES + OTHER_MUNICIPALITIES}
    out = {}
    for year in (2010, 2015, 2020, 2025):
        vals = census_foreign_values(year)
        nations = CENSUS_FOREIGN_NATIONS[year]
        areas = [("a", "13000", "東京都"), ("a", "14000", "神奈川県"), ("1", "14100", "みほん市")]
        areas += [("0" if c.startswith(("131", "141")) else "2" if c[2] == "2" else "3", c, names[c]) for c in names]
        areas.insert(0, ("a", "00000", "全国"))
        areas.append(("3", "13498", "合併で消えた村"))   # 最新の境界にない市区町村（取り込まない）
        def cell(code, key):
            v = vals.get(code, {"総数": 999, "外国人人口": 9}).get(key, 0)
            return "-" if v == 0 else v
        d = directory / f"census{year}_municipal_foreign"
        d.mkdir(parents=True, exist_ok=True)
        if year >= 2020:
            sep = "、" if year == 2025 else "，"
            heads = ["0_総数", "1_外国人"] + [f"{101 + i}_{n.replace('・', sep)}" for i, n in enumerate(nations)] \
                + [f"{101 + len(nations)}_その他", "2_日本人", "3_日本人・外国人の別「不詳」"]
            keys = ["総数", "外国人人口", *nations, None, None, None]
            title = [[f"令和{year - 2018}年国勢調査　人口等基本集計"], ["見本"], [], ["1) 注記"]]
            if year == 2025:
                head = [[None] * 3 + ["表章項目"] + ["人口"] * len(heads), [None] * 3 + ["事項名"] + ["国籍"] * len(heads),
                        [None] * 3 + ["項目名"] + heads, [None] * 3 + ["表章単位"] + ["人"] * len(heads)]
            else:
                head = [[None] * 4 + ["人口"] * len(heads), [None] * 4 + ["国籍"] * len(heads),
                        [None] * 4 + ["1.0"] * len(heads), [None] * 4 + heads, [None] * 4 + ["人"] * len(heads)]
            rows = title + head + [["男女", "地域識別コード", "都道府県", "地域名", " "]]
            for sex, f in (("0_総数", 1.0), ("1_男", 0.5)):
                for level, code, label in areas:
                    rows.append([sex, level, f"{code[:2]}_x", f"{code}_{label}"]
                                + [(round(c * f) if isinstance(c := cell(code, k), int) else c) if k else 1
                                   for k in keys])
            fname = "b49_01.xlsx" if year == 2025 else "b44_01.xlsx"
            write_sheet(d / fname, rows, fname.removesuffix(".xlsx"))
        else:
            labels = ["総数（国籍）", *[n.replace("・", "，") for n in nations], "その他 1)",
                      "（別掲）総人口 2)" if year == 2010 else "（別掲）総人口 ", "（別掲）日本人"]
            keys = ["外国人人口", *nations, None, "総数", None]
            lines = [["1", f"国勢調査人口等基本集計（見本 {year}）"], ["2", "", "", "", "", "第38表　国籍別外国人数"],
                     ["11", "", "", "", "", "総数（男女別）"] + [""] * (len(labels) - 1) + ["男"],
                     ["12", "※大項目", "地域コード", "地域識別コード", "", *labels, *labels]]
            for level, code, label in areas:
                vals_row = [cell(code, k) if k else 1 for k in keys]
                lines.append(["13", "", code, level, label, *vals_row, *vals_row])
                if level == "a" and code == "13000":
                    lines.append(["14", "", "13001", "b", "東京都 市部", *vals_row, *vals_row])
                if level != "a":
                    lines.append(["15", "", code, "d", f"{label}　人口集中地区", *vals_row, *vals_row])
            fname = "c41.csv" if year == 2010 else "c38.csv"
            with (d / fname).open("w", encoding="cp932", newline="") as fh:
                csv.writer(fh, quoting=csv.QUOTE_MINIMAL).writerows(lines)
        out[f"census{year}_municipal_foreign"] = d
    return out


def _write_daytime(directory: Path, base: dict, rnd: random.Random) -> Path:
    d = directory / "tokyo_daytime_2020"
    d.mkdir(parents=True, exist_ok=True)
    header = ["階層", "地域コード", "地域", "昼間人口／総数（人）", "昼間人口／男（人）", "昼間人口／女（人）",
              "常住人口／総数（人）", "昼夜間人口比率／総数（％）"]
    rows = []
    for (city5, city_name, town, west, south), ratio in zip(MUNICIPALITIES, (2.5, 0.85, 1.0)):
        resident = sum(base[k][0][0] for k, _, _ in _cells(city5, town, west, south))
        day = round(resident * ratio * rnd.uniform(0.98, 1.02))
        rows.append(["2", city5, city_name, day, day // 2, day - day // 2, resident,
                     round(day / resident * 100, 1)])
    path = d / "tj20zv0100.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(header)
        wr.writerow(["0", "13000", "東京都総数"] + [""] * (len(header) - 3))
        wr.writerows(rows)
        wr.writerow(["階層（0:東京都の合計　1:区部・市部・郡部・島部　2:区市町村）"] + [""] * (len(header) - 1))
    return path


def _write_daytime_past(directory: Path, year: int, base: dict, rnd: random.Random) -> Path:
    """平成27年は列名が「地域階層」、平成22年は階層の列がなく区部・市部の行が混じる形式。"""
    d = directory / f"tokyo_daytime_{year}"
    d.mkdir(parents=True, exist_ok=True)
    head = ["地域コード", "地域", "昼間人口／総数（人）", "夜間人口／総数（人）"]
    rows = [["13000", "東京都総数"], ["13100", "区部"]]
    for (city5, city_name, town, west, south), ratio in zip(MUNICIPALITIES, (2.3, 0.86, 1.0)):
        resident = sum(base[k][0][0] for k, _, _ in _cells(city5, town, west, south))
        rows.append([city5, city_name, round(resident * ratio * rnd.uniform(0.95, 1.0)), resident])
    rows[0] += [sum(r[2] for r in rows[2:]), sum(r[3] for r in rows[2:])]
    rows[1] += rows[2][2:]
    if year == 2015:
        head = ["地域階層"] + head
        rows = [["0" if r[0] == "13000" else "1" if r[0] == "13100" else "2"] + r for r in rows]
    path = d / f"tj{str(year)[2:]}zv0100.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(head)
        wr.writerows(rows)
    return path


# 外国人人口（国勢調査 小地域集計 第2表。男女の列がなく、外国人人口・世帯数の列名は1行上）
def _write_foreign_census(directory: Path, base: dict, rnd: random.Random) -> Path:
    d = directory / "census2020_small_area_foreign" / "13"
    d.mkdir(parents=True, exist_ok=True)
    head = ["市区町村コード", "町丁字コード", "地域階層レベル", "秘匿処理", "秘匿先情報", "合算地域",
            "都道府県名", "市区町村名", "大字・町名", "字・丁目名"]
    rows = []
    for city5, city_name, town, west, south in MUNICIPALITIES:
        cells = list(_cells(city5, town, west, south))
        values = {}
        for key, _, _ in cells:
            pop, male, female, households = base[key][0]
            values[key] = [pop, male, female, round(pop * rnd.uniform(0.0, 0.12)), round(households * 0.97)]
        hidden_key, merge_key = cells[5][0], cells[6][0]
        total = [sum(v[i] for v in values.values()) for i in range(5)]
        rows.append([city5, "-", "1", "", "", "", "東京都", city_name, "", ""] + total)
        for key, name, _ in cells:
            code = key[:9] if key.endswith("00") else key
            level = "3" if len(code) == 9 else "4"
            r = [city5, code[5:], level, "", "", "", "東京都", city_name, name, ""]
            if key == hidden_key:
                r[3:5] = ["秘匿地域", merge_key[5:]]
                rows.append(r + ["X"] * 5)
            elif key == merge_key:
                r[3], r[5] = "合算地域あり", hidden_key[5:]
                rows.append(r + [a + b for a, b in zip(values[merge_key], values[hidden_key])])
            else:
                rows.append(r + [v if v else "-" for v in values[key]])
    path = d / "h02_13.csv"
    with path.open("w", encoding="cp932", newline="") as f:
        wr = csv.writer(f)
        width = 1 + len(head) + 5
        wr.writerow(["1", "令和２年国勢調査　小地域集計　（架空データ）"] + [""] * (width - 2))
        wr.writerow(["2", "第2表　男女別人口，外国人人口及び世帯数－町丁・字等"] + [""] * (width - 2))
        wr.writerow(["3"] + [""] * (width - 1))
        wr.writerow(["4"] + [""] * len(head) + ["人口", "人口", "人口", "外国人人口", "世帯数"])
        wr.writerow(["5"] + head + ["総数", "男", "女", "-", "-"])
        wr.writerows([str(i + 6)] + r for i, r in enumerate(rows))
    return d


# 外国人人口（東京都の統計 表3 区市町村、国籍・地域別）。かりの村は島しょの例で支庁単位（地域階層3）だけ載せる。
# 2020年は全国の住民基本台帳がない年の例（総数も東京都の表から取る）。2026年は国籍別だけを東京都の表から取る
FOREIGN_YEARS = (2020, 2026)
FOREIGN_COLUMNS = ["総数", "男", "女", "アジア", "中国", "台湾", "インド", "韓国", "朝鮮", "ネパール", "フィリピン",
                   "ベトナム", "ミャンマー", "北米", "米国", "無国籍・その他"]


def _write_foreign(directory: Path, year: int, base: dict, rnd: random.Random) -> Path:
    d = directory / f"tokyo_foreign_{year}"
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for city5, city_name, town, west, south in MUNICIPALITIES:
        pop = sum(base[k][0][0] for k, _, _ in _cells(city5, town, west, south))
        nat = {c: round(pop * rnd.uniform(0.0, 0.02)) for c in
               ["中国", "台湾", "インド", "韓国", "朝鮮", "ネパール", "フィリピン", "ベトナム", "ミャンマー", "米国"]}
        other = round(pop * 0.005)
        total = sum(nat.values()) + other
        asia = total - nat["米国"] - other
        male = total // 2
        vals = {"総数": total, "男": male, "女": total - male, "アジア": asia, "北米": nat["米国"],
                "無国籍・その他": other, **nat}
        level, code = ("3", "13360") if city5 == "13499" else ("4", city5)
        rows.append([level, code, "大島支庁" if level == "3" else city_name] + [vals[c] for c in FOREIGN_COLUMNS])
    path = d / f"ga{str(year)[2:]}ev0300.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["地域階層", "地域コード", "国・地域(人)"] + FOREIGN_COLUMNS)
        wr.writerow(["0", "13000", "東京都総数"] + [""] * len(FOREIGN_COLUMNS))
        wr.writerows(rows)
        wr.writerow(["地域階層（0:総数　1:区部・市部・町村部　2:郡部・島部　3:支庁　4:区市町村）"]
                    + [""] * (len(FOREIGN_COLUMNS) + 2))
    return path


# 住民基本台帳の外国人住民（総務省、全国の市区町村別）。団体コードは検査数字付きの6桁。都道府県の行は
# 市区町村の合計と少しずらし（出典の都道府県の値を使うことを確かめる）、政令指定都市の市全体の行も入れる
JUKI_FOREIGN_YEARS = (2025, 2026)


def _check_digit(code5: str) -> str:
    r = sum(int(c) * w for c, w in zip(code5, (6, 5, 4, 3, 2))) % 11
    return code5 + str((11 - r) % 10)


def juki_foreign_values(year: int) -> dict[str, int]:
    """見本の市区町村ごとの外国人住民の人口（年ごとに決まった値）。"""
    rnd = random.Random(f"juki-values-{year}")
    return {c: rnd.randint(200, 3000) if c != "13499" else 12
            for c, *_ in MUNICIPALITIES + OTHER_MUNICIPALITIES}


def juki_total_values(year: int) -> dict[str, int]:
    """見本の市区町村ごとの住民基本台帳の人口（日本人住民と外国人住民の合計）。島しょの村は50人未満にする。"""
    rnd = random.Random(f"juki-total-{year}")
    return {c: v + (rnd.randint(20000, 300000) if c != "13499" else 28)
            for c, v in juki_foreign_values(year).items()}


def _write_juki_foreign(directory: Path, year: int, rnd: random.Random, total: bool = False) -> Path:
    """【外国人住民】（total なら【総計】）の市区町村別人口。2つは同じ形。"""
    from .xlsx import write_sheet
    kind, label = ("total", "総計") if total else ("foreign", "外国人住民")
    d = directory / f"soumu_juki_{kind}_{year}"
    d.mkdir(parents=True, exist_ok=True)
    vals = juki_total_values(year) if total else juki_foreign_values(year)
    names = {c: n for c, n, *_ in MUNICIPALITIES + OTHER_MUNICIPALITIES}
    era = f"令和{year - 2018}年"
    rows = [[f"{era}1月1日住民基本台帳人口・世帯数、{era}（1月1日から同年12月31日まで）人口動態（市区町村別）【{label}】"],
            [None] * 3 + [era] * 4, [None] * 3 + [f"{year}年"] * 4, [None] * 3 + ["人口", "人口", "人口", "世帯数"],
            [None] * 3 + ["男", "女", "計", "世帯数"], ["団体コード", "都道府県名", "市区町村名", "人", "人", "人", "世帯"]]

    def row(code5, pref, name, total):
        male = total // 2
        return [_check_digit(code5), pref, name, male, total - male, total, round(total * 0.6)]

    rows.append(["-", "合計", "-"] + [None] * 4)
    for pref in ("13", "14"):
        members = {c: v for c, v in vals.items() if c[:2] == pref}
        rows.append(row(f"{pref}000", PREF_NAMES[pref], "-", sum(members.values()) + 7))
        if pref == "14":
            rows.append(row("14190", PREF_NAMES[pref], "みほん市", sum(members.values())))
        rows += [row(c, PREF_NAMES[pref], names[c], v) for c, v in members.items()]
    rows.append(["注：見本の注記"])
    path = d / f"juki_{kind}_{year}.xlsx"
    write_sheet(path, rows, f"人口、世帯数、人口動態（市区町村別）【{label}】")
    return path


# 在留外国人統計（市区町村別・国籍別、12月末）。2022年末は横長の第3表、2023年末は在留資格別の縦長の表。
# 2023年末は、かりの村を総数10人以下の市区町村として全国の「その他」（99999）にまとめる
ZAIRYU_YEARS = (2022, 2023)
ZAIRYU_NATIONS = ["中国", "ベトナム", "韓国", "フィリピン", "ブラジル", "ネパール", "インドネシア", "米国", "台湾", "タイ"]


def zairyu_values(year: int) -> dict[str, dict[str, int]]:
    """見本の市区町村ごと・国籍ごとの在留外国人数（タイはサンプル区だけ0人）。"""
    rnd = random.Random(f"zairyu-values-{year}")
    out = {}
    for c, *_ in MUNICIPALITIES + OTHER_MUNICIPALITIES:
        v = {n: (rnd.randint(0, 3) if c == "13499" else rnd.randint(5, 400)) for n in ZAIRYU_NATIONS}
        if c == "13199":
            v["タイ"] = 0
        out[c] = v
    return out


def _write_zairyu(directory: Path, year: int, rnd: random.Random) -> Path:
    from .xlsx import write_sheets
    d = directory / f"moj_zairyu_foreign_{year}"
    d.mkdir(parents=True, exist_ok=True)
    vals = zairyu_values(year)
    names = {c: n for c, n, *_ in MUNICIPALITIES + OTHER_MUNICIPALITIES}
    path = d / f"zairyu_{year}.xlsx"
    if year <= 2022:
        rows = [["第３表　市区町村別　国籍・地域別　在留外国人"],
                ["市区町村コード", "都道府県市区町村", "総数"] + ZAIRYU_NATIONS + ["その他"]]

        def row(code, name, v):
            other = 3
            return [code, name, sum(v.values()) + other] + [v[n] for n in ZAIRYU_NATIONS] + [other]

        add = lambda codes: {n: sum(vals[c][n] for c in codes) for n in ZAIRYU_NATIONS}
        rows.append([None, "総数"] + [None] * (len(ZAIRYU_NATIONS) + 2))
        for pref in ("13", "14"):
            codes = [c for c in vals if c[:2] == pref]
            # 都道府県の行は市区町村の合計より少し多い（出典の都道府県の値を使うことを確かめる）
            rows.append(row(f"{pref}000", PREF_NAMES[pref], {n: v + 1 for n, v in add(codes).items()}))
            if pref == "13":
                rows.append(row("13100", "特別区", add(["13199"])))
            else:
                rows.append(row("14190", "みほん市", add(codes)))
            rows += [row(c, names[c], vals[c]) for c in codes]
        rows.append(["     ", "未定・不詳"] + [1] * (len(ZAIRYU_NATIONS) + 2))
        rows.append(["（注)　北方領土(歯舞群島、色丹島、国後島及び択捉島)を除く。"])
        write_sheets(path, {f"{year - 2000}-12-03": rows})
    else:
        statuses = ["永住者", "留学", "技能実習２号ロ"]
        rows = [["市区町村コード", "都道府県", "市区町村", "国籍・地域", "在留資格", "在留外国人数"]]
        for c, v in vals.items():
            pref, name = PREF_NAMES[c[:2]], names[c]
            if c == "13499":
                pref = name = "その他"
                c = "99999"
            for n, total in v.items():
                # 在留資格ごとに分ける（0人の組み合わせの行はない）
                parts = [total // 2, total - total // 2 - total // 4, total // 4]
                rows += [[c, pref, name, n, st, k] for st, k in zip(statuses, parts) if k]
            rows.append([c, pref, name, "シンガポール", "留学", 1])
        write_sheets(path, {"注意事項": [["（注１）総数が１０人以下の市区町村は「その他」にまとめています。"]],
                            "PVT": [["国籍・地域", "(すべて)"]],
                            f"令和{str(year - 2018).translate(str.maketrans('0123456789', '０１２３４５６７８９'))}年末": rows})
    return path


# 犯罪の認知件数（警視庁の町丁別CSVの形式）。2025年は町丁目の合計＋以下不詳＝計、
# 2024年はサンプル区の計が合わない例（表にない町丁目を値なしにする）。かりの村は2024年に0件（行なし）。
# 交通事故（警察庁 オープンデータ 本票の列名の一部）。地点は度分秒を続けた数字。
# 東京都以外の行（都道府県コード 01）と地点のない行も入れ、取込で除くことを確かめる。
TRAFFIC_YEARS = (2021, 2022, 2023, 2024, 2025)
TRAFFIC_COLUMNS = ["資料区分", "都道府県コード", "警察署等コード", "本票番号", "事故内容", "死者数", "負傷者数",
                   "市区町村コード", "発生日時　　年", "事故類型", "当事者種別（当事者A）", "当事者種別（当事者B）",
                   "地点　緯度（北緯）", "地点　経度（東経）"]


def _dms(value: float, degree_digits: int) -> str:
    deg = int(value)
    rest = (value - deg) * 60
    minutes = int(rest)
    millis = round((rest - minutes) * 60 * 1000)
    return f"{deg:0{degree_digits}d}{minutes:02d}{millis:05d}"


def _write_traffic(directory: Path, year: int, rnd: random.Random) -> Path:
    d = directory / f"npa_traffic_{year}"
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for city5, _, town, west, south in MUNICIPALITIES[:2]:
        for n in range(rnd.randint(40, 60)):
            # 区市町村の南西の1マスは事故なし（0件の例）
            i, j = rnd.choice([(i, j) for i in range(GRID) for j in range(GRID) if (i, j) != (0, 0)])
            lon = west + (j + rnd.uniform(0.1, 0.9)) * CELL
            lat = south + (i + rnd.uniform(0.1, 0.9)) * CELL
            kind = rnd.choice(["01", "21", "21", "41"])
            party_a = rnd.choice(["03", "04", "13", "51"])
            party_b = "61" if kind == "01" else rnd.choice(["03", "51", "52", "76"])
            fatal = "1" if rnd.random() < 0.05 else "2"
            rows.append(["1", "30", "001", f"{len(rows) + 1:04d}", fatal, "001" if fatal == "1" else "000", "001",
                         city5[2:], str(year), kind, party_a, party_b, _dms(lat, 2), _dms(lon, 3)])
    rows.append(["1", "30", "001", "9998", "2", "000", "001", "199", str(year), "21", "03", "03", "000000000", "0000000000"])
    rows.append(["1", "01", "001", "0001", "2", "000", "001", "101", str(year), "21", "03", "03",
                 _dms(35.67, 2), _dms(139.71, 3)])
    # 神奈川県警（45）が記録した、みほん市中区の事故（全国版の確認用）
    rows.append(["1", "45", "001", "0001", "2", "000", "001", "199", str(year), "01", "03", "61",
                 _dms(35.455, 2), _dms(139.605, 3)])
    path = d / f"honhyo_{year}.csv"
    with path.open("w", encoding="cp932", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(TRAFFIC_COLUMNS)
        wr.writerows(rows)
    return d


CRIME_YEARS = {2021: "R3", 2022: "R4", 2023: "R5", 2024: "R6", 2025: "R7"}
CRIME_COLUMNS = ["市区町丁", "総合計", "凶悪犯計", "粗暴犯計", "侵入窃盗計", "非侵入窃盗計", "その他計"]
FULLWIDTH = str.maketrans("0123456789", "０１２３４５６７８９")


def _write_crime(directory: Path, year: int, rnd: random.Random) -> Path:
    d = directory / f"keishicho_crime_{year}"
    d.mkdir(parents=True, exist_ok=True)
    rows, grand = [], [0] * 6

    def counts(n: int) -> list[int]:
        parts = [rnd.randint(0, max(0, n // 30)), rnd.randint(0, n // 8), rnd.randint(0, n // 10)]
        parts.append(rnd.randint(0, n - sum(parts)))
        parts.append(n - sum(parts))
        return [n] + parts

    for city5, city_name, town, west, south in MUNICIPALITIES:
        if city5 == "13499" and year == 2024:
            continue  # 認知件数0件の区市町村は行がない
        total = [0] * 6
        for i, (key, name, _) in enumerate(_cells(city5, town, west, south)):
            if i % 5 == 4:
                continue  # 0件の町丁目は行がない
            n = rnd.randint(1, 400) if i != 1 else 900   # 繁華街の例（件数が多い）
            c = counts(n)
            # 丁目の数字は全角（境界データの名称と表記が違う例）
            rows.append([f"{city_name}{name.translate(FULLWIDTH)}"] + c)
            total = [a + b for a, b in zip(total, c)]
        unknown = counts(rnd.randint(1, 5))
        rows.append([f"{city_name}以下不詳"] + unknown)
        stray = counts(3)
        rows.append([f"{city_name}{town}存在しない町"] + stray)   # 境界に対応しない名称
        total = [a + b + c for a, b, c in zip(total, unknown, stray)]
        if city5 == "13199" and year == 2024:
            total = [v + 7 for v in total]     # 町丁目の合計と計が合わない
        rows.append([f"{city_name}計"] + total)
        grand = [a + b for a, b in zip(grand, total)]
    rows += [["２３区計"] + grand, ["他県", 3, 0, 1, 0, 1, 1], ["合計"] + grand]
    path = d / f"{CRIME_YEARS[year]}.csv"
    with path.open("w", encoding="cp932", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(CRIME_COLUMNS)
        wr.writerows(rows)
    return path


def _base_values(rnd: random.Random) -> dict:
    """セルごとの2020年の人口・世帯・年齢の値。"""
    values = {}
    for city5, _, town, west, south in MUNICIPALITIES + OTHER_MUNICIPALITIES:
        cells = list(_cells(city5, town, west, south))
        small_key = cells[9][0]                              # 人口の少ない地域
        for key, _, _ in cells:
            pop = rnd.randint(30, 45) if key == small_key else rnd.randint(300, 9000)
            male = round(pop * rnd.uniform(0.46, 0.52))
            unknown = rnd.randint(0, max(1, pop // 50))
            known = pop - unknown
            child = round(known * rnd.uniform(0.06, 0.17))
            old = round(known * rnd.uniform(0.14, 0.33))
            values[key] = ([pop, male, pop - male, round(pop / rnd.uniform(1.6, 2.4))],
                           [pop, child, known - child - old, old])
    return values


def _write_year(directory: Path, year: str, keys: dict, base: dict,
                rnd: random.Random, pref: str, municipalities: list) -> dict[str, Path]:
    dirs = {"boundary": directory / keys["boundary"] / pref,
            "population": directory / keys["population"][0] / pref,
            "age": directory / keys["age"][0] / pref}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    w = shapefile.Writer(str(dirs["boundary"] / "fixture"),
                         shapeType=shapefile.POLYGON, encoding="cp932")
    for name, kind, size, dec in [("KEY_CODE", "C", 11, 0), ("PREF", "C", 2, 0),
                                  ("CITY", "C", 3, 0), ("S_AREA", "C", 6, 0),
                                  ("PREF_NAME", "C", 12, 0), ("CITY_NAME", "C", 30, 0),
                                  ("S_NAME", "C", 60, 0), ("HCODE", "N", 4, 0),
                                  ("AREA", "N", 16, 3), ("GST_NAME", "C", 30, 0)]:
        w.field(name, kind, size, dec)

    pop_rows, age_rows = [], []
    all_values = {}
    pref_name = PREF_NAMES[pref]
    for city5, city_name, town, west, south in municipalities:
        designated = city_name.split("市")[0] + "市" if "市" in city_name[:-1] and city_name.endswith("区") else ""
        # 実ファイルで区の CITY_NAME が区名だけでも市の名前を補えるか確かめるため、区名だけにする
        shp_city_name = city_name[len(designated):]
        totals = [0.0] * 4
        age_totals = [0.0] * 4
        cells = list(_cells(city5, town, west, south))
        if year != "2020":
            cells = [c for i, c in enumerate(cells) if i != NEW_CELL]
        hidden_key, merge_key = cells[5][0], cells[6][0]   # 秘匿と合算先
        values = {}
        for i, (key, name, ring) in enumerate(cells):
            pv, av = base[key]
            if year != "2020":
                f = rnd.uniform(0.85, 1.1)
                pv = [round(v * f) for v in pv]
                av = [round(v * f) for v in av]
                pv[2] = pv[0] - pv[1]
                av[2] = max(0, round(av[0] * 0.97) - av[1] - av[3])
            values[key] = (pv, av)
            all_values[key] = (pv, av)
            area = CELL * 91_000 * CELL * 111_000
            if year != "2020" and i == CHANGED_CELL:
                area *= 0.6
                x0, y0 = ring[0]
                ring = [(x0, y0), (x0, y0 + CELL * 0.6), (x0 + CELL, y0 + CELL * 0.6),
                        (x0 + CELL, y0), (x0, y0)]
            w.record(key, pref, city5[2:], key[5:], pref_name, shp_city_name, name, 8101, area, designated)
            w.poly([ring])
        # 水面調査区（取込時に除外される）
        x0, y0 = west - CELL / 2, south
        w.record(city5 + "999999", pref, city5[2:], "999999", pref_name, shp_city_name, "（水面）",
                 8154, 1000.0, designated)
        w.poly([[(x0, y0), (x0, y0 + CELL), (x0 + CELL / 2, y0 + CELL), (x0, y0)]])

        for key, (pv, av) in values.items():
            totals = [a + b for a, b in zip(totals, pv)]
            age_totals = [a + b for a, b in zip(age_totals, av)]
        merged_p = [a + b for a, b in zip(values[merge_key][0], values[hidden_key][0])]
        merged_a = [a + b for a, b in zip(values[merge_key][1], values[hidden_key][1])]

        # 実ファイルの秘匿処理: "2"=秘匿（HTKSAKI に合算先の6桁）、"1"=合算先（GASSAN に一覧）
        def head(key, hyosyo, name, flag="0", saki="", gassan=""):
            return [key, hyosyo, city_name, name, flag, saki, gassan]

        pop_rows.append(head(city5, "1", "") + [int(v) for v in totals])
        age_rows.append(head(city5, "1", "") + [int(v) for v in age_totals])
        for key, name, _ in cells:
            code = key[:9] if key.endswith("00") else key
            hyosyo = "3" if len(code) == 9 else "4"
            if key == hidden_key:
                pop_rows.append(head(code, hyosyo, name, "2", merge_key[5:]) + ["X"] * 4)
                age_rows.append(head(code, hyosyo, name, "2", merge_key[5:]) + ["X"] * 4)
            elif key == merge_key:
                pop_rows.append(head(code, hyosyo, name, "1", "", hidden_key[5:]) + [int(v) for v in merged_p])
                age_rows.append(head(code, hyosyo, name, "1", "", hidden_key[5:]) + [int(v) for v in merged_a])
            else:
                pv, av = values[key]
                av = [v if v else "-" for v in av]
                pop_rows.append(head(code, hyosyo, name) + pv)
                age_rows.append(head(code, hyosyo, name) + av)
    w.close()
    (dirs["boundary"] / "fixture.prj").write_text(
        'GEOGCS["JGD2011",DATUM["D_JGD_2011",SPHEROID["GRS_1980",6378137,298.257222101]],'
        'PRIMEM["Greenwich",0],UNIT["Degree",0.017453292519943295]]')

    _write_csv(dirs["population"] / keys["population"][1], HEAD_CODES + POP_CODES, POP_LABELS, pop_rows)
    _write_csv(dirs["age"] / keys["age"][1], HEAD_CODES + AGE_CODES, AGE_LABELS, age_rows)
    out = {f"{year}_{k}": v for k, v in dirs.items()}
    if "education" in keys:
        out[f"{year}_education"] = _write_education(directory, keys["education"], base, rnd)
    out.update(_write_households(directory, year, keys["households"], all_values, rnd, pref, municipalities))
    return out


def _household_values(households: float, rnd: random.Random) -> dict[str, list[float]]:
    """一般世帯の架空の内訳（表ごと）。"""
    h = round(households * 0.97)
    one = round(h * rnd.uniform(0.2, 0.65))
    rest = h - one
    sizes = [round(rest * x) for x in (0.4, 0.3, 0.2, 0.07)]
    six = rest - sum(sizes)
    persons = one + sum((i + 2) * v for i, v in enumerate(sizes)) + 6 * six
    kin = h - one - round(h * 0.02)
    nuclear = round(kin * 0.9)
    u6 = round(h * rnd.uniform(0.02, 0.1))
    housed = h - round(h * 0.03)
    own = round(housed * rnd.uniform(0.2, 0.7))
    main = housed - round(housed * 0.01)
    detached, row, other = round(main * rnd.uniform(0.1, 0.6)), round(main * 0.01), round(main * 0.005)
    apt = main - detached - row - other
    floors = [round(apt * x) for x in (0.25, 0.3, 0.25)]
    floors.append(apt - sum(floors) if rnd.random() > 0.15 else 0)   # 高層のない地域もある
    floors[0] += apt - sum(floors)
    workers = round(households * rnd.uniform(0.9, 1.3))
    status_unknown = round(workers * rnd.uniform(0, 0.15))
    self_emp, family = round(workers * rnd.uniform(0.05, 0.15)), round(workers * 0.02)
    occ_unknown = round(workers * rnd.uniform(0, 0.2))
    occ_shares = [rnd.uniform(0.01, 0.06), rnd.uniform(0.1, 0.3)] + [rnd.uniform(0.02, 0.2) for _ in range(9)]
    occ = [round((workers - occ_unknown) * x / sum(occ_shares)) for x in occ_shares]
    occ[2] += workers - occ_unknown - sum(occ)
    return {
        "industry_status": [workers, 0, workers - status_unknown - self_emp - family, self_emp, family],
        "occupation": [workers, *occ, occ_unknown],
        "household_size": [h, one, *sizes, persons, 0],
        "family_type": [h, kin, nuclear, round(nuclear * 0.35), round(nuclear * 0.45), kin - nuclear,
                        u6, u6 + round(h * rnd.uniform(0.05, 0.15)), round(h * rnd.uniform(0.15, 0.4))],
        "tenure": [housed, own, round((housed - own) * 0.8)],
        "building_type": [main, detached, row, apt, *floors, other],
    }


def _write_households(directory: Path, year: str, keys: dict, values: dict,
                      rnd: random.Random, pref: str, municipalities: list) -> dict[str, Path]:
    """values: 人口の表と同じ地域（地域コード → (人口, 年齢)）。秘匿・合算も人口の表と同じにする。"""
    tables = {t: HOUSEHOLD_TABLES[t] for t in keys}
    rows: dict[str, list[list]] = {t: [] for t in tables}
    for city5, city_name, town, west, south in municipalities:
        cells = [c for c in _cells(city5, town, west, south) if c[0] in values]
        hidden_key, merge_key = cells[5][0], cells[6][0]
        hv = {key: _household_values(values[key][0][3], rnd) for key, _, _ in cells}

        def fix(t: str, v: list[float]) -> list:
            v = [int(x) for x in v]
            if t == "household_size":   # 1世帯当たり人員は合計せず計算する
                v[-1] = round(v[-2] / v[0], 5) if v[0] else 0
            return v

        for t in tables:
            total = [sum(hv[k][t][i] for k in hv) for i in range(len(tables[t]))]
            rows[t].append([city5, "1", city_name, "", "0", "", ""] + fix(t, total))
            for key, name, _ in cells:
                code = key[:9] if key.endswith("00") else key
                hyosyo = "3" if len(code) == 9 else "4"
                if key == hidden_key:
                    rows[t].append([code, hyosyo, city_name, name, "2", merge_key[5:], ""]
                                   + ["X"] * len(tables[t]))
                elif key == merge_key:
                    merged = [a + b for a, b in zip(hv[merge_key][t], hv[hidden_key][t])]
                    rows[t].append([code, hyosyo, city_name, name, "1", "", hidden_key[5:]] + fix(t, merged))
                else:
                    rows[t].append([code, hyosyo, city_name, name, "0", "", ""]
                                   + [x if x else "-" for x in fix(t, hv[key][t])])
    out = {}
    for t, labels in tables.items():
        src, filename = keys[t]
        d = directory / src / pref
        d.mkdir(parents=True, exist_ok=True)
        stats_id = filename[3:10]
        if year == "2015":
            labels = [l if i == 0 else "　" + l for i, l in enumerate(labels)]
        _write_csv(d / filename, HEAD_CODES + [f"{stats_id}{i + 1:03d}" for i in range(len(labels))],
                   labels, rows[t])
        out[f"{year}_{t}"] = d
    return out


# 最終学歴（e-Stat「ファイル」の小地域集計CSV 第13表の形式。2020年のみ）
EDU_LABELS = ["総数", "卒業者", "（卒業者）小学校", "（卒業者）中学校", "（卒業者）高校・旧中",
              "（卒業者）短大・高専", "（卒業者）大学", "（卒業者）大学院", "（卒業者）不詳",
              "在学者", "未就学者", "在学か否かの別「不詳」"]
EDU_HEAD = ["男女", "市区町村コード", "町丁字コード", "地域階層レベル", "秘匿処理", "秘匿先情報",
            "合算地域", "都道府県名", "市区町村名", "大字・町名", "字・丁目名"]


def _education_values(pop: int, rnd: random.Random) -> list[int]:
    adults = round(pop * rnd.uniform(0.84, 0.92))
    students = round(adults * rnd.uniform(0.03, 0.08))
    unknown_status = rnd.randint(0, 3)
    grads = adults - students - unknown_status
    unknown = round(grads * rnd.uniform(0.05, 0.4))
    known = grads - unknown
    shares = [rnd.uniform(0.0, 0.01), rnd.uniform(0.03, 0.1), rnd.uniform(0.2, 0.4),
              rnd.uniform(0.1, 0.2), rnd.uniform(0.2, 0.45), rnd.uniform(0.02, 0.1)]
    parts = [round(known * x / sum(shares)) for x in shares]
    parts[2] += known - sum(parts)
    return [adults, grads, *parts, unknown, students, 0, unknown_status]


def _write_education(directory: Path, key_and_file: tuple[str, str], base: dict,
                     rnd: random.Random) -> Path:
    return _write_files_census(
        directory, key_and_file, "第13表　男女，在学か否かの別・最終卒業学校の種類別人口（15歳以上）－町丁・字等",
        "人口", EDU_LABELS, _education_values, base, rnd)


def _write_files_census(directory: Path, key_and_file: tuple[str, str], title: str, group: str,
                        labels: list[str], values_of, base: dict, rnd: random.Random,
                        layout: str = "2020") -> Path:
    """e-Stat「ファイル」の小地域集計CSVを架空の値で書く。秘匿・合算は人口の表と同じ。

    layout="2020": 男女の列があり、男女ごとに行が分かれる。
    layout="2015": 男女の列がなく、総数・男・女の値が横に並ぶ（列名が3回くり返す）。
    """
    d = directory / key_and_file[0] / "13"
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for city5, city_name, town, west, south in MUNICIPALITIES:
        cells = list(_cells(city5, town, west, south))
        values = {key: values_of(base[key][0][0], rnd) for key, _, _ in cells}
        hidden_key, merge_key = cells[5][0], cells[6][0]   # 人口・年齢の表と同じ秘匿・合算
        total = [sum(v[i] for v in values.values()) for i in range(len(labels))]
        merged = [a + b for a, b in zip(values[merge_key], values[hidden_key])]
        body = []
        body.append(["総数", city5, "-", "1", "", "", "", "東京都", city_name, "", ""] + total)
        for key, name, _ in cells:
            code = key[:9] if key.endswith("00") else key
            level = "2" if len(code) == 9 else "4"
            head = ["総数", city5, code[5:], level, "", "", "", "東京都", city_name, name, ""]
            if key == hidden_key:
                head[4:6] = ["秘匿地域", merge_key[5:]]
                body.append(head + ["X"] * len(labels))
            elif key == merge_key:
                head[4], head[6] = "合算地域あり", hidden_key[5:]
                body.append(head + merged)
            else:
                body.append(head + [v if v else "-" for v in values[key]])
        if layout == "2015":
            # 男女の列・地域階層レベルの列がなく、男・女の値（取込では使わない。0にする）が右に続く
            rows += [r[1:] + ["-"] * (2 * len(labels)) for r in body]
            continue
        rows += body
        # 男・女の行（取込では使わない）。値は総数と区別できるよう0にする
        rows += [["男"] + r[1:11] + ["-"] * len(labels) for r in body]
    head = EDU_HEAD if layout == "2020" else [
        "地域識別番号" if h == "地域階層レベル" else h for h in EDU_HEAD[1:]]
    values = labels if layout == "2020" else labels * 3
    path = d / key_and_file[1]
    with path.open("w", encoding="cp932", newline="") as f:
        wr = csv.writer(f)
        width = 1 + len(head) + len(values)
        era = "令和２年" if layout == "2020" else "平成27年"
        wr.writerow(["1", f"{era}国勢調査　小地域集計　（架空データ）"] + [""] * (width - 2))
        wr.writerow(["2", title] + [""] * (width - 2))
        wr.writerow(["3"] + [""] * len(head) + [group] * len(values))
        wr.writerow(["4"] + head + values)
        wr.writerows([str(i + 5)] + r for i, r in enumerate(rows))
    return d


# 利用交通手段（第17-1表）・在学学校（第14表）・5年前の常住地（第19表）。2020年のみ
COMMUTE_LABELS = ["総数", "徒歩のみ", "鉄道・電車", "乗合バス", "勤め先・学校のバス", "自家用車",
                  "ハイヤー・タクシー", "オートバイ", "自転車", "その他", "利用交通手段「不詳」"]
SCHOOL_LABELS = ["在学者", "（在学者）小学校", "（在学者）中学校", "（在学者）高校", "（在学者）短大・高専",
                 "（在学者）大学", "（在学者）大学院", "（在学者）不詳", "未就学者", "（未就学者）幼稚園",
                 "（未就学者）保育園・保育所", "（未就学者）認定こども園", "（未就学者）その他", "（未就学者）不詳"]
RESIDENCE_LABELS = ["常住者（現住地による人口）", "現住所", "移動あり（5年前の常住市区町村「不詳」を除く）",
                    "国内から", "自市町村内から", "自区内から", "自市内他区から", "県内他市町村から", "他県から",
                    "国外から", "5年前の常住市区町村「不詳」", "移動状況「不詳」"]


def _commute_values(pop: int, rnd: random.Random) -> list[int]:
    total = round(pop * rnd.uniform(0.45, 0.6))
    unknown = round(total * rnd.uniform(0.0, 0.1))
    known = total - unknown
    # 複数回答なので手段の合計は総数と一致しない
    shares = [(0.05, 0.3), (0.3, 0.7), (0.0, 0.1), (0.0, 0.01), (0.0, 0.3), (0.0, 0.01), (0.0, 0.02),
              (0.05, 0.3), (0.0, 0.02)]
    return [total, *[round(known * rnd.uniform(lo, hi)) for lo, hi in shares], unknown]


def _school_values(pop: int, rnd: random.Random) -> list[int]:
    parts = [round(pop * rnd.uniform(lo, hi)) for lo, hi in
             ((0.03, 0.06), (0.015, 0.03), (0.015, 0.03), (0.0, 0.005), (0.0, 0.06), (0.0, 0.01))]
    unknown = rnd.randint(0, 2)
    pre = [round(pop * rnd.uniform(0.0, 0.01)) for _ in range(4)]
    return [sum(parts) + unknown, *parts, unknown, sum(pre), *pre, 0]


def _residence_values(pop: int, rnd: random.Random) -> list[int]:
    same = round(pop * rnd.uniform(0.4, 0.7))
    unknown_status = round(pop * rnd.uniform(0.0, 0.2))
    unknown_city = rnd.randint(0, 3)
    moved = max(pop - same - unknown_status - unknown_city, 0)
    abroad = round(moved * 0.03)
    domestic = moved - abroad
    within = round(domestic * 0.4)
    prefecture = round(domestic * 0.3)
    return [same + moved + unknown_city + unknown_status, same, moved, domestic, within, within, 0,
            prefecture, domestic - within - prefecture, abroad, unknown_city, unknown_status]


# 居住期間（2020年 第18表・2015年 第13表）。2015年は列名に「（居住期間）」が付く
PERIOD_LABELS = ["総数", "出生時から", "1年未満", "1年以上5年未満", "5年以上10年未満", "10年以上20年未満",
                 "20年以上", "居住期間「不詳」"]


def _period_values(pop: int, rnd: random.Random) -> list[int]:
    unknown = round(pop * rnd.uniform(0.0, 0.3))
    known = pop - unknown
    parts = [rnd.uniform(0.02, 0.1), rnd.uniform(0.03, 0.2), rnd.uniform(0.1, 0.3), rnd.uniform(0.05, 0.2),
             rnd.uniform(0.05, 0.2), rnd.uniform(0.1, 0.4)]
    counts = [round(known * p / sum(parts)) for p in parts]
    counts[-1] += known - sum(counts)
    return [pop, *counts, unknown]


def _write_mobility(directory: Path, base: dict, rnd: random.Random) -> dict[str, Path]:
    return {
        "residence_period": _write_files_census(
            directory, ("census2020_small_area_residence_period", "h18_13.csv"),
            "第18表　男女，居住期間別人口－町丁・字等", "人口", PERIOD_LABELS, _period_values, base, rnd),
        "residence_period_2015": _write_files_census(
            directory, ("census2015_small_area_residence_period", "t13_13.csv"),
            "第13表　居住期間（6区分），男女別人口 －町丁・字等", "総数（男女別）",
            ["総数（居住期間）"] + PERIOD_LABELS[1:], _period_values, base, rnd, layout="2015"),
        "commute": _write_files_census(
            directory, ("census2020_small_area_commute", "h17-1_13.csv"),
            "第17-1表　男女，利用交通手段別通勤者・通学者数（15歳以上）－町丁・字等", "通勤者・通学者数",
            COMMUTE_LABELS, _commute_values, base, rnd),
        "school": _write_files_census(
            directory, ("census2020_small_area_school", "h14_13.csv"),
            "第14表　男女，在学学校・未就学の種類別人口－町丁・字等", "人口", SCHOOL_LABELS, _school_values, base, rnd),
        "residence_5y": _write_files_census(
            directory, ("census2020_small_area_residence_5y", "h19_13.csv"),
            "第19表　男女，5年前の常住地別人口－町丁・字等", "人口", RESIDENCE_LABELS, _residence_values, base, rnd),
    }


def _write_csv(path: Path, codes: list[str], labels: list[str], rows: list[list]) -> None:
    with path.open("w", encoding="cp932", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(codes)
        wr.writerow([""] * len(HEAD_CODES) + labels)
        wr.writerows(rows)


# 気象庁の平年値（アメダスの月・年別平年値と地点情報、どちらも zip の中の cp932 の CSV）。
# 「ためし」は日照・積雪の統計値なし（品質0、値の欄も0）で、統計期間が短い。「標本」は雪の降らない地点（正常値の0cm）。
# 「遠く」は地図の範囲外の地点で、取り込まない
WEATHER_STATIONS = [   # (観測所番号, 名前, カナ, 緯度, 経度, 高度)
    ("44901", "見本", "ﾐﾎﾝ", (35, 40.8), (139, 43.2), 25),
    ("44902", "ためし", "ﾀﾒｼ", (35, 41.4), (139, 39.6), 60),
    ("46901", "標本", "ﾋｮｳﾎﾝ", (35, 28.2), (139, 37.2), 10),
    ("14999", "遠く", "ﾄｵｸ", (43, 3.0), (142, 0.0), 100),
]
WEATHER_NORMALS = {   # 観測所番号 → 要素番号 → (資料年数, 開始年, 1〜12月と年の値。None は統計値なし)
    "44901": {"3500": (30, 1991, [1900, 1700, 1750, 1790, 1800, 1240, 1510, 1740, 1270, 1290, 1500, 1740, 19230]),
              "4000": (30, 1991, [600, 560, 1160, 1340, 1400, 1680, 1560, 1550, 2250, 2350, 960, 580, 15990]),
              "6200": (30, 1991, [3, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 6]),
              "6300": (30, 1991, [4, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 8])},
    "44902": {"3500": None, "6200": None, "6300": None,
              "4000": (18, 2003, [500, 520, 1100, 1300, 1450, 1700, 1650, 1600, 2300, 2400, 900, 520, 15940])},
    "46901": {"3500": (30, 1991, [1950, 1750, 1800, 1800, 1820, 1300, 1600, 1800, 1300, 1300, 1550, 1800, 19770]),
              "4000": (30, 1991, [700, 650, 1300, 1400, 1450, 1800, 1600, 1500, 2200, 2300, 1000, 650, 16550]),
              "6200": (30, 1991, [0] * 13), "6300": (30, 1991, [0] * 13)},
    "14999": {"4000": (30, 1991, [1000] * 12 + [12000])},
}


def _write_weather(directory: Path) -> dict[str, Path]:
    d = directory / "jma_normals_2020"
    d.mkdir(parents=True, exist_ok=True)
    head = "観測所番号,観測所名,カナ,ローマ字,緯度(度),緯度(分),経度(度),経度(分),高度,風速計の高さ,降水量,風,気温,日照時間,積雪の深さ"
    lines = [head] + [f"{n},{name}{'　' * (10 - len(name))},{kana:<15},{'X':<30},{lat[0]},{lat[1]:04.1f},"
                      f"{lon[0]},{lon[1]:04.1f},{alt:04d},010.0,1,1,1,1,1"
                      for n, name, kana, lat, lon, alt in WEATHER_STATIONS]
    index = d / "amedas_station_index.zip"
    with zipfile.ZipFile(index, "w") as z:
        z.writestr("amedas_station_index.csv", ("\r\n".join(lines) + "\r\n").encode("cp932"))
    monthly = d / "normal_amedas_monthly.zip"
    with zipfile.ZipFile(monthly, "w") as z:
        for n, elements in WEATHER_NORMALS.items():
            rows = []
            for el in ("0500", "3500", "4000", "6200", "6300"):
                v = elements.get(el)
                if v is None:
                    rows.append(f"21,{n},{el}, 0,   0,   0," + ",".join(["     0,0"] * 13))
                else:
                    years, start, vals = v
                    rows.append(f"21,{n},{el},{years:2d},{start},2020," + ",".join(f"{x:6d},8" for x in vals))
            z.writestr(f"monthly/area{n[:2]}/nml_amd_m_{n}.csv", ("\r\n".join(rows) + "\r\n").encode("cp932"))
    return {"weather_index": index, "weather_monthly": monthly}
