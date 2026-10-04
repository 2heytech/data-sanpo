import json
import re
import sqlite3

import pytest

from tdm import fixture
from tdm.cli import cmd_build
from tdm.config import Paths, load_censuses, load_indicators
from tdm.db import connect, init_schema, insert_observation, upsert_indicators
from tdm.ingest.estat_small_area import normalize_label, parse_cell
from tdm.regions import region_of


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    paths = Paths(tmp_path_factory.mktemp("data"))
    fixture.write(paths.raw)
    assert cmd_build(paths, "test", overrides=fixture.FIXTURE_SOURCE, prefs=["13", "14"]) == 0
    return paths


def load(paths, rel):
    """公開ファイルを読む。values/…/<区市町村5桁>.json は都道府県のファイルからその区市町村の行だけを返す。"""
    m = re.fullmatch(r"(values/.+)/(\d{5})\.json", rel)
    if m:
        data = load(paths, f"{m[1]}/{m[2][:2]}.json")
        return {**data, "rows": [r for r in data["rows"] if r["entity_id"][5:10] == m[2]]}
    return json.loads((paths.releases / "test" / rel).read_text(encoding="utf-8"))


def test_parse_cell_marks():
    assert parse_cell("1,234").value == 1234
    assert parse_cell("-").value == 0  # e-Stat の「-」は該当なし＝0
    assert parse_cell("X").status == "suppressed" and parse_cell("X").value is None
    assert parse_cell("").status == "missing"


def test_normalize_label():
    assert normalize_label("年齢「不詳」") == "年齢不詳"
    assert normalize_label("総数１５～６４歳") == normalize_label("総数15〜64歳") == "総数15~64歳"
    assert normalize_label(" 人口 総数 ") == "人口総数"


@pytest.mark.parametrize("code,region", [("13101", "区部"), ("13123", "区部"), ("13201", "多摩"),
                                         ("13308", "多摩"), ("13361", "島しょ"),
                                         ("13421", "島しょ")])
def test_region_of(code, region):
    assert region_of(code) == region


def test_missing_values_are_not_zero():
    conn = connect(":memory:")
    init_schema(conn)
    upsert_indicators(conn, load_indicators())
    conn.execute("INSERT INTO entities VALUES ('x', 'municipality', 'x', NULL, NULL, NULL, NULL, NULL)")
    conn.execute("""INSERT INTO sources (source_id, dataset_key, title, provider, license,
                    attribution, retrieved_at, file_sha256) VALUES ('s','s','s','s','s','s','t','h')""")
    with pytest.raises(sqlite3.IntegrityError):
        insert_observation(conn, entity_id="x", indicator_id="population_total",
                           definition_version="1", period_start="2020-10-01",
                           period_end="2020-10-01", period_kind="point", value=0.0,
                           status="suppressed", source_id="s")


def test_validate_finds_observations_without_references():
    # 観測値は番号で持ち外部キーの制約がないので、参照先がないことは検証で見つける
    from tdm.validate import validate
    conn = connect(":memory:")
    init_schema(conn)
    catalog = load_indicators()
    upsert_indicators(conn, catalog)
    insert_observation(conn, entity_id="nowhere", indicator_id="population_total",
                       definition_version="9", period_start="2020-10-01", period_end="2020-10-01",
                       period_kind="point", value=1.0, status="observed", source_id="unknown")
    errors = validate(conn, catalog).errors
    assert "外部キー違反: obs.entity_k = nowhere" in errors
    assert "外部キー違反: obs.source_k = unknown" in errors
    assert any("指標の定義がない観測値 population_total 9" in e for e in errors)


def test_manifest_lists_every_file_with_hash(built):
    manifest = load(built, "manifest.json")
    paths = {f["path"] for f in manifest["files"]}
    on_disk = {p.relative_to(built.releases / "test").as_posix()
               for p in (built.releases / "test").rglob("*") if p.is_file()} - {"manifest.json"}
    assert paths == on_disk
    assert all(len(f["sha256"]) == 64 for f in manifest["files"])


def test_secret_rows_point_to_merge_target(built):
    rows = {r["entity_id"]: r for r in
            load(built, "values/population_total/2020-10-01/13199.json")["rows"]}
    secret = [r for r in rows.values() if r["status"] == "suppressed"]
    assert len(secret) == 1 and "13199002003" in secret[0]["note"]
    assert "近隣地域（1地域）" in rows["area-13199002003"]["note"]


def test_suppressed_and_withheld_rows_are_kept(built):
    rows = load(built, "values/aged_65_plus_share/2020-10-01/13199.json")["rows"]
    statuses = {r["status"] for r in rows}
    assert {"derived", "suppressed", "withheld"} <= statuses
    for r in rows:
        if r["status"] != "derived":
            assert r["value"] is None and "numerator" not in r


def test_small_area_counts_add_up_to_municipality(built):
    munis = {r["entity_id"]: r["value"] for r in
             load(built, "values/population_total/2020-10-01/municipalities.json")["rows"]}
    for muni_id, total in munis.items():
        rows = load(built, f"values/population_total/2020-10-01/{muni_id[5:]}.json")["rows"]
        assert sum(r["value"] or 0 for r in rows) == total


def test_nine_digit_town_codes_match_boundaries(built):
    rows = load(built, "values/population_total/2020-10-01/13199.json")["rows"]
    assert any(r["entity_id"] == "area-13199090000" and r["value"] for r in rows)


def test_water_polygons_are_excluded(built):
    gj = load(built, "boundaries/census2020/13199.geojson")
    assert len(gj["features"]) == fixture.GRID ** 2
    assert all("999999" not in f["properties"]["id"] for f in gj["features"])


def test_density_uses_boundary_area(built):
    rows = load(built, "values/population_density/2020-10-01/13199.json")["rows"]
    r = next(r for r in rows if r["status"] == "derived")
    assert r["value"] == pytest.approx(r["numerator"] / r["denominator"], rel=1e-3)


def test_small_area_values_are_split_by_prefecture(built):
    base = built.releases / "test" / "values/population_total/2020-10-01"
    assert sorted(p.name for p in base.iterdir()) == ["13.json", "14.json", "legend.json", "municipalities.json", "prefectures.json"]
    rows = load(built, "values/population_total/2020-10-01/14.json")["rows"]
    assert rows and all(r["entity_id"].startswith("area-14199") for r in rows)


def test_prefectures_and_designated_city_wards(built):
    areas = load(built, "areas.json")
    prefs = {p["code"]: p for p in areas["prefectures"]}
    assert prefs["13"]["name"] == "東京都" and prefs["14"]["name"] == "神奈川県"
    assert prefs["13"]["municipality_count"] == 3
    munis = {m["id"]: m for m in areas["municipalities"]}
    # 境界の CITY_NAME が区名だけでも、政令指定都市の名前を補う
    assert munis["muni-14199"]["name"] == "みほん市中区"
    assert munis["muni-14199"]["region"] == "みほん市" and munis["muni-14199"]["prefecture"] == "14"
    nation = load(built, "boundaries/census2020/municipalities.geojson")
    assert {f["properties"]["id"] for f in nation["features"]} == set(munis)
    fine = load(built, "boundaries/census2020/municipalities/14.geojson")
    assert [f["properties"]["id"] for f in fine["features"]] == ["muni-14199"]


def test_search_index_is_split_by_prefecture(built):
    index = load(built, "search-index.json")
    assert {e[3] for e in index["entries"]} == {"prefecture", "municipality"}
    assert ["muni-14199", "みほん市中区", "神奈川県 みほん市", "municipality"] in index["entries"]
    assert ["muni-13199", "サンプル区", "東京都 区部", "municipality"] in index["entries"]
    towns = load(built, "search-index/14.json")["entries"]
    assert towns and all(e[0].startswith("area-14199") and e[2] == "みほん市中区" for e in towns)


def test_tokyo_only_indicators_list_their_prefectures(built):
    inds = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    assert inds["population_total"]["prefectures"] == ["13", "14"]
    assert inds["crime_total"]["prefectures"] == ["13"]
    assert inds["university_graduate_share"]["prefectures"] == ["13"]


def test_neighbors_and_regions(built):
    munis = {m["id"]: m for m in load(built, "areas.json")["municipalities"]}
    assert munis["muni-13199"]["neighbors"] == ["muni-13299"]
    assert munis["muni-13499"]["region"] == "島しょ"
    assert munis["muni-13499"]["neighbors"] == []


def test_release_is_never_overwritten(built):
    conn = connect(built.db)
    from tdm.export import export_release
    with pytest.raises(FileExistsError):
        export_release(conn, load_indicators(), built.releases, "test", load_censuses())


def test_manifest_has_size_report(built):
    size = load(built, "manifest.json")["size"]
    assert size["errors"] == [] and size["warnings"] == []
    assert 0 < size["initial_load_gzip_bytes"] < size["total_gzip_bytes"]
    assert size["largest_area_load"]["municipality_code"] in {"13199", "13299", "13499"}


def test_size_report_flags_oversized_files():
    from tdm.export import size_report
    files = [{"path": "boundaries/v/13101.geojson", "bytes": 30 * 1024 * 1024,
              "gzip_bytes": 4 * 1024 * 1024}]
    rep = size_report(files, "v", None)
    assert rep["errors"] and rep["warnings"]


def test_fetch_rejects_html_and_extracts_zip(tmp_path):
    import io
    import zipfile
    from tdm.fetch import FetchError, fetch_source
    cfg = {"url": "https://example.invalid/page", "download_url": "https://example.invalid/d?x=1"}
    with pytest.raises(FetchError):
        fetch_source("k", cfg, tmp_path / "a", downloader=lambda u: b"<!DOCTYPE html><html>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("sub/data.txt", "x")
    files = fetch_source("k", cfg, tmp_path / "b", downloader=lambda u: buf.getvalue())
    assert [f.name for f in files] == ["data.txt"]
    assert (tmp_path / "b" / "_fetch.json").exists()
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../evil.txt", "x")
    with pytest.raises(FetchError):
        fetch_source("k", cfg, tmp_path / "c", downloader=lambda u: bad.getvalue())


def test_past_census_is_overlaid_on_latest_boundaries(built):
    catalog = load(built, "indicators.json")
    pop = next(i for i in catalog["indicators"] if i["id"] == "population_total")
    assert [p["period"] for p in pop["periods"]] == ["2010-10-01", "2015-10-01", "2020-10-01", "2025-10-01"]
    assert pop["default_period"] == "2020-10-01"
    cells = list(fixture._cells("13199", "見本町", 139.70, 35.66))
    changed = "area-" + cells[fixture.CHANGED_CELL][0]
    new = "area-" + cells[fixture.NEW_CELL][0]
    for year in ("2010", "2015"):
        rows = {r["entity_id"]: r for r in load(built, f"values/population_total/{year}-10-01/13199.json")["rows"]}
        # 面積が変わった地域は過去の値を出さず、理由を添える
        assert rows[changed]["value"] is None and rows[changed]["status"] == "not_applicable"
        assert f"{year}年から境界が変わった" in rows[changed]["note"]
        # 2020年に新設された地域には過去の行がない
        assert new not in rows
        # それ以外は値がある
        assert rows["area-" + cells[0][0]]["value"] is not None
        # 過去の地図に使う境界は出力しない（最新の境界だけ）
        assert not (built.releases / "test" / "boundaries" / f"census{year}").exists()


def test_legend_breaks_are_shared_across_periods(built):
    a = load(built, "values/aged_65_plus_share/2010-10-01/legend.json")
    b = load(built, "values/aged_65_plus_share/2020-10-01/legend.json")
    assert a["levels"]["small_area"]["breaks"] == b["levels"]["small_area"]["breaks"]
    assert a["pooled_periods"] == 3
    # 市区町村は都道府県ごとにも区切る（全時点をまとめて決めるので時点で変わらない）
    by_pref = a["levels"]["municipality"]["by_prefecture"]
    assert set(by_pref) == {"13", "14"}
    assert by_pref == b["levels"]["municipality"]["by_prefecture"]
    assert "by_prefecture" not in a["levels"]["small_area"]


def test_density_uses_area_of_the_same_census(built):
    cells = list(fixture._cells("13199", "見本町", 139.70, 35.66))
    key = "area-" + cells[0][0]
    for period in ("2010-10-01", "2015-10-01", "2020-10-01"):
        pop = {r["entity_id"]: r for r in load(built, f"values/population_total/{period}/13199.json")["rows"]}
        den = {r["entity_id"]: r for r in load(built, f"values/population_density/{period}/13199.json")["rows"]}
        assert den[key]["numerator"] == pop[key]["value"]


def test_population_change_rate_uses_previous_census(built):
    catalog = load(built, "indicators.json")
    ind = next(i for i in catalog["indicators"] if i["id"] == "population_change_rate")
    # 最も古い時点は前回がないので時点に含めない
    assert [p["period"] for p in ind["periods"]] == ["2015-10-01", "2020-10-01", "2025-10-01"]   # 2025年は速報
    cells = list(fixture._cells("13199", "見本町", 139.70, 35.66))
    key = "area-" + cells[0][0]
    for prev, cur in (("2010-10-01", "2015-10-01"), ("2015-10-01", "2020-10-01")):
        pop_prev = {r["entity_id"]: r for r in load(built, f"values/population_total/{prev}/13199.json")["rows"]}
        pop_cur = {r["entity_id"]: r for r in load(built, f"values/population_total/{cur}/13199.json")["rows"]}
        rate = {r["entity_id"]: r for r in load(built, f"values/population_change_rate/{cur}/13199.json")["rows"]}
        # 率は分子（増減）・分母（前回の人口）から計算する
        assert rate[key]["denominator"] == pop_prev[key]["value"]
        assert rate[key]["numerator"] == pop_cur[key]["value"] - pop_prev[key]["value"]
        expected = (pop_cur[key]["value"] - pop_prev[key]["value"]) / pop_prev[key]["value"] * 100
        assert abs(rate[key]["value"] - expected) < 0.01
        # 境界が変わった地域は比べない
        changed = rate["area-" + cells[fixture.CHANGED_CELL][0]]
        assert changed["value"] is None and changed["status"] == "not_applicable"
        # 2020年に新設された地域は前回がないので行がない
        assert "area-" + cells[fixture.NEW_CELL][0] not in rate
    munis = {r["entity_id"]: r for r in load(built, "values/population_change_rate/2020-10-01/municipalities.json")["rows"]}
    assert munis["muni-13199"]["value"] is not None
    # 凡例は0（増減なし）を境に区切る
    legend = load(built, "values/population_change_rate/2020-10-01/legend.json")
    assert 0 in legend["levels"]["municipality"]["breaks"] or 0.0 in legend["levels"]["small_area"]["breaks"]


def test_municipality_outline_has_no_holes(built):
    gj = load(built, "boundaries/census2020/municipalities.geojson")
    for f in gj["features"]:
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        assert all(len(p) == 1 for p in polys), f["properties"]["id"]
        # 隣り合う町丁・字等は1つの形にまとまる（内側に線が出ない）
        assert g["type"] == "Polygon", f["properties"]["id"]


def test_persons_per_household_is_population_over_households(built):
    catalog = load(built, "indicators.json")
    ind = next(i for i in catalog["indicators"] if i["id"] == "persons_per_household")
    assert ind["fraction_units"] == ["人", "世帯"]
    for period in ("2010-10-01", "2020-10-01"):
        pop = {r["entity_id"]: r for r in load(built, f"values/population_total/{period}/municipalities.json")["rows"]}
        hh = {r["entity_id"]: r for r in load(built, f"values/households_total/{period}/municipalities.json")["rows"]}
        pph = {r["entity_id"]: r for r in load(built, f"values/persons_per_household/{period}/municipalities.json")["rows"]}
        row = pph["muni-13199"]
        assert row["numerator"] == pop["muni-13199"]["value"]
        assert row["denominator"] == hh["muni-13199"]["value"]
        assert abs(row["value"] - row["numerator"] / row["denominator"]) < 0.001
    # 秘匿された地域は値を出さない（0 にしない）
    rows = load(built, "values/persons_per_household/2020-10-01/13199.json")["rows"]
    assert any(r["status"] == "suppressed" and r["value"] is None for r in rows)


def test_files_csv_is_read_as_gis_table(built):
    from tdm.ingest.estat_small_area import read_files_table
    path = next((built.raw / "census2020_small_area_education" / "13").glob("*.csv"))
    table = read_files_table(path)
    keys = [r["KEY_CODE"] for r in table.rows]
    assert "13199" in keys and len(keys) == len(set(keys))  # 「総数」の行だけ（男・女の行は使わない）
    assert any(len(k) == 9 for k in keys)  # 丁目のない町は4桁の町丁字コード → 9桁
    secret = next(r for r in table.rows if r["HTKSYORI"] == "2")
    assert secret["HTKSAKI"] and secret["卒業者"] == "X"
    assert any(r["HTKSYORI"] == "1" and r["GASSAN"] for r in table.rows)


def test_university_graduate_share_excludes_unknown(built):
    catalog = load(built, "indicators.json")
    ind = next(i for i in catalog["indicators"] if i["id"] == "university_graduate_share")
    assert [p["period"] for p in ind["periods"]] == ["2020-10-01"]  # 2020年のみ
    from tdm.ingest.estat_small_area import read_files_table
    path = next((built.raw / "census2020_small_area_education" / "13").glob("*.csv"))
    src = next(r for r in read_files_table(path).rows if r["KEY_CODE"] == "13199")
    known = sum(int(src[c]) for c in ["（卒業者）小学校", "（卒業者）中学校", "（卒業者）高校・旧中",
                                      "（卒業者）短大・高専", "（卒業者）大学", "（卒業者）大学院"])
    assert known == int(src["卒業者"]) - int(src["（卒業者）不詳"])
    row = {r["entity_id"]: r for r in load(
        built, "values/university_graduate_share/2020-10-01/municipalities.json")["rows"]}["muni-13199"]
    assert row["numerator"] == int(src["（卒業者）大学"]) + int(src["（卒業者）大学院"])
    assert row["denominator"] == known
    unknown = {r["entity_id"]: r for r in load(
        built, "values/education_unknown_share/2020-10-01/municipalities.json")["rows"]}["muni-13199"]
    assert unknown["denominator"] == int(src["卒業者"])
    rows = load(built, "values/university_graduate_share/2020-10-01/13199.json")["rows"]
    assert any(r["status"] == "suppressed" and r["value"] is None for r in rows)


def test_household_indicators_for_three_censuses(built):
    catalog = load(built, "indicators.json")
    by = {i["id"]: i for i in catalog["indicators"]}
    for ind in ["single_person_household_share", "households_with_children_share", "owner_occupied_share",
                "private_rented_share", "high_rise_household_share"]:
        assert by[ind]["category"] == "暮らし方"
        assert [p["period"] for p in by[ind]["periods"]] == ["2010-10-01", "2015-10-01", "2020-10-01"]
    from tdm.ingest.estat_small_area import read_table
    path = next((built.raw / "census2015_small_area_household_size" / "13").glob("*.txt"))
    src = next(r for r in read_table(path).rows if r["KEY_CODE"] == "13199")
    row = {r["entity_id"]: r for r in load(
        built, "values/single_person_household_share/2015-10-01/municipalities.json")["rows"]}["muni-13199"]
    # 2015年の列名の先頭の全角空白は読み込み時に除く
    assert row["numerator"] == int(src["世帯人員１人"])
    assert row["denominator"] == int(src["一般世帯数（世帯人員６人以上含む）"])
    rows = load(built, "values/high_rise_household_share/2020-10-01/13199.json")["rows"]
    assert any(r["status"] == "suppressed" and r["value"] is None for r in rows)
    assert any(r["status"] == "withheld" for r in rows)   # 主世帯が50未満


def test_work_indicators_exclude_unknown(built):
    catalog = load(built, "indicators.json")
    by = {i["id"]: i for i in catalog["indicators"]}
    for ind in ["self_employed_share", "professional_share", "manager_share"]:
        assert by[ind]["category"] == "働き方"
        assert [p["period"] for p in by[ind]["periods"]] == ["2015-10-01", "2020-10-01"]
    from tdm.ingest.estat_small_area import read_table
    path = next((built.raw / "census2020_small_area_occupation" / "13").glob("*.txt"))
    src = next(r for r in read_table(path).rows if r["KEY_CODE"] == "13199")
    row = {r["entity_id"]: r for r in load(
        built, "values/professional_share/2020-10-01/municipalities.json")["rows"]}["muni-13199"]
    assert row["numerator"] == int(src["Ｂ専門的・技術的職業従事者"])
    assert row["denominator"] == int(src["総数"]) - int(src["Ｌ分類不能の職業"])   # 分類不能を除く
    path = next((built.raw / "census2015_small_area_industry_status" / "13").glob("*.txt"))
    src = next(r for r in read_table(path).rows if r["KEY_CODE"] == "13199")
    row = {r["entity_id"]: r for r in load(
        built, "values/self_employed_share/2015-10-01/municipalities.json")["rows"]}["muni-13199"]
    known = sum(int(src[c]) for c in ["雇用者（役員を含む）", "自営業主（家庭内職者を含む）", "家族従業者"])
    assert row["denominator"] == known < int(src["総数"])   # 従業上の地位「不詳」を除く


def test_foreign_residents(built):
    catalog = load(built, "indicators.json")
    by = {i["id"]: i for i in catalog["indicators"]}
    share = by["foreign_resident_share"]
    assert share["category"] == "外国人住民" and [p["period"] for p in share["periods"]] == ["2020-10-01"]
    from tdm.ingest.estat_small_area import read_files_table
    path = next((built.raw / "census2020_small_area_foreign" / "13").glob("*.csv"))
    table = read_files_table(path)
    assert "外国人人口" in table.labels and "世帯数" in table.labels   # 列名「-」は1行上の分類名
    src = next(r for r in table.rows if r["KEY_CODE"] == "13199")
    row = {r["entity_id"]: r for r in load(
        built, "values/foreign_resident_share/2020-10-01/municipalities.json")["rows"]}["muni-13199"]
    assert row["numerator"] == int(src["外国人人口"]) and row["denominator"] == int(src["総数"])
    rows = load(built, "values/foreign_resident_share/2020-10-01/13199.json")["rows"]
    assert any(r["status"] == "suppressed" for r in rows)
    # 住民基本台帳の外国人住民（区市町村・国籍別、各年1月1日）
    total = by["foreign_residents"]
    assert total["family"] == "foreign" and total["facets"] == {"type": "総数", "basis": "人数"}
    assert [p["period"] for p in total["periods"]] == ["2025-01-01", "2026-01-01"]
    assert by["foreign_residents_korea"]["facets"]["type"] == "韓国"
    munis = {r["entity_id"]: r for r in load(
        built, "values/foreign_residents/2026-01-01/municipalities.json")["rows"]}
    china = {r["entity_id"]: r for r in load(
        built, "values/foreign_residents_china/2026-01-01/municipalities.json")["rows"]}
    assert munis["muni-13199"]["value"] > china["muni-13199"]["value"] > 0
    # 島しょ（支庁単位でしか公表されない町村）は値なし。0 にしない
    assert munis.get("muni-13499") is None or munis["muni-13499"]["value"] is None


def test_daytime_night_ratio_uses_same_year_population(built):
    catalog = load(built, "indicators.json")
    ind = next(i for i in catalog["indicators"] if i["id"] == "daytime_night_ratio")
    assert [p["period"] for p in ind["periods"]] == ["2010-10-01", "2015-10-01", "2020-10-01"]
    for period in ["2010-10-01", "2015-10-01"]:
        ratio = {r["entity_id"]: r for r in load(
            built, f"values/daytime_night_ratio/{period}/municipalities.json")["rows"]}["muni-13199"]
        day = {r["entity_id"]: r for r in load(
            built, f"values/daytime_population/{period}/municipalities.json")["rows"]}["muni-13199"]
        pop = {r["entity_id"]: r for r in load(
            built, f"values/population_total/{period}/municipalities.json")["rows"]}["muni-13199"]
        assert ratio["numerator"] == day["value"] and ratio["denominator"] == pop["value"]
        assert ratio["value"] > 100   # 架空のサンプル区は昼間に人が集まる
    # 区部（13100）などの行は取り込まない
    rows = load(built, "values/daytime_population/2010-10-01/municipalities.json")["rows"]
    assert {r["entity_id"] for r in rows} <= {"muni-13199", "muni-13299", "muni-13499"}


def test_crime_town_names_are_normalized():
    from tdm.ingest.keishicho_crime import normalize_name
    assert normalize_name("飯田橋１丁目") == normalize_name("飯田橋一丁目") == "飯田橋1丁目"
    assert normalize_name("霞ヶ関") == normalize_name("霞が関")
    assert normalize_name("西新宿十二丁目") == "西新宿12丁目"


def test_crime_counts_by_municipality_and_town(built):
    def rows(period, chunk):
        return {r["entity_id"]: r for r in load(built, f"values/crime_total/{period}/{chunk}.json")["rows"]}
    munis = rows("2025-01-01", "municipalities")
    towns = rows("2025-01-01", "13199")
    # 区市町村の値は「計」の行（以下不詳・対応しない町丁目を含むので町丁目の合計より大きい）
    assert munis["muni-13199"]["value"] > sum(r["value"] for r in towns.values())
    # 表にない町丁目は、合計が一致する年は0件（注記つき）
    zero = [r for r in towns.values() if r["value"] == 0]
    assert zero and all("掲載がない" in r["note"] for r in zero)
    # 合計が一致しない年（2024年のサンプル区）は表にない町丁目を値なしにする（0 にしない）
    towns_2024 = rows("2024-01-01", "13199")
    missing = [r for r in towns_2024.values() if r["status"] == "missing"]
    assert missing and all(r["value"] is None for r in missing)
    # 行のない区市町村はその年0件
    assert rows("2024-01-01", "municipalities")["muni-13499"]["value"] == 0


def test_crime_rates_use_2020_population_and_daytime_population(built):
    catalog = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    # 5年分（2021〜2025年）と5年合計
    assert [p["levels"] for p in catalog["crime_total_per_100_daytime"]["periods"]] == [["municipality", "prefecture"]] * 6
    assert catalog["crime_total"]["compare_with"] == ["crime_total_per_100_residents", "crime_total_per_100_daytime"]
    pop = {r["entity_id"]: r for r in load(built, "values/population_total/2020-10-01/municipalities.json")["rows"]}
    day = {r["entity_id"]: r for r in load(built, "values/daytime_population/2020-10-01/municipalities.json")["rows"]}
    crime = {r["entity_id"]: r for r in load(built, "values/crime_total/2025-01-01/municipalities.json")["rows"]}
    res = {r["entity_id"]: r for r in load(built, "values/crime_total_per_100_residents/2025-01-01/municipalities.json")["rows"]}
    dt = {r["entity_id"]: r for r in load(built, "values/crime_total_per_100_daytime/2025-01-01/municipalities.json")["rows"]}
    m = "muni-13199"
    assert res[m]["numerator"] == crime[m]["value"] and res[m]["denominator"] == pop[m]["value"]
    assert dt[m]["denominator"] == day[m]["value"]
    assert abs(dt[m]["value"] - crime[m]["value"] / day[m]["value"] * 100) < 0.01


def test_crime_family_facets_and_five_year_total(built):
    catalog = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    crime = [i for i in catalog.values() if i["family"] == "crime"]
    assert len(crime) == 18   # 6種別 ×（件数・住民100人当たり・昼間人口100人当たり）
    assert catalog["crime_violent_per_100_residents"]["facets"] == {"type": "凶悪犯", "basis": "住民100人あたり"}
    periods = catalog["crime_violent"]["periods"]
    assert [p["period"] for p in periods][-1] == "2021-2025" and periods[-1]["aggregate"]
    assert periods[-1]["label"] == "2021〜2025年の合計"
    assert catalog["crime_violent"]["default_period"] == "2025-01-01"   # 既定は最新の年
    def muni(ind, period):
        return {r["entity_id"]: r for r in load(built, f"values/{ind}/{period}/municipalities.json")["rows"]}
    m = "muni-13299"
    total = muni("crime_total", "2021-2025")[m]["value"]
    assert total == sum(muni("crime_total", f"{y}-01-01")[m]["value"] for y in range(2021, 2026))
    rate = muni("crime_total_per_100_residents", "2021-2025")[m]
    assert rate["numerator"] == total
    # 年が欠けた町丁目（2024年のサンプル区の表にない町丁目）は5年合計も値なし
    towns = {r["entity_id"]: r for r in load(built, "values/crime_total/2021-2025/13199.json")["rows"]}
    towns_2024 = {r["entity_id"]: r for r in load(built, "values/crime_total/2024-01-01/13199.json")["rows"]}
    gap = [k for k, r in towns_2024.items() if r["status"] == "missing"]
    assert gap and all(towns[k]["value"] is None for k in gap)


def test_zero_is_left_blank_and_breaks_are_round_numbers(built):
    legend = load(built, "values/crime_violent/2025-01-01/legend.json")
    assert legend["zero_blank"] and legend["method"] == "nice"
    for level in legend["levels"].values():
        assert all(b > 0 for b in level["breaks"])   # 0 は区切りに使わない（色を塗らない）
    agg = load(built, "values/crime_total/2021-2025/legend.json")["levels"]["municipality"]["breaks"]
    annual = load(built, "values/crime_total/2025-01-01/legend.json")["levels"]["municipality"]["breaks"]
    assert agg != annual   # 5年合計は年ごとと別の区切り
    dens = load(built, "values/population_density/2020-10-01/legend.json")["levels"]["small_area"]["breaks"]
    assert 0 < len(dens) <= 11


def test_nice_breaks():
    from tdm.breaks import diverging_breaks, nice_breaks
    # 均等に散らばる値は切りのよい等間隔
    assert nice_breaks([float(v) for v in range(0, 121)], 12, 0) == [10.0 * i for i in range(1, 12)]
    # 偏った値は分位点の近くの切りのよい数値（0.1 や 5 の倍数など）
    skew = [1.0] * 50 + [2.0] * 30 + [3.0] * 10 + [10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0, 5000.0, 9000.0]
    b = nice_breaks(skew, 12, 0)
    assert b == sorted(set(b)) and len(b) == 11 and b[0] == 2.0
    assert all(float(f"{x:.1g}") == x for x in b)   # どれも上1桁で切れる数値
    # 飛び抜けた地域があっても、ほかの地域は均等な刻みで分ける
    assert nice_breaks([v / 10 for v in range(10, 33)] * 3 + [50.0], 12, 1) == [1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0]
    shares = [0.123, 0.187, 0.21, 0.26, 0.33, 0.41, 0.48, 0.52, 0.66, 0.71, 0.9, 1.5, 2.6, 8.0] * 10
    for x in nice_breaks(shares, 12, 2):
        assert round(x * 20) == x * 20 or round(x * 100) == x * 100
    d = diverging_breaks([-30.0, -10.0, -5.0, -1.0, 1.0, 2.0, 4.0, 8.0, 15.0, 40.0] * 5, 12, 1)
    assert 0.0 in d and d == sorted(d) and len(d) <= 11


def test_stations_are_per_operator_and_keep_duplicates_apart(built):
    st = load(built, "places/station_passengers.json")
    assert st["periods"][0]["label"] == "2011年度" and st["periods"][-1]["label"] == "2024年度"
    by = {(s["name"], s["operator"]): s for s in st["stations"] if s["lines"] != ["遠方線"]}
    assert ("県外", "架空鉄道") not in by                      # 都外の駅は含めない
    assert {s["municipality_id"] for s in st["stations"]} <= {"muni-13199", "muni-13299"}
    jr = by[("見本中央", "東日本旅客鉄道")]
    assert jr["lines"] == ["見本線", "試験線"] and jr["status"][-1] == "observed"
    # 他路線駅に記載された駅は 0 にせず、含めて公表されている旨を残す
    toei = by[("見本中央", "東京都")]
    assert toei["values"] == [None] * 14 and set(toei["status"]) == {"not_applicable"}
    assert "東京地下鉄 2号線試験線" in toei["notes"]["0"]
    far = next(s for s in st["stations"] if s["lines"] == ["遠方線"])   # 別のグループでも同じ事業者の同名駅を探す
    assert far["status"][0] == "not_applicable" and "（見本線）" in far["notes"]["0"]
    # 同じ事業者で路線別に値があれば合計し、内訳を残す。事業者をまたいでは合計しない
    metro = by[("見本中央", "東京地下鉄")]
    assert metro["values"][-1] == sum(v[-1] for v in metro["by_line"].values())
    assert "路線別の値（1号線見本線・2号線試験線）の合計" in metro["notes"]["13"]
    keio = by[("ためし", "京王電鉄")]
    assert keio["values"][:3] == [None] * 3 and keio["status"][:3] == ["missing"] * 3
    assert set(by[("試験公園", "架空鉄道")]["status"]) == {"suppressed"}
    new = by[("見本新町", "東日本旅客鉄道")]
    assert new["status"][:4] == [None] * 4 and new["values"][4] is not None   # 開業前は行なし
    # 駅の指標は塗り分けの指標一覧には出さない
    assert "station_passengers" not in {i["id"] for i in load(built, "indicators.json")["indicators"]}


def test_schools_are_located_from_addresses(built):
    sc = load(built, "places/school_enrollment.json")
    assert [p["label"] for p in sc["periods"]][-1] == "2025年5月1日現在" and len(sc["periods"]) == 5
    by = {s["id"]: s for s in sc["schools"]}
    # 通信制の課程は学校の点にしない（同じ学校番号の中学校の値に混ぜない）
    assert by["school-990110"]["name"] == "見本中学校"
    assert sum(1 for s in sc["schools"] if "通信制" in s["name"]) == 0
    # 住所の丁目・街区から位置を求める。街区がなければ町丁目の代表点
    assert by["school-990010"]["precision"] == "街区" and by["school-990010"]["coord"] == [139.705, 35.665]
    assert by["school-990020"]["precision"] == "町丁目"
    # 見つからない住所は区市町村の中心などに置かず、位置なし（区市町村は設置者から）
    lost = by["school-990030"]
    assert lost["coord"] is None and lost["municipality_id"] == "muni-13299"
    # 都立の学校は住所の先頭の区市町村
    assert by["school-990120"]["municipality_id"] == "muni-13299"
    # 学年別の合計が総数。「-」は該当なし（0人）
    k = by["school-990210"]
    assert k["values"][-1] == sum(v[-1] for v in k["by_grade"].values()) and k["by_grade"]["2年"][-1] == 0
    # 掲載のない年度は値なし（0 にしない）
    assert k["values"][:2] == [None, None] and by["school-990040"]["values"][3:] == [None, None]
    # 街区レベルにない大字は大字・町丁目レベルで補う。大字を書かない住所は大字が1つの町村だけ
    assert by["school-990050"]["precision"] == "町丁目" and by["school-990050"]["coord"] == [139.68, 35.7]
    assert by["school-990060"]["coord"] == [139.37, 34.71]
    assert any(s.startswith("mlit_isj_2025@") for s in sc["source_ids"])
    assert any(s.startswith("mlit_isj_oaza_2025@") for s in sc["source_ids"])
    assert "school_enrollment" not in {i["id"] for i in load(built, "indicators.json")["indicators"]}


def test_isj_locate_address_forms():
    from tdm.ingest.isj_geocode import Gazetteer, kanji_number
    g = Gazetteer()
    g.blocks = {("千代田区", "麹町二丁目"): {"8": (139.74, 35.68, 1)},
                ("千代田区", "三番町"): {"16": (139.741, 35.69, 1)},
                ("八王子市", "子安町二丁目"): {"18": (139.33, 35.65, 1)}}
    assert kanji_number(2) == "二" and kanji_number(10) == "十" and kanji_number(23) == "二十三"
    assert g.locate("千代田区", "麹町2-8").precision == "街区"
    assert g.locate("千代田区", "千代田区麹町２－８").town == "麹町二丁目"      # 区市町村名・全角数字
    assert g.locate("千代田区", "三番町16").town == "三番町"                  # 丁目のない町
    assert g.locate("八王子市", "子安町2-18-1").precision == "街区"           # 地番の枝番
    assert g.locate("千代田区", "麹町2-99").precision == "町丁目"
    assert g.locate("千代田区", "麹町２ー８ー１").town == "麹町二丁目"        # 長音符の区切り
    assert g.locate("千代田区", "麹町2丁目8番1号 麹町ビル3階").precision == "街区"   # 丁目を数字で書く・建物名
    assert g.locate("千代田区", "存在しない町1-1") is None


def test_isj_oaza_level_drops_county_name(tmp_path):
    from tdm.ingest.isj_geocode import Gazetteer
    p = tmp_path / "oaza.csv"
    p.write_text("市区町村名,大字町丁目名,緯度,経度\n西多摩郡瑞穂町,箱根ケ崎,35.77,139.35\n"
                 "西多摩郡檜原村,檜原村,35.72,139.15\n", encoding="cp932")
    g = Gazetteer.read(None, p)
    r = g.locate("瑞穂町", "箱根ヶ崎2287")        # 郡名つきの名前・ヶ/ケ のゆれ
    assert r and r.level == "oaza" and (r.lon, r.lat) == (139.35, 35.77)
    assert g.locate("檜原村", "檜原村600").town == "檜原村"   # 大字が1つの村


def test_commute_school_and_residence(built):
    from tdm.ingest.estat_small_area import parse_cell, read_files_table
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}

    def source_row(key, code):
        table = read_files_table(next((built.raw / key / "13").glob("*.csv")))
        return next(r for r in table.rows if r["KEY_CODE"] == code)

    def muni(indicator, code="muni-13199"):
        rows = load(built, f"values/{indicator}/2020-10-01/municipalities.json")["rows"]
        return {r["entity_id"]: r for r in rows}[code]

    # 交通手段: 種別で切り替え、分母は総数から「不詳」を引く（複数回答なので内訳の合計ではない）
    rail = by["commute_rail_share"]
    assert rail["family"] == "commute" and rail["facets"] == {"type": "鉄道・電車", "basis": "割合"}
    assert [p["period"] for p in rail["periods"]] == ["2020-10-01"]
    src = source_row("census2020_small_area_commute", "13199")
    row = muni("commute_rail_share")
    assert row["numerator"] == int(src["鉄道・電車"])
    assert row["denominator"] == int(src["総数"]) - int(src["利用交通手段「不詳」"])
    rows = load(built, "values/commute_rail_share/2020-10-01/13199.json")["rows"]
    assert any(r["status"] == "suppressed" for r in rows)
    # 大学生・大学院生: 大学＋大学院の合計 ÷ 同じ年の人口
    src = source_row("census2020_small_area_school", "13199")
    students = muni("university_students")
    assert students["value"] == int(src["（在学者）大学"]) + int(src["（在学者）大学院"])
    share = muni("university_student_share")
    assert share["numerator"] == students["value"]
    assert share["denominator"] == muni("population_total")["value"]
    # 5年前と同じ場所: 移動状況「不詳」は分母から除く
    src = source_row("census2020_small_area_residence_5y", "13199")
    row = muni("same_residence_5y_share")
    known = [parse_cell(src[c]).value for c in
             ("現住所", "移動あり（5年前の常住市区町村「不詳」を除く）", "5年前の常住市区町村「不詳」")]
    assert row["numerator"] == known[0] and row["denominator"] == sum(known)
    assert row["denominator"] < int(src["常住者（現住地による人口）"]) or int(src["移動状況「不詳」"]) == 0


def test_residence_period(built):
    from tdm.ingest.estat_small_area import read_files_table
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    short = by["residence_under1y_share"]
    assert short["family"] == "residence_period" and short["facets"] == {"type": "1年未満", "basis": "割合"}
    assert [p["period"] for p in short["periods"]] == ["2015-10-01", "2020-10-01"]
    for year, key, total in (("2020", "census2020_small_area_residence_period", "総数"),
                             ("2015", "census2015_small_area_residence_period", "総数（居住期間）")):
        table = read_files_table(next((built.raw / key / "13").glob("*.csv")))
        src = next(r for r in table.rows if r["KEY_CODE"] == "13199")
        # 2015年は総数・男・女の列名がくり返す。最初（総数）の列を使う
        assert int(src[total]) > 0 and (year == "2020" or src[f"{total}#2"] == "-")
        rows = {r["entity_id"]: r for r in load(
            built, f"values/residence_under5y_share/{year}-10-01/municipalities.json")["rows"]}
        row = rows["muni-13199"]
        assert row["numerator"] == int(src["1年未満"]) + int(src["1年以上5年未満"])
        assert row["denominator"] == int(src[total]) - int(src["居住期間「不詳」"])


def test_census2025_preliminary(built):
    import csv as _csv
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    pop = by["population_total"]
    p2025 = next(p for p in pop["periods"] if p["period"] == "2025-10-01")
    assert p2025["levels"] == ["municipality", "prefecture"]  # 速報は区市町村（と都道府県）だけ
    assert pop["default_period"] == "2020-10-01"        # 最初は町丁・字等まである最新の時点を表示
    with (built.raw / "tokyo_census2025_preliminary" / "kt25sv0300.csv").open(encoding="utf-8-sig") as f:
        src = {r["地域コード"]: r for r in _csv.DictReader(f) if r["地域階層"] == "4"}

    def muni(indicator, period="2025-10-01"):
        rows = load(built, f"values/{indicator}/{period}/municipalities.json")["rows"]
        return {r["entity_id"]: r for r in rows}["muni-13199"]

    people = int(src["13199"]["人口／総数／令和7（2025）年（人）"])
    homes = int(src["13199"]["世帯／総数／令和7（2025）年（世帯）"])
    assert muni("population_total")["value"] == people and muni("households_total")["value"] == homes
    pph = muni("persons_per_household")
    assert pph["numerator"] == people and pph["denominator"] == homes   # 公表の1世帯当たり人員ではなく分子・分母から
    change = muni("population_change_rate")
    before = muni("population_total", "2020-10-01")["value"]
    assert abs(change["value"] - (people - before) / before * 100) < 0.001   # 公開値は小数3桁
    assert muni("population_density")["value"] > 0


def test_resident_tax(built):
    from tdm.ingest.soumu_tax import read_rows
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    tax = by["resident_tax_per_taxpayer"]
    assert [p["period"] for p in tax["periods"]] == ["2024-fiscal", "2025-fiscal"] or \
        [p["label"] for p in tax["periods"]] == ["2024年度", "2025年度"]
    assert all(p["levels"] == ["municipality", "prefecture"] for p in tax["periods"])
    src = read_rows(next((built.raw / "soumu_tax_2025").glob("*.xlsx")))
    assert "01100" not in src                  # 東京都の行だけ
    city, pref = src["13199"]["市町村民税"], src["13199"]["道府県民税"]
    pid = tax["periods"][-1]["period"]
    row = {r["entity_id"]: r for r in load(built, f"values/resident_tax_per_taxpayer/{pid}/municipalities.json")["rows"]}["muni-13199"]
    levy = city["所得割額（税額控除・減免後）"] + pref["所得割額（税額控除・減免後）"]
    assert row["numerator"] == levy and row["denominator"] == city["所得割の納税義務者数"]
    assert abs(row["value"] - levy * 1000 / city["所得割の納税義務者数"]) < 1     # 千円 → 円
    inc = {r["entity_id"]: r for r in load(built, f"values/taxable_income_per_taxpayer/{pid}/municipalities.json")["rows"]}["muni-13199"]
    assert inc["numerator"] == city["課税対象所得"]
    # 神奈川県も取り込むが、政令指定都市（市全体の行）の値を区に割り振らない
    assert "14190" in read_rows(next((built.raw / "soumu_tax_2025").glob("*.xlsx")), ["13", "14"])
    rows = {r["entity_id"]: r for r in load(built, f"values/resident_tax_per_taxpayer/{pid}/municipalities.json")["rows"]}
    assert rows.get("muni-14199", {}).get("value") is None


def test_childcare(built):
    from tdm.ingest.tokyo_childcare import read_table
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    waiting = by["waiting_children"]
    # 2026年の発表から2026年、2023年の発表から2023年と前年の2022年（見本では2024・2025年の発表はない）
    assert [p["period"] for p in waiting["periods"]] == ["2022-04-01", "2023-04-01", "2026-04-01"]
    t26 = read_table(next((built.raw / "tokyo_childcare_2026").glob("*.xlsx")))
    t23 = read_table(next((built.raw / "tokyo_childcare_2023").glob("*.xlsx")))
    assert sorted(t26) == [2025, 2026] and sorted(t23) == [2022, 2023]   # 日付のセルと「令和5年」の文字列
    name = fixture.MUNICIPALITIES[0][1]

    def muni(indicator, period):
        rows = load(built, f"values/{indicator}/{period}/municipalities.json")["rows"]
        return {r["entity_id"]: r for r in rows}["muni-13199"]

    assert muni("waiting_children", "2026-04-01")["value"] == t26[2026][name]["waiting"]
    assert muni("waiting_children", "2022-04-01")["value"] == t23[2022][name]["waiting"]
    rate = muni("childcare_usage_rate", "2023-04-01")
    assert rate["numerator"] == t23[2023][name]["users"] and rate["denominator"] == t23[2023][name]["children"]


def test_street_trees(built):
    from tdm.ingest.tokyo_street_trees import read_trees
    trees = read_trees(built.raw / "tokyo_street_trees_ku" / "tokyo_gairoju.csv")
    assert len(trees) == 300                    # 位置のない木は数えない
    areas = {r["entity_id"]: r for r in load(built, "values/street_trees/2026-04-01/13199.json")["rows"]}
    munis = {r["entity_id"]: r for r in load(built, "values/street_trees/2026-04-01/municipalities.json")["rows"]}
    assert munis["muni-13199"]["value"] == 300 and sum(r["value"] for r in areas.values()) == 300
    assert any(r["value"] == 0 and r["status"] == "observed" for r in areas.values())   # 都道のない町丁目は0本
    assert munis["muni-13299"]["value"] == 0
    assert munis["muni-13499"]["value"] is None and munis["muni-13499"]["status"] == "missing"   # 島しょは対象外
    ginkgo = {r["entity_id"]: r for r in load(built, "values/street_trees_ginkgo/2026-04-01/municipalities.json")["rows"]}
    assert ginkgo["muni-13199"]["value"] == sum(1 for t in trees if t[0] == "イチョウ")
    cherry = {r["entity_id"]: r for r in load(built, "values/street_trees_cherry/2026-04-01/municipalities.json")["rows"]}
    assert cherry["muni-13199"]["value"] == sum(1 for t in trees if t[0] == "ソメイヨシノ")
    assert munis["muni-13199"]["note"].startswith("最も多い樹種: ")
    kinds = {r["entity_id"]: r for r in load(built, "values/street_tree_species/2026-04-01/municipalities.json")["rows"]}
    assert kinds["muni-13199"]["value"] == len({t[0] for t in trees})


def test_traffic_accidents(built):
    from tdm.ingest.npa_traffic import dms_to_degrees, read_accidents
    assert abs(dms_to_degrees("354115168", 2) - (35 + 41 / 60 + 15.168 / 3600)) < 1e-9
    assert dms_to_degrees("0000000000", 3) is None
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    total = by["traffic_accidents"]
    assert total["family"] == "traffic" and total["facets"] == {"type": "総数", "basis": "件数"}
    periods = [p["period"] for p in total["periods"]]
    assert periods == ["2021-01-01", "2022-01-01", "2023-01-01", "2024-01-01", "2025-01-01", "2021-2025"]
    rows = read_accidents(next((built.raw / "npa_traffic_2025").glob("*.csv")))
    assert all(r["都道府県コード"] == "30" for r in rows)   # 他の道府県の行は除く（既定は東京都だけ）
    assert {r["都道府県コード"] for r in read_accidents(
        next((built.raw / "npa_traffic_2025").glob("*.csv")), prefs=["13", "14"])} == {"30", "45"}
    located = [r for r in rows if r["地点　緯度（北緯）"].strip("0")]
    munis = {r["entity_id"]: r for r in load(
        built, "values/traffic_accidents/2025-01-01/municipalities.json")["rows"]}
    assert munis["muni-13199"]["value"] + munis["muni-13299"]["value"] == len(located)
    areas = {r["entity_id"]: r for r in load(built, "values/traffic_accidents/2025-01-01/13199.json")["rows"]}
    assert sum(r["value"] for r in areas.values()) == munis["muni-13199"]["value"]
    assert any(r["value"] == 0 and r["status"] == "observed" for r in areas.values())   # 事故のない町丁目は0件
    assert munis["muni-14199"]["value"] == 1   # 神奈川県警の事故は神奈川県の地域に数える
    ped = {r["entity_id"]: r for r in load(
        built, "values/traffic_accidents_pedestrian/2025-01-01/municipalities.json")["rows"]}
    assert ped["muni-13199"]["value"] == sum(
        1 for r in located if r["市区町村コード"] == "199" and r["事故類型"] == "01")
    five = {r["entity_id"]: r for r in load(
        built, "values/traffic_accidents/2021-2025/municipalities.json")["rows"]}
    yearly = [{r["entity_id"]: r for r in load(
        built, f"values/traffic_accidents/{y}-01-01/municipalities.json")["rows"]} for y in range(2021, 2026)]
    assert five["muni-13199"]["value"] == sum(y["muni-13199"]["value"] for y in yearly)
    # 住民100人当たり・昼間人口100人当たり（犯罪と同じ組み立て、#46）
    traffic = [i for i in by.values() if i.get("family") == "traffic"]
    assert len(traffic) == 12   # 4種別 ×（件数・住民100人当たり・昼間人口100人当たり）
    assert by["traffic_accidents_bicycle_per_100_daytime"]["facets"] == {"type": "自転車が関係", "basis": "昼間人口100人あたり"}
    pop = {r["entity_id"]: r for r in load(built, "values/population_total/2020-10-01/municipalities.json")["rows"]}
    res = {r["entity_id"]: r for r in load(
        built, "values/traffic_accidents_per_100_residents/2021-2025/municipalities.json")["rows"]}
    m = "muni-13199"
    assert res[m]["numerator"] == five[m]["value"] and res[m]["denominator"] == pop[m]["value"]
    assert abs(res[m]["value"] - five[m]["value"] / pop[m]["value"] * 100) < 0.01
    day = load(built, "values/traffic_accidents_per_100_daytime/2025-01-01/municipalities.json")["rows"]
    assert day and all(r["entity_id"].startswith("muni-") for r in day)


def test_fetch_keep_rows():
    from tdm.fetch import keep_rows
    data = "都道府県コード,値\n30,1\n01,2\n30,3\n".encode("cp932")
    assert keep_rows(data, "都道府県コード", "30").decode("cp932") == "都道府県コード,値\n30,1\n30,3\n"


def test_fetch_keeps_xlsx_as_one_file(tmp_path):
    import io, zipfile
    from tdm.fetch import fetch_source
    from tdm.xlsx import read_sheet, write_sheet
    book = tmp_path / "src.xlsx"
    write_sheet(book, [["団体コード", "値"], ["131016", 1]])
    files = fetch_source("t", {"download_url": "https://example.jp/x/J51-25-b.xlsx"}, tmp_path / "out",
                         downloader=lambda url: book.read_bytes())
    assert [f.name for f in files] == ["J51-25-b.xlsx"] and read_sheet(files[0])[1] == ["131016", 1.0]
    # 普通の ZIP は展開する
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.csv", "x\n")
    files = fetch_source("z", {"download_url": "https://example.jp/a.zip"}, tmp_path / "zip",
                         downloader=lambda url: buf.getvalue())
    assert [f.name for f in files] == ["a.csv"]


def test_xlsx_ignores_furigana(tmp_path):
    import zipfile
    from tdm.xlsx import read_sheet, write_sheet
    plain = tmp_path / "a.xlsx"
    write_sheet(plain, [["x", 1]])
    assert read_sheet(plain) == [["x", 1.0]]
    # 日本語の Excel は共有文字列にふりがな（rPh）を一緒に保存する。読みの文字は含めない
    m = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    shared = (f'<sst xmlns="{m}"><si><t>団体コード</t><rPh sb="0" eb="2"><t>ダンタイ</t></rPh></si>'
              f'<si><r><t>表</t></r><r><rPr><b/></rPr><t>側</t></r></si></sst>')
    sheet = (f'<worksheet xmlns="{m}"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c>'
             f'<c r="C1" t="s"><v>1</v></c></row></sheetData></worksheet>')
    book = tmp_path / "b.xlsx"
    with zipfile.ZipFile(plain) as zi, zipfile.ZipFile(book, "w") as zo:
        for name in zi.namelist():
            zo.writestr(name, sheet if name.endswith("sheet1.xml") else zi.read(name))
        zo.writestr("xl/sharedStrings.xml", shared)
    assert read_sheet(book) == [["団体コード", None, "表側"]]


def test_land_prices(built):
    lp = load(built, "places/land_price.json")
    labels = [p["period"] for p in lp["periods"]]
    assert labels[0] == "1983-01-01" and labels[-1] == "2026-01-01" and len(labels) == 44
    by = {p["name"]: p for p in lp["points"]}
    # 番号は市区町村名・用途・連番（住宅地は用途の数字なし）
    assert set(by) == {"サンプル-1", "サンプル-2", "サンプル5-1", "ためし-1", "ためし9-1"}
    assert by["サンプル5-1"]["use_label"] == "商業地" and by["ためし9-1"]["use_label"] == "工業地"
    assert by["サンプル-1"]["municipality_id"] == "muni-13199" and by["サンプル-1"]["coord"] == [139.705, 35.665]
    # 標準地でなかった年（元データの 0）は値なし。0円にしない
    late = by["サンプル-2"]["values"]
    assert late[:2008 - 1983] == [None] * (2008 - 1983) and all(v and v > 0 for v in late[2008 - 1983:])
    assert all(v is None or v > 0 for p in lp["points"] for v in p["values"])
    assert by["サンプル-1"]["residential_address"] is None   # 「_」は記載なし
    assert any(s.startswith("mlit_l01_2026@") for s in lp["source_ids"])
    assert "land_price" not in {i["id"] for i in load(built, "indicators.json")["indicators"]}


def test_estat_file_ids_are_found_by_prefecture_and_table(tmp_path):
    from tdm.fetch import resolve_file_ids
    pages = {
        "": '<li><a href="/stat-search/files?tclass2=000001159850">北海道</a></li>'
            '<li><a href="/stat-search/files?tclass2=000001159886"><span>東京都</span></a></li>',
        "000001159850": '<div>第2表 男女別人口</div><a href="/file-download?statInfId=000032100001&fileKind=1">CSV</a>'
                        '<div>第13表 最終卒業学校</div><a href="/file-download?statInfId=000032100013&fileKind=0">Excel</a>'
                        '<a href="/file-download?statInfId=000032100013&fileKind=1">CSV</a>',
    }

    def downloader(url):
        import re as _re
        m = _re.search(r"tclass2=(\d+)", url)
        page = int(_re.search(r"page=(\d+)", url).group(1))
        return (pages.get(m.group(1) if m else "", "") if page == 1 else "").encode()

    cfg = {"estat_lookup": {"tstat": "1", "tclass1": "2", "table": "第13表"}, "known_ids": {"13": "000032210414"}}
    ids = resolve_file_ids("k", cfg, tmp_path, ["01", "13", "14"], downloader)
    assert ids == {"01": "000032100013", "13": "000032210414"}
    assert json.loads((tmp_path / "_ids.json").read_text(encoding="utf-8")) == ids


def test_estat_file_ids_are_found_in_flat_list(tmp_path):
    """都道府県の分類のリンクがない一覧（全都道府県のファイルが1つの表に並ぶ）からも探せる。"""
    from tdm.fetch import resolve_file_ids
    html = ('<tr><td>第13表 最終卒業学校</td><td>神奈川県</td>'
            '<td><a href="/file-download?statInfId=000032100113&fileKind=1">CSV</a></td></tr>'
            '<tr><td>第2表 男女別人口</td><td>大阪府</td>'
            '<td><a href="/file-download?statInfId=000032100202&fileKind=1">CSV</a></td></tr>'
            '<tr><td>第13表 最終卒業学校</td><td>大阪府</td>'
            '<td><a href="/file-download?statInfId=000032100213&fileKind=0">Excel</a>'
            '<a href="/file-download?statInfId=000032100213&fileKind=1">CSV</a></td></tr>')

    def downloader(url):
        return (html if "page=1&" in url or url.endswith("page=1") else "").encode()

    cfg = {"estat_lookup": {"tstat": "9", "tclass1": "8", "table": "第13表"}}
    ids = resolve_file_ids("k", cfg, tmp_path, ["14", "27"], downloader)
    assert ids == {"14": "000032100113", "27": "000032100213"}


def test_prefecture_values_are_summed_from_municipalities(built):
    """都道府県の値は区市町村の分子・分母（人数などは値）の合計から出し、欠けた区市町村があれば値なし。"""
    areas = load(built, "areas.json")
    assert all(len(p["center"]) == 2 for p in areas["prefectures"])
    gj = load(built, f"boundaries/{areas['boundary_version']}/prefectures.geojson")
    assert sorted(f["properties"]["id"] for f in gj["features"]) == ["pref-13", "pref-14"]
    munis = load(built, "values/population_total/2020-10-01/municipalities.json")["rows"]
    prefs = {r["entity_id"]: r for r in load(built, "values/population_total/2020-10-01/prefectures.json")["rows"]}
    tokyo = [r for r in munis if r["entity_id"].startswith("muni-13")]
    if all(r["value"] is not None for r in tokyo):
        assert prefs["pref-13"]["value"] == round(sum(r["value"] for r in tokyo), 2)
    else:
        assert prefs["pref-13"]["value"] is None
    share = load(built, "values/aged_65_plus_share/2020-10-01/municipalities.json")["rows"]
    pshare = {r["entity_id"]: r for r in load(built, "values/aged_65_plus_share/2020-10-01/prefectures.json")["rows"]}
    k = [r for r in share if r["entity_id"].startswith("muni-14")]
    assert pshare["pref-14"]["numerator"] == round(sum(r["numerator"] for r in k), 4)
    assert abs(pshare["pref-14"]["value"] - pshare["pref-14"]["numerator"] / pshare["pref-14"]["denominator"] * 100) < 0.01
    # 住民税は区に値のない政令指定都市も含めて、出典の行から都道府県の値を出す
    tax_periods = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}["resident_tax_per_taxpayer"]["periods"]
    tax = {r["entity_id"]: r for r in load(built, f"values/resident_tax_per_taxpayer/{tax_periods[-1]['period']}/prefectures.json")["rows"]}
    assert tax["pref-14"]["value"] is not None


def test_estat_file_ids_are_guessed_and_verified(tmp_path):
    """一覧から探せないときは、分かっている都道府県の番号から推測し、中身（表番号・地域コード）で確かめる。"""
    from tdm.fetch import fetch_source

    def csv_for(table, pref):
        rows = ["1,令和２年国勢調査　小地域集計", f"2,{table}　男女，…－町丁・字等", "3,,",
                "4,市区町村コード,町丁字コード,秘匿処理,秘匿先情報,合算地域,市区町村名,大字・町名,字・丁目名,人口",
                f"5,{pref}101,-,,,,a,,,10"]
        return "\n".join(rows).encode("cp932")

    # 東京都（13）= 100013 から都道府県の順。27 は1つずれていて、推測した番号は別の表（確かめて除く）
    files = {"000000100013": csv_for("第13表", "13"), "000000100014": csv_for("第13表", "14"),
             "000000100027": csv_for("第14表", "27"), "000000100028": csv_for("第13表", "27")}

    def downloader(url):
        import re as _re
        m = _re.search(r"statInfId=(\d+)", url)
        if m:
            if m.group(1) not in files:
                raise OSError("404")
            return files[m.group(1)]
        return b"<html></html>"  # 一覧のページは中身がない

    cfg = {"per_prefecture": True, "estat_lookup": {"tstat": "1", "tclass1": "2", "table": "第13表"},
           "known_ids": {"13": "000000100013"},
           "download_url": "https://example/file-download?statInfId={id}&fileKind=1",
           "download_filename": "h13_{pref}.csv", "files": ["*.csv"]}
    got = fetch_source("k", cfg, tmp_path, downloader, ["13", "14", "27"])
    ids = json.loads((tmp_path / "_ids.json").read_text(encoding="utf-8"))
    assert ids == {"13": "000000100013", "14": "000000100014", "27": "000000100028"}
    assert sorted(p.parent.name for p in got) == ["13", "14", "27"]


def test_estat_file_ids_follow_the_step_between_prefectures(tmp_path):
    """都道府県ごとに表がまとまる並び方（間隔が1でない）でも、広く探して間隔を求める。"""
    from tdm.fetch import fetch_source

    def csv_for(pref):
        return "\n".join(["1,令和２年国勢調査", "2,第2表　男女別人口－町丁・字等", "3,,",
                          "4,市区町村コード,町丁字コード,人口", f"5,{pref}101,-,10"]).encode("cp932")

    files = {f"{100013 + 7 * (p - 13):012d}": csv_for(f"{p:02d}") for p in (13, 14, 27)}

    def downloader(url):
        import re as _re
        m = _re.search(r"statInfId=(\d+)", url)
        if m and m.group(1) in files:
            return files[m.group(1)]
        if m:
            raise OSError("404")
        return b"<html></html>"

    cfg = {"per_prefecture": True, "estat_lookup": {"tstat": "1", "tclass1": "2", "table": "第2表"},
           "known_ids": {"13": "000000100013"}, "files": ["*.csv"],
           "download_url": "https://example/file-download?statInfId={id}&fileKind=1"}
    fetch_source("k", cfg, tmp_path, downloader, ["13", "14", "27", "28"])
    ids = json.loads((tmp_path / "_ids.json").read_text(encoding="utf-8"))
    assert ids == {"13": "000000100013", "14": "000000100020", "27": "000000100111"}
    assert json.loads((tmp_path / "_missing.json").read_text(encoding="utf-8")) == ["28"]

def test_nurseries(built):
    nc = load(built, "places/nursery_capacity.json")
    assert [p["period"] for p in nc["periods"]] == ["2025-10-01"]
    by = {p["name"]: p for p in nc["points"]}
    assert set(by) == {"見本ほいくえん", "見本第二保育園", "ためし保育園", "かりの保育所"}
    # 全角の住所・街区から位置を求める。街区がなければ町丁目の代表点
    assert by["見本ほいくえん"]["precision"] == "街区" and by["見本ほいくえん"]["coord"] == [139.705, 35.665]
    assert by["見本ほいくえん"]["values"] == [87] and by["見本ほいくえん"]["municipality_id"] == "muni-13199"
    assert by["見本第二保育園"]["precision"] == "町丁目"
    # 見つからない住所は位置なし（区市町村はコードから）
    assert by["ためし保育園"]["coord"] is None and by["ためし保育園"]["municipality_id"] == "muni-13299"
    # 島名から書く住所も区市町村名から後ろで位置を求める
    assert by["かりの保育所"]["coord"] == [139.37, 34.71]
    assert any(s.startswith("tokyo_nurseries_2025@") for s in nc["source_ids"])
    assert "nursery_capacity" not in {i["id"] for i in load(built, "indicators.json")["indicators"]}


def test_furusato(built):
    from tdm.ingest.soumu_furusato import fiscal_year
    assert fiscal_year("令和元年度") == 2019 and fiscal_year("令和７年度") == 2025 and fiscal_year("平成20年度") == 2008
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    amount = by["furusato_amount"]
    assert [p["period"] for p in amount["periods"]] == ["2023-04-01", "2024-04-01", "2025-04-01"]
    assert amount["periods"][-1]["label"] == "2025年度" and amount["family"] == "furusato"

    def muni(ind, period):
        return {r["entity_id"]: r for r in load(built, f"values/{ind}/{period}/municipalities.json")["rows"]}
    v = muni("furusato_amount", "2025-04-01")
    assert set(v) == {"muni-13199", "muni-13299", "muni-13499"}   # 都道府県の行・政令指定都市の市の行は区市町村に出さない
    assert muni("furusato_amount", "2023-04-01")["muni-13499"]["value"] is None   # 空欄は 0 にしない
    per = muni("furusato_amount_per_capita", "2025-04-01")["muni-13199"]
    assert abs(per["value"] - per["numerator"] / per["denominator"] * 1e6) < 1
    assert abs(per["numerator"] - v["muni-13199"]["value"]) < 0.01
    assert "furusato_amount_per_capita" in by and "furusato_count" in by

    # 都道府県の値は、都道府県（庁）自身と県内の全市区町村（政令指定都市は市全体の行）の合計
    def pref(ind, period):
        return {r["entity_id"]: r for r in load(built, f"values/{ind}/{period}/prefectures.json")["rows"]}
    p = pref("furusato_amount", "2025-04-01")
    assert abs(p["pref-13"]["value"] - (1.8 + sum(r["value"] for r in v.values()))) < 0.01
    assert abs(p["pref-14"]["value"] - (0.4 + 22.0)) < 0.01   # 政令指定都市の区に値はないが県の合計には入る
    assert pref("furusato_amount", "2023-04-01")["pref-13"]["value"] is None   # 空欄の市町村があれば値なし
    pc = pref("furusato_amount_per_capita", "2025-04-01")["pref-13"]
    pop = sum(r["value"] for r in load(built, "values/population_total/2020-10-01/municipalities.json")["rows"]
              if r["entity_id"].startswith("muni-13"))
    assert abs(pc["denominator"] - pop) < 0.01 and abs(pc["numerator"] - p["pref-13"]["value"]) < 0.01


def test_jhs_progress(built):
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    assert by["jhs_progress_private"]["periods"][0]["label"] == "2025年3月卒業"

    def muni(ind):
        return {r["entity_id"]: r for r in load(built, f"values/{ind}/2025-03-31/municipalities.json")["rows"]}
    pri, pub = muni("jhs_progress_private"), muni("jhs_progress_public")
    assert pri["muni-13199"]["value"] == 35.0 and pri["muni-13199"]["numerator"] == 70
    assert pub["muni-13199"]["value"] == 60.0 and muni("jhs_progress_outside")["muni-13199"]["value"] == 1.5
    assert pri["muni-13499"]["value"] is None and pri["muni-13499"]["status"] == "withheld"   # 卒業者10人未満


def test_elections(built):
    from tdm.ingest.tokyo_election import read_party_votes, read_turnout
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    names = {n for _, n, *_ in fixture.MUNICIPALITIES}
    turnout = by["voter_turnout"]
    assert [p["period"] for p in turnout["periods"]] == ["2024-07-07", "2024-10-27"]
    assert [p["label"] for p in turnout["periods"]] == ["2024年7月 都知事選", "2024年10月 衆院選"]

    def muni(indicator, period, entity="muni-13199"):
        rows = load(built, f"values/{indicator}/{period}/municipalities.json")["rows"]
        return {r["entity_id"]: r for r in rows}.get(entity)

    # 小選挙区で分かれる区は「…計」の行を使う（「…4区」の行は使わない）
    t = read_turnout(built.raw / "tokyo_election_2024_shugiin_touhyou" / "r6_syuugiin_hirei_touhyou.csv", names)
    assert sorted(t) == sorted(names)
    row = muni("voter_turnout", "2024-10-27")
    assert (row["numerator"], row["denominator"]) == t["サンプル区"]
    assert abs(row["value"] - t["サンプル区"][0] / t["サンプル区"][1] * 100) < 0.01

    # 衆院比例: 政党の得票 ÷ 合計
    votes = read_party_votes(built.raw / "tokyo_election_2024_shugiin_hirei" / "r6_syuugiin_hirei_kaihyou2.csv",
                             names, "shugiin_hirei")
    v, total = votes["サンプル区"]
    assert abs(total - sum(v.values())) < 0.01
    row = muni("vote_share_ldp", "2024-10-27")
    assert row["numerator"] == v["自由民主党"] and row["denominator"] == total
    # 参院比例: 政党ごとの3列のうち得票総数（政党名＋候補者名）
    votes = read_party_votes(built.raw / "tokyo_election_2025_sangiin_hirei" / "r7_sangiin_hirei_kaihyou0724.csv",
                             names, "sangiin_hirei")
    v, total = votes["ためし市"]
    assert set(v) == set(fixture.ELECTION_PARTIES["2025_sangiin_hirei"])
    assert abs(total - sum(v.values())) < 0.01
    assert muni("vote_share_sanseito", "2025-07-20", "muni-13299")["numerator"] == v["参政党"]
    ldp = by["vote_share_ldp"]
    assert [p["label"] for p in ldp["periods"]] == ["2024年10月 衆院選（比例）", "2025年7月 参院選（比例）"]
    # 名簿を出していない選挙は値を入れない（参政党は見本の衆院選に出ていない）
    assert [p["period"] for p in by["vote_share_sanseito"]["periods"]] == ["2025-07-20"]
    assert "vote_share_mirai" not in by


def test_street_trees_tama_format(tmp_path):
    from tdm.ingest.tokyo_street_trees import read_trees
    p = tmp_path / "tokyo_tama_gairoju.csv"
    p.write_text("name,type,height,perimeter,width,route,route_name,route_nickname,route_type,longitude,latitude\n"
                 "イチョウ,高木,8,76,2,3,世田谷町田線,鶴川街道,主要地方道,139.5909642,35.6334512\n"
                 "ケヤキ,高木,8,76,2,3,世田谷町田線,鶴川街道,主要地方道,,\n", encoding="utf-8-sig")
    assert read_trees(p, "cp932") == [("イチョウ", 139.5909642, 35.6334512)]


def test_traffic_accident_in_enclave_counts_for_its_own_municipality(tmp_path):
    # 区市町村の境界は穴を埋めているので、飛び地を囲む区市町村の形は飛び地にも重なる。
    # 区市町村の件数は町丁目の属する区市町村で数え、町丁目の合計と食い違わないようにする
    import json as _json
    from shapely.geometry import box, mapping
    from tdm.db import connect, init_schema
    from tdm.ingest import npa_traffic
    conn = connect(":memory:")
    init_schema(conn)
    conn.execute("PRAGMA foreign_keys = OFF")   # 出典・指標の行は省く
    outer, inner = box(139.0, 35.0, 139.1, 35.1), box(139.04, 35.04, 139.06, 35.06)
    shapes = {"muni-13101": outer, "muni-13102": inner,
              "area-13101001001": outer.difference(inner), "area-13102001001": inner}
    for eid, g in shapes.items():
        kind = "municipality" if eid.startswith("muni-") else "small_area"
        parent = None if kind == "municipality" else "muni-" + eid[5:10]
        conn.execute("INSERT INTO entities (entity_id, entity_type, name, parent_id) VALUES (?, ?, ?, ?)",
                     (eid, kind, eid, parent))
        conn.execute("INSERT INTO boundaries VALUES (?, 'v', ?, '2020-10-01', 's', ?, NULL, NULL, ?, ?, ?, ?)",
                     (f"v:{eid}", eid, _json.dumps(mapping(g)), *g.bounds))
    csv_path = tmp_path / "honhyo.csv"
    csv_path.write_text("都道府県コード,事故内容,事故類型,当事者種別（当事者A）,当事者種別（当事者B）,"
                        "地点　緯度（北緯）,地点　経度（東経）\n30,2,21,03,03,350300000,1390300000\n",
                        encoding="cp932")
    catalog = {"traffic_accidents": {"source_kind": "npa_traffic", "traffic_filter": "all",
                                     "definition_version": "1"}}
    npa_traffic.ingest(conn, csv_path, "s", catalog, ("2025-01-01", "2025-12-31", "calendar_year"), "v")
    got = dict(conn.execute("SELECT entity_id, value FROM observations").fetchall())
    assert got == {"muni-13101": 0, "muni-13102": 1, "area-13101001001": 0, "area-13102001001": 1}


def test_town_total_row_is_not_put_on_unsplit_remainder(tmp_path):
    # 丁目に分かれた町の合計（9桁）を、境界の丁目のない部分（末尾00）に入れると二重に数える
    from tdm.db import connect, init_schema
    from tdm.ingest.estat_small_area import Table, match_rows
    conn = connect(":memory:")
    init_schema(conn)
    conn.execute("PRAGMA foreign_keys = OFF")
    for eid in ("area-13199001001", "area-13199001002", "area-13199001000", "area-13199002000"):
        conn.execute("INSERT INTO entities (entity_id, entity_type, name) VALUES (?, 'small_area', ?)", (eid, eid))
    rows = [{"KEY_CODE": k} for k in ("131990010", "13199001001", "13199001002", "131990020")]
    matched, unmatched = match_rows(conn, Table(["KEY_CODE"], rows))
    assert sorted(e for e, _ in matched) == ["area-13199001001", "area-13199001002", "area-13199002000"]
    assert unmatched == []


def test_inbound_guests(built):
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    assert by["inbound_guest_nights"]["periods"][-1]["levels"] == ["prefecture"]

    def pref(ind):
        return {r["entity_id"]: r for r in load(built, f"values/{ind}/2025-01-01/prefectures.json")["rows"]}
    total, foreign = fixture.inbound_values("13")
    nights, share = pref("inbound_guest_nights"), pref("inbound_guest_share")
    assert abs(nights["pref-13"]["value"] - foreign * 0.0001) < 0.01   # 万人泊
    assert abs(share["pref-13"]["value"] - foreign / total * 100) < 0.01
    assert share["pref-13"]["numerator"] == foreign and share["pref-13"]["denominator"] == total
    assert abs(nights["pref-14"]["value"] - fixture.inbound_values("14")[1] * 0.0001) < 0.01   # コードなしの行


def test_gakuryoku(built):
    def pref(ind):
        return {r["entity_id"]: r for r in load(built, f"values/{ind}/2025-04-17/prefectures.json")["rows"]}
    assert pref("gakuryoku_elem_japanese")["pref-13"]["value"] == 70.0
    assert pref("gakuryoku_elem_math")["pref-13"]["value"] == 64.0
    assert pref("gakuryoku_jhs_japanese")["pref-13"]["value"] == 57.0
    assert pref("gakuryoku_jhs_math")["pref-14"]["value"] == 47.0
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    assert by["gakuryoku_elem_math"]["periods"][0]["label"] == "2025年度（4月実施）"


def test_jhs_students(built):
    def rows(ind, level):
        return {r["entity_id"]: r for r in load(built, f"values/{ind}/2025-05-01/{level}.json")["rows"]}
    pri = rows("jhs_students_private", "municipalities")
    assert pri["muni-13199"]["value"] == 40.0 and pri["muni-13199"]["denominator"] == 1000
    assert pri["muni-13499"]["value"] is None and pri["muni-13499"]["status"] == "not_applicable"   # 生徒0人
    assert rows("jhs_students_national", "municipalities")["muni-13199"]["value"] == 10.0
    # 都道府県の値は「計」の行から（区市町村の分子分母の合計ではない）
    p = rows("jhs_students_public", "prefectures")["pref-13"]
    assert abs(p["value"] - 2400 / 3000 * 100) < 0.01 and p["denominator"] == 3000
