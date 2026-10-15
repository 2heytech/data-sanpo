import json
import re
import sqlite3

import pytest

from tdm import fixture
from tdm.cli import cmd_build
from tdm.config import Paths, load_censuses, load_indicators
from tdm.db import connect, init_schema, insert_observation, upsert_entity, upsert_indicators
from tdm.ingest.estat_small_area import normalize_label, parse_cell
from tdm.regions import designated_city_wards, region_of


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
    data = json.loads((paths.releases / "test" / rel).read_text(encoding="utf-8"))
    m = re.fullmatch(r"places/([^/]+)\.json", rel)
    if m and "prefectures" in data:
        # 点の一覧は都道府県ごとのファイルに分かれている。テストでは全都道府県分をまとめて返す
        for pref in data["prefectures"]:
            part = load(paths, f"places/{m[1]}/{pref}.json")
            key = next(k for k in ("stations", "schools", "points") if k in part)
            data.setdefault(key, []).extend(part[key])
    return data


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


def test_small_area_names_are_in_boundary_file(built):
    # 町丁・字等の名前・範囲・代表点は境界ファイルに入れ、別のファイル（areas/）は作らない（ファイル数の節約）
    gj = load(built, "boundaries/census2020/13199.geojson")
    assert gj["municipality_id"] == "muni-13199"
    props = gj["features"][0]["properties"]
    assert set(props) == {"id", "name", "bbox", "center"}
    w, s, e, n = props["bbox"]
    assert w <= props["center"][0] <= e and s <= props["center"][1] <= n
    assert not (built.releases / "test" / "areas").exists()


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


def test_fetch_falls_back_to_previous_download(tmp_path):
    """配布元が 403 などで拒んだときは、前回の取得分があればそれを使い、なければ失敗にする。"""
    import urllib.error
    from tdm.fetch import fetch_source

    def refuse(u):
        raise urllib.error.HTTPError(u, 403, "Forbidden", None, None)
    cfg = {"url": "https://example.invalid/page", "download_url": "https://example.invalid/a.csv"}
    first = fetch_source("k", cfg, tmp_path / "a", downloader=lambda u: b"x,y\n1,2\n")
    assert fetch_source("k", cfg, tmp_path / "a", downloader=refuse) == first
    with pytest.raises(OSError):
        fetch_source("k", cfg, tmp_path / "new", downloader=refuse)
    multi = {"url": "https://example.invalid/page",
             "download_files": {"a.csv": "https://example.invalid/a.csv", "b.csv": "https://example.invalid/b.csv"}}
    first = fetch_source("m", multi, tmp_path / "m", downloader=lambda u: b"x,y\n1,2\n")
    assert fetch_source("m", multi, tmp_path / "m", downloader=refuse) == first


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
    assert a["pooled_periods"] == 4   # 2010・2015・2020年と2025年（市区町村だけ）
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
        # 一人暮らし・子どものいる世帯は2025年（市区町村だけ）もある
        extra = ["2025-10-01"] if ind in ("single_person_household_share", "households_with_children_share") else []
        assert [p["period"] for p in by[ind]["periods"]] == ["2010-10-01", "2015-10-01", "2020-10-01", *extra]
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
    assert share["category"] == "外国人住民" and share["family"] == "census_foreign"
    assert [p["period"] for p in share["periods"]] == ["2010-10-01", "2015-10-01", "2020-10-01", "2025-10-01"]
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
    # 総数は2021年以降は全国の住民基本台帳、2020年以前は東京都の表（東京都だけ）
    assert [p["period"] for p in total["periods"]] == ["2020-01-01", "2025-01-01", "2026-01-01"]
    assert by["foreign_residents_korea"]["facets"]["type"] == "韓国"
    assert [p["period"] for p in by["foreign_residents_korea"]["periods"]] == ["2020-01-01", "2026-01-01"]
    juki = fixture.juki_foreign_values(2026)
    munis = {r["entity_id"]: r for r in load(
        built, "values/foreign_residents/2026-01-01/municipalities.json")["rows"]}
    assert munis["muni-13199"]["value"] == juki["13199"] and munis["muni-14199"]["value"] == juki["14199"]
    assert munis["muni-13499"]["value"] == juki["13499"]   # 全国の表には島しょの町村もある
    assert "muni-14190" not in munis   # 政令指定都市の市全体の行は地図の単位ではない
    prefs = {r["entity_id"]: r for r in load(
        built, "values/foreign_residents/2026-01-01/prefectures.json")["rows"]}
    tokyo = sum(v for c, v in juki.items() if c[:2] == "13")
    assert prefs["pref-13"]["value"] == tokyo + 7   # 出典の都道府県の行を使う
    # 外国人住民の割合: 分母は同じ調査の【総計】の人口。分母の指標そのものは公開しない
    share = by["foreign_residents_share"]
    assert share["facets"] == {"type": "総数", "basis": "割合"} and share["family"] == "foreign"
    assert [p["period"] for p in share["periods"]] == ["2025-01-01", "2026-01-01"]   # 2020年以前は分母がない
    assert "juki_population" not in by
    tot = fixture.juki_total_values(2026)
    srows = {r["entity_id"]: r for r in load(
        built, "values/foreign_residents_share/2026-01-01/municipalities.json")["rows"]}
    assert srows["muni-13199"]["numerator"] == juki["13199"] and srows["muni-13199"]["denominator"] == tot["13199"]
    assert srows["muni-13199"]["value"] == pytest.approx(juki["13199"] / tot["13199"] * 100, abs=1e-4)
    assert srows["muni-13499"]["value"] is None and srows["muni-13499"]["status"] == "withheld"   # 分母が50人未満
    sprefs = {r["entity_id"]: r for r in load(
        built, "values/foreign_residents_share/2026-01-01/prefectures.json")["rows"]}
    assert sprefs["pref-13"]["denominator"] == sum(v for c, v in tot.items() if c[:2] == "13") + 7
    china = {r["entity_id"]: r for r in load(
        built, "values/foreign_residents_china/2026-01-01/municipalities.json")["rows"]}
    assert china["muni-13199"]["value"] > 0 and "muni-14199" not in china   # 国籍別は東京都だけ
    old = {r["entity_id"]: r for r in load(
        built, "values/foreign_residents/2020-01-01/municipalities.json")["rows"]}
    assert old["muni-13199"]["value"] > 0 and "muni-14199" not in old
    # 2020年の東京都の表では、島しょ（支庁単位でしか公表されない町村）は値なし。0 にしない
    assert old.get("muni-13499") is None or old["muni-13499"]["value"] is None


def test_census_foreign_by_nationality(built):
    """国勢調査 人口等基本集計の男女・国籍別人口（市区町村・都道府県、2010〜2025年。#102）。"""
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    periods = lambda i: [p["period"] for p in by[i]["periods"]]
    assert by["census_foreign_population"]["facets"] == {"type": "総数", "basis": "人数"}
    assert by["census_foreign_china_share"]["facets"] == {"type": "中国", "basis": "割合"}
    assert {by[i]["family"] for i in ("census_foreign_population", "census_foreign_china", "foreign_resident_share")} \
        == {"census_foreign"}
    assert periods("census_foreign_china") == ["2010-10-01", "2015-10-01", "2020-10-01", "2025-10-01"]
    assert periods("census_foreign_india") == ["2015-10-01", "2020-10-01", "2025-10-01"]   # 2010年の表にない
    assert periods("census_foreign_nepal") == ["2020-10-01", "2025-10-01"]
    assert periods("census_foreign_myanmar_share") == ["2025-10-01"]

    def rows(indicator, year, level="municipalities"):
        return {r["entity_id"]: r for r in load(built, f"values/{indicator}/{year}-10-01/{level}.json")["rows"]}

    for year in (2010, 2015, 2020, 2025):
        v = fixture.census_foreign_values(year)
        china, total = rows("census_foreign_china", year), rows("census_foreign_population", year)
        assert china["muni-13199"]["value"] == v["13199"]["中国"] and china["muni-14199"]["value"] == v["14199"]["中国"]
        assert total["muni-14199"]["value"] == v["14199"]["外国人人口"]   # 男女の総数の行・列（男の値ではない）
        assert total["muni-13499"]["value"] == 0 and total["muni-13499"]["status"] == "observed"   # 「-」は0人
        assert set(total) == {"muni-13199", "muni-13299", "muni-13499", "muni-14199"}   # 市全体・消えた村の行は使わない
        prefs = rows("census_foreign_china", year, "prefectures")
        assert prefs["pref-13"]["value"] == v["13000"]["中国"]   # 公表の都道府県の行（市区町村の合計＋3）
        share = rows("census_foreign_china_share", year)
        assert share["muni-14199"]["numerator"] == v["14199"]["中国"]
        assert share["muni-14199"]["denominator"] == v["14199"]["総数"]
        assert share["muni-13499"]["value"] is None and share["muni-13499"]["status"] == "withheld"   # 人口50人未満
        whole = rows("foreign_resident_share", year)
        if year != 2020:
            assert whole["muni-13199"]["numerator"] == v["13199"]["外国人人口"]
        # 2020年の東京都の市区町村は小地域集計の表の値（同じ地域・時点の値を2つにしない）。神奈川県は人口等基本集計
        assert whole["muni-14199"]["numerator"] == v["14199"]["外国人人口"]
        wprefs = rows("foreign_resident_share", year, "prefectures")
        assert wprefs["pref-13"]["numerator"] == v["13000"]["外国人人口"]
        assert wprefs["pref-13"]["denominator"] == v["13000"]["総数"]
    assert "small_area" not in [lv for p in by["census_foreign_china"]["periods"] for lv in p["levels"]]


def test_zairyu_foreign_by_nationality(built):
    """在留外国人統計の市区町村別・国籍別（全国、12月末）。"""
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    thai = by["zairyu_foreign_thailand"]
    assert thai["family"] == "zairyu_foreign" and thai["facets"] == {"type": "タイ", "basis": "人数"}
    assert [p["period"] for p in thai["periods"]] == ["2022-12-31", "2023-12-31"]
    for year in (2022, 2023):
        vals = fixture.zairyu_values(year)
        china = {r["entity_id"]: r for r in load(
            built, f"values/zairyu_foreign_china/{year}-12-31/municipalities.json")["rows"]}
        assert china["muni-13199"]["value"] == vals["13199"]["中国"]
        assert china["muni-14199"]["value"] == vals["14199"]["中国"]
        assert "muni-14190" not in china
        thai_rows = {r["entity_id"]: r for r in load(
            built, f"values/zairyu_foreign_thailand/{year}-12-31/municipalities.json")["rows"]}
        assert thai_rows["muni-13199"]["value"] == 0 and thai_rows["muni-13199"]["status"] == "observed"
    # 2022年末: 都道府県は表の都道府県の行（市区町村の合計より1人多い見本）
    vals = fixture.zairyu_values(2022)
    prefs = {r["entity_id"]: r for r in load(built, "values/zairyu_foreign_china/2022-12-31/prefectures.json")["rows"]}
    assert prefs["pref-13"]["value"] == sum(v["中国"] for c, v in vals.items() if c[:2] == "13") + 1
    # 2023年末: 総数10人以下の市区町村（かりの村）は「その他」にまとめられて値なし。0 にしない。
    # 市区町村がそろわない東京都の値は出さず、そろう神奈川県は市区町村の合計
    vals = fixture.zairyu_values(2023)
    china = {r["entity_id"]: r for r in load(
        built, "values/zairyu_foreign_china/2023-12-31/municipalities.json")["rows"]}
    assert china.get("muni-13499") is None or china["muni-13499"]["value"] is None
    prefs = {r["entity_id"]: r for r in load(built, "values/zairyu_foreign_china/2023-12-31/prefectures.json")["rows"]}
    assert prefs["pref-13"]["value"] is None
    assert prefs["pref-14"]["value"] == vals["14199"]["中国"]


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
    assert ind["periods"][-1]["levels"] == ["municipality", "prefecture"]


def test_daytime_population_is_national(built):
    """国勢調査 従業地・通学地集計の昼間人口（全国の市区町村・都道府県、2010・2015・2020年。#107）。"""
    base = fixture._base_values(__import__("random").Random(42))
    for year in (2010, 2015, 2020):
        vals = fixture.census_daytime_values(year, base)
        munis = {r["entity_id"]: r["value"] for r in load(
            built, f"values/daytime_population/{year}-10-01/municipalities.json")["rows"]}
        # 男女・年齢の総数の行（2010年は都道府県ごとのファイル）。政令指定都市の市全体（14100）・消えた村は使わない
        assert munis == {f"muni-{c}": vals[c] for c in ("13199", "13299", "13499", "14199")}
        prefs = {r["entity_id"]: r["value"] for r in load(
            built, f"values/daytime_population/{year}-10-01/prefectures.json")["rows"]}
        assert prefs == {"pref-13": vals["13000"], "pref-14": vals["14000"]}   # 公表の都道府県の行
    # 東京都以外でも、交通事故の昼間人口当たりの分母になる
    rows = {r["entity_id"]: r for r in load(
        built, "values/traffic_accidents_per_100_daytime/2025-01-01/municipalities.json")["rows"]}
    assert rows["muni-14199"]["denominator"] == fixture.census_daytime_values(2020, base)["14199"]


def test_crime_town_names_are_normalized():
    from tdm.ingest.keishicho_crime import normalize_name
    assert normalize_name("飯田橋１丁目") == normalize_name("飯田橋一丁目") == "飯田橋1丁目"
    assert normalize_name("霞ヶ関") == normalize_name("霞が関")
    assert normalize_name("西新宿十二丁目") == "西新宿12丁目"


def test_crime_towns_match_current_map_only(tmp_path):
    # 警視庁の表の町丁目の照合: 2010年の境界にしかない名前のない区市町村に島しょの行を取られない、
    # 「神田」を省いた地図の町名・字体の違い・地図で丁目に分かれていない町に対応付け、
    # 地図のほうが細かい町と同じ名前の町丁目には割り振らずに値なし
    from tdm.ingest import keishicho_crime
    conn = connect(":memory:")
    init_schema(conn)
    conn.execute("PRAGMA foreign_keys = OFF")   # 出典・指標の行は省く
    catalog = {k: d for k, d in load_indicators().items() if d.get("source_kind") == "keishicho_crime"}
    entities = [
        ("muni-13101", "municipality", "千代田区", None, "v"), ("muni-13361", "municipality", "大島町", None, "v"),
        ("muni-13199", "municipality", "", None, "old"),     # 2010年の所属未定地（名前がない）
        ("area-13101000001", "small_area", "三崎町一丁目", "muni-13101", "v"),
        ("area-13101000002", "small_area", "神田司町", "muni-13101", "v"),
        ("area-13101000003", "small_area", "松涛一丁目", "muni-13101", "v"),
        ("area-13101000004", "small_area", "川口町", "muni-13101", "v"),
        ("area-13101000005", "small_area", "川口町", "muni-13101", "v"),
        ("area-13101000006", "small_area", "大字平井本宿", "muni-13101", "v"),
        ("area-13101000007", "small_area", "大字平井谷戸", "muni-13101", "v"),
        ("area-13101000008", "small_area", "鴬谷町", "muni-13101", "v"),
        ("area-13101000009", "small_area", "飯田橋一丁目", "muni-13101", "v"),
        ("area-13101000010", "small_area", "飯田橋二丁目", "muni-13101", "old"),   # 今の地図にない
        ("area-13361000001", "small_area", "元町", "muni-13361", "v"),
        ("area-13361000002", "small_area", "岡田", "muni-13361", "v"),
    ]
    for eid, kind, name, parent, version in entities:
        conn.execute("INSERT INTO entities (entity_id, entity_type, name, parent_id) VALUES (?, ?, ?, ?)",
                     (eid, kind, name, parent))
        conn.execute("INSERT INTO boundaries (boundary_id, boundary_version, entity_id, reference_date, source_id, "
                     "geometry, bbox_west, bbox_south, bbox_east, bbox_north) VALUES (?, ?, ?, '2020', 's', '{}', 0, 0, 0, 0)",
                     (f"{version}:{eid}", version, eid))
    columns = "市区町丁," + ",".join(d["column"] for d in catalog.values()) + "\n"
    zeros = "," + ",".join("0" for _ in range(len(catalog) - 1))
    rows = [("千代田区神田三崎町１丁目", 5), ("千代田区神田司町２丁目", 2), ("千代田区松濤１丁目", 1),
            ("千代田区川口町", 4), ("千代田区大字平井", 6), ("千代田区鶯谷町", 3), ("千代田区計", 21),
            ("大島町元町", 2), ("大島町計", 2), ("２３区計", 21), ("合計", 23)]
    path = tmp_path / "R7.csv"
    path.write_text(columns + "".join(f"{name},{n}{zeros}\n" for name, n in rows), encoding="cp932")
    result = keishicho_crime.ingest(conn, path, "s", catalog, ("2025-01-01", "2025-12-31", "calendar_year"), "v")
    got = {r["entity_id"]: (r["value"], r["status"]) for r in conn.execute(
        "SELECT entity_id, value, status FROM observations WHERE indicator_id = 'crime_total'")}
    assert result["unmatched"] == []
    assert got["muni-13361"] == (2, "observed") and got["area-13361000001"] == (2, "observed")   # 島しょの行
    assert got["area-13361000002"] == (0, "observed")
    assert "muni-13199" not in got and "area-13101000010" not in got
    assert got["area-13101000001"] == (5, "observed")     # 神田三崎町1丁目 → 三崎町一丁目
    assert got["area-13101000002"] == (2, "observed")     # 神田司町2丁目 → 神田司町（地図は丁目に分かれていない）
    assert got["area-13101000003"] == (1, "observed")     # 松濤 → 松涛
    assert got["area-13101000008"] == (3, "observed")     # 鶯谷町 → 鴬谷町
    for eid in ("area-13101000004", "area-13101000005", "area-13101000006", "area-13101000007"):
        assert got[eid] == (None, "missing")              # 同じ名前が2つ・地図のほうが細かい
    assert got["area-13101000009"] == (0, "observed")     # 表にない町丁目（計と一致）
    # 列名が変わったら0件で書かずに止める
    path.write_text("市区町丁,総数\n千代田区計,1\n", encoding="cp932")
    with pytest.raises(ValueError, match="列"):
        keishicho_crime.ingest(conn, path, "s", catalog, ("2025-01-01", "2025-12-31", "calendar_year"), "v")


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
    # 大半が0で分位点の区切りが作れないときも、0とそれより大きい値は分ける（#75、徳島県の私立中学校）
    assert nice_breaks([5.656] + [0.0] * 23, 12, 1) == [5.6]
    assert nice_breaks([0.05] + [0.0] * 20, 12, 1) == [0.05]
    assert nice_breaks([0.0] * 5, 12, 1) == []
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


def test_quantile_breaks():
    from tdm.breaks import quantile_breaks
    # 分位点を表示の桁に丸めたまま使い、同じ値になった区切りは1つにする
    assert quantile_breaks([float(v) for v in range(1, 11)], 4, 0) == [3.0, 6.0, 8.0]
    assert quantile_breaks([1.0] * 8 + [2.0, 3.0], 4, 1) == [1.0]
    assert quantile_breaks([1.0], 4, 1) == []


def test_stations_are_per_operator_and_keep_duplicates_apart(built):
    st = load(built, "places/station_passengers.json")
    assert st["periods"][0]["label"] == "2011年度" and st["periods"][-1]["label"] == "2024年度"
    by = {(s["name"], s["operator"]): s for s in st["stations"] if s["lines"] != ["遠方線"]}
    assert ("県外", "架空鉄道") not in by                      # 対象の都道府県の外の駅は含めない
    assert {s["municipality_id"] for s in st["stations"]} <= {"muni-13199", "muni-13299", "muni-14199"}
    # 駅の一覧は都道府県ごとのファイルに分け、places/<指標>.json には都道府県ごとの件数と範囲を書く
    meta = json.loads((built.releases / "test" / "places/station_passengers.json").read_text(encoding="utf-8"))
    assert "stations" not in meta and set(meta["prefectures"]) == {"13", "14"}
    assert meta["prefectures"]["14"]["count"] == 1
    w, s, e, n = meta["prefectures"]["14"]["bbox"]
    assert w <= 139.62 <= e and s <= 35.47 <= n
    kanagawa = load(built, "places/station_passengers/14.json")
    assert kanagawa["prefecture"] == "14" and [x["name"] for x in kanagawa["stations"]] == ["標本"]
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
    assert [p["label"] for p in sc["periods"]] == ["2023年5月1日現在"]   # カタログに載っている年度だけ
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
    # 街区レベルにない大字は大字・町丁目レベルで補う。大字を書かない住所は大字が1つの町村だけ
    assert by["school-990050"]["precision"] == "町丁目" and by["school-990050"]["coord"] == [139.68, 35.7]
    assert by["school-990060"]["coord"] == [139.37, 34.71]
    assert any(s.startswith("mlit_isj_2025@") for s in sc["source_ids"])
    assert any(s.startswith("mlit_isj_oaza_2025@") for s in sc["source_ids"])
    assert "school_enrollment" not in {i["id"] for i in load(built, "indicators.json")["indicators"]}


def test_schools_outside_tokyo_are_locations_only(built):
    sc = load(built, "places/school_enrollment.json")
    others = {s["name"]: s for s in sc["schools"] if s["municipality_id"].startswith("muni-14")}
    # 公立の小学校・中学校・義務教育学校だけ（私立・高校・休校は除く）。児童・生徒数はないので値なし（0 にしない）
    assert set(others) == {"みほん市立標本小学校", "みほん市立標本中学校", "みほん市立標本学園"}
    s = others["みほん市立標本学園"]
    assert s["location_only"] and s["values"] == [None] and s["school_type"] == "compulsory"
    assert s["coord"] == [139.63, 35.47] and s["as_of"] == "2023年度"
    # 東京都は都教委の一覧だけを使う（国土数値情報の東京都の学校は取り込まない）
    assert "サンプル区立見本小学校" not in {x["name"] for x in sc["schools"]}
    assert not any(x.get("location_only") for x in sc["schools"] if x["municipality_id"].startswith("muni-13"))
    meta = json.loads((built.releases / "test" / "places/school_enrollment.json").read_text(encoding="utf-8"))
    assert meta["prefectures"]["14"]["location_only"] == 3 and "location_only" not in meta["prefectures"]["13"]
    assert any(x.startswith("mlit_p29_2023@") for x in sc["source_ids"])


def test_nurseries_outside_tokyo_follow_terms(built):
    nc = load(built, "places/nursery_capacity.json")
    # 神奈川県の所管の保育所は利用条件（商用利用不可）で除く。東京都は都の一覧だけ
    assert not any(p["municipality_id"].startswith("muni-14") for p in nc["points"])
    assert "見本保育園" not in {p["name"] for p in nc["points"]}
    from tdm.ingest.mlit_facilities import _matches
    assert _matches("14199", ["14"]) and not _matches("13101", ["14"])


def test_nursery_terms_exceptions(tmp_path):
    from tdm.ingest import mlit_facilities
    conn = connect(":memory:")
    init_schema(conn)
    conn.execute("""INSERT INTO sources (source_id, dataset_key, title, provider, license,
                    attribution, retrieved_at, file_sha256) VALUES ('s','s','s','s','s','s','t','h')""")
    for code in ("14131", "14199"):
        conn.execute("INSERT INTO entities VALUES (?, 'municipality', ?, NULL, NULL, NULL, NULL, NULL)",
                     (f"muni-{code}", code))
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [139.7, 35.5]},
              "properties": {"P14_001": "神奈川県", "P14_002": name, "P14_003": code, "P14_004": "1-1",
                             "P14_007": "050401", "P14_008": f"{name}保育園"}}
             for code, name in (("14131", "川崎市川崎区"), ("14199", "みほん市中区"))]
    path = tmp_path / "P14-23_14.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False),
                    encoding="utf-8")
    r = mlit_facilities.ingest_nurseries(conn, [path], "s", "none", ["14"], "2023年度", ["14"], ["1413"])
    assert r["nurseries"] == 1 and r["excluded_by_terms"] == 1
    assert [x["name"] for x in conn.execute("SELECT name FROM entities WHERE entity_type = 'nursery'")] == [
        "川崎市川崎区保育園"]


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


def test_census2025_municipal(built):
    import tomllib
    from tdm.ingest.estat_census_municipal import read_table
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    pop = by["population_total"]
    p2025 = next(p for p in pop["periods"] if p["period"] == "2025-10-01")
    assert p2025["levels"] == ["municipality", "prefecture"]  # 2025年は市区町村（と都道府県）だけ
    assert pop["default_period"] == "2020-10-01"        # 最初は町丁・字等まである最新の時点を表示
    from tdm.config import load_sources
    cfg = load_sources()
    def src(key):
        c = cfg[key]
        t = read_table(built.raw / key / c["files"][0], c["columns"], c.get("filters"))
        return {r["KEY_CODE"]: r for r in t.rows}

    def muni(indicator, code="13199", period="2025-10-01"):
        rows = load(built, f"values/{indicator}/{period}/municipalities.json")["rows"]
        return {r["entity_id"]: r for r in rows}[f"muni-{code}"]

    p = src("census2025_municipal_population")
    # 市区町村と都道府県の行だけ（全国・政令指定都市の市全体・2000年の市区町村の行は使わない）
    assert set(p) == {"13199", "13299", "13499", "14199", "13", "14"}
    people, homes = int(p["13199"]["人口総数"]), int(p["13199"]["世帯総数"])
    assert muni("population_total")["value"] == people and muni("households_total")["value"] == homes
    pph = muni("persons_per_household")
    assert pph["numerator"] == people and pph["denominator"] == homes   # 公表の1世帯当たり人員ではなく分子・分母から
    change = muni("population_change_rate")
    before = muni("population_total", period="2020-10-01")["value"]
    assert abs(change["value"] - (people - before) / before * 100) < 0.001   # 公開値は小数3桁
    assert muni("population_density")["value"] > 0
    # 神奈川県（全国の表）も取り込み、都道府県の値は公表の都道府県の行（市区町村の合計ではない。#73）
    assert muni("population_total", "14199")["value"] == int(p["14199"]["人口総数"])
    prefs = {r["entity_id"]: r for r in load(built, "values/population_total/2025-10-01/prefectures.json")["rows"]}
    assert prefs["pref-13"]["value"] == int(p["13"]["人口総数"])
    assert prefs["pref-13"]["value"] != sum(int(p[c]["人口総数"]) for c in ("13199", "13299", "13499"))
    shares = {r["entity_id"]: r for r in load(built, "values/aged_65_plus_share/2025-10-01/prefectures.json")["rows"]}
    a13 = src("census2025_municipal_age")["13"]
    assert shares["pref-13"]["numerator"] == int(a13["総数65歳以上"])   # 率は都道府県の行の分子・分母から
    # 年齢は国籍総数・男女計の行。分母は年齢3区分の合計（年齢不詳を除く）
    a = src("census2025_municipal_age")["13199"]
    old = muni("aged_65_plus_share")
    assert old["numerator"] == int(a["総数65歳以上"])
    assert old["denominator"] == sum(int(a[k]) for k in ("総数15歳未満", "総数15~64歳", "総数65歳以上"))
    h = src("census2025_municipal_household_size")["13199"]
    single = muni("single_person_household_share")
    assert single["numerator"] == int(h["世帯人員1人"]) and single["denominator"] == int(h["一般世帯数"])
    f = src("census2025_municipal_family_type")["13199"]
    kids = muni("households_with_children_share")
    assert kids["numerator"] == int(f["18歳未満世帯員のいる一般世帯総数"])  # 家族類型の総数の行
    assert kids["denominator"] == int(f["一般世帯総数"])


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
    assert rows["muni-14199"]["value"] is None and rows["muni-14199"]["status"] == "not_applicable"
    assert "市全体の値だけ" in rows["muni-14199"]["note"]                      # 「データなし」に見えないよう理由を書く
    # 所得割を納める人の割合: 分母は同じ年の1月1日の住民基本台帳の人口（#106）
    share = by["income_levy_taxpayer_share"]
    assert share["unit"] == "%" and "income_levy_taxpayers" not in by    # 分子の人数は公開しない
    r = {r["entity_id"]: r for r in load(built, f"values/income_levy_taxpayer_share/{pid}/municipalities.json")["rows"]}
    assert r["muni-13199"]["numerator"] == city["所得割の納税義務者数"]
    assert r["muni-13199"]["denominator"] == fixture.juki_total_values(2025)["13199"]
    assert abs(r["muni-13199"]["value"] - city["所得割の納税義務者数"] / fixture.juki_total_values(2025)["13199"] * 100) < 0.01
    assert r["muni-13499"]["value"] is None                                # 人口50人未満は出さない
    pref = {r["entity_id"]: r for r in load(built, f"values/income_levy_taxpayer_share/{pid}/prefectures.json")["rows"]}
    assert 0 < pref["pref-13"]["value"] < 100



def test_finance(built):
    """財政（主要財政指標一覧・市町村別決算状況調、#119）。"""
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    # 住民税と課税対象所得は「種別」で切り替えず、別々の指標にする
    assert by["resident_tax_per_taxpayer"]["family"] is None and by["taxable_income_per_taxpayer"]["family"] is None
    fs = by["fiscal_strength_index"]
    assert fs["category"] == "財政" and fs["unit"] == ""
    assert [p["label"] for p in fs["periods"]] == ["2023年度", "2024年度"]

    def rows(indicator, level="municipalities", period="2024-04-01"):
        return {r["entity_id"]: r for r in load(built, f"values/{indicator}/{period}/{level}.json")["rows"]}

    v = fixture.fiscal_values(2024)
    assert rows("fiscal_strength_index")["muni-13199"]["value"] == v["13199"][0]
    assert rows("current_balance_ratio")["muni-13299"]["value"] == v["13299"][1]
    assert rows("real_debt_service_ratio")["muni-13199"]["value"] == v["13199"][2] < 0     # マイナスもそのまま
    burden = rows("future_burden_ratio")
    # 「-」（将来負担なし）は0で塗り、注記を付ける。空欄は値なしのまま（0にしない）
    assert burden["muni-13199"]["value"] == 0 and "将来負担なし" in burden["muni-13199"]["note"]
    assert burden["muni-13499"]["value"] is None and burden["muni-13499"]["status"] == "missing"
    assert burden["muni-13299"]["value"] == v["13299"][3]
    # 政令指定都市は市全体の値だけなので、区には割り振らない（区には理由を書く）
    assert burden["muni-14199"]["value"] is None and burden["muni-14199"]["status"] == "not_applicable"
    assert "市全体の値だけ" in burden["muni-14199"]["note"]
    # 比率は合計できないので、都道府県の値は出さない
    pref = rows("future_burden_ratio", "prefectures")
    assert pref["pref-13"]["value"] is None and pref["pref-13"]["status"] == "not_applicable"

    s = {r[0]: r for r in fixture.SETTLEMENT_ROWS}
    exp = rows("expenditure_per_capita")["muni-13199"]
    assert exp["numerator"] == s["13199"][4] and exp["denominator"] == s["13199"][3]
    assert abs(exp["value"] - s["13199"][4] * 1000 / s["13199"][3]) < 0.01           # 千円 → 円
    # 歳入内訳の「地方税」は最初の列（内訳の表の同じ名前の列ではない）
    assert rows("local_tax_per_capita")["muni-13299"]["numerator"] == s["13299"][5]
    assert rows("local_debt_per_capita")["muni-13199"]["value"] == 0                   # 「-」は地方債なし
    assert rows("reserve_fund_per_capita")["muni-13499"]["denominator"] == s["13499"][3]
    # 都道府県の値は、政令指定都市（市全体）も含めた県内の合計 ÷ 人口の合計
    pref = rows("expenditure_per_capita", "prefectures")
    tokyo = [s[c] for c in ("13199", "13299", "13499")]
    assert abs(pref["pref-13"]["value"] - sum(r[4] for r in tokyo) * 1000 / sum(r[3] for r in tokyo)) < 0.01
    assert abs(pref["pref-14"]["value"] - s["14190"][4] * 1000 / s["14190"][3]) < 0.01
    ward = rows("expenditure_per_capita")["muni-14199"]
    assert ward["value"] is None and ward["status"] == "not_applicable" and "市全体の値だけ" in ward["note"]
    assert "01100" not in {e[5:] for e in rows("expenditure_per_capita")}              # 取り込まない都道府県


def test_designated_city_wards():
    """政令指定都市の区を、市のすぐ後ろの区の地域区分（市の名前）で集める（#119）。"""
    conn = connect(":memory:")
    init_schema(conn)
    wards = {"14131": "川崎市", "14137": "川崎市", "14151": "相模原市", "14153": "相模原市",
             "22131": "浜松市", "22138": "浜松市", "22140": "浜松市", "14201": None, "13101": "区部"}
    for pref in ("13", "14", "22"):
        upsert_entity(conn, f"pref-{pref}", "prefecture", pref)
    for code, region in wards.items():
        upsert_entity(conn, f"muni-{code}", "municipality", code, f"pref-{code[:2]}", region)
    assert designated_city_wards(conn, "14130") == ["muni-14131", "muni-14137"]   # 相模原市の区（14151〜）は入れない
    assert designated_city_wards(conn, "14150") == ["muni-14151", "muni-14153"]
    assert designated_city_wards(conn, "22130") == ["muni-22131", "muni-22138", "muni-22140"]
    assert designated_city_wards(conn, "14200") == [] and designated_city_wards(conn, "13100") == []


def test_area(built):
    """面積（国土地理院の面積調、#119）。"""
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    area = by["area"]
    assert area["category"] == "土地" and area["unit"] == "km²"
    assert [p["period"] for p in area["periods"]] == ["2020-10-01", "2025-10-01"]
    for period in ("2020-10-01", "2025-10-01"):
        munis = {r["entity_id"]: r for r in load(built, f"values/area/{period}/municipalities.json")["rows"]}
        prefs = {r["entity_id"]: r for r in load(built, f"values/area/{period}/prefectures.json")["rows"]}
        assert munis["muni-13299"]["value"] == fixture.area_value(period, "13299")
        assert "参考値" in munis["muni-13199"]["note"]                                    # 境界未定
        assert "湖の一部を除く" in munis["muni-13499"]["note"]
        assert munis["muni-14199"]["value"] == fixture.area_value(period, "14199")        # 政令指定都市の区
        # 都道府県は公表値（市区町村の合計ではない）
        assert prefs["pref-13"]["value"] == fixture.area_value(period, "13000")
        assert prefs["pref-13"]["value"] != round(sum(r["value"] for e, r in munis.items() if e.startswith("muni-13")), 2)


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
    # 東京都のほかの道府県の地域は0本にしない（値を出さず、指標の対象も東京都だけ）
    assert not any(e.startswith("muni-14") for e in munis)
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    assert by["street_trees"]["prefectures"] == ["13"]


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
    # 種別ごとに別の組（指標の一覧で4つから選ぶ。#105）。組の中は件数・住民100人当たり・昼間人口100人当たり
    for family, name in (("traffic", "交通事故の件数"), ("traffic_pedestrian", "歩行者が関係する交通事故の件数"),
                         ("traffic_bicycle", "自転車が関係する交通事故の件数"), ("traffic_fatal", "死亡事故の件数")):
        members = [i for i in by.values() if i.get("family") == family]
        assert len(members) == 3 and len({m["facets"]["type"] for m in members}) == 1
        assert members[0]["name"] == name and all(m["name"].startswith(name) for m in members)
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
    assert set(by) == {"サンプル-1", "サンプル-2", "サンプル5-1", "ためし-1", "ためし9-1", "みほん中-1"}  # 神奈川県は別ファイル
    assert by["みほん中-1"]["municipality_id"] == "muni-14199"
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
    from tdm.ingest.tokyo_election import read_turnout
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    names = {n for _, n, *_ in fixture.MUNICIPALITIES}
    turnout = by["voter_turnout"]
    assert [p["period"] for p in turnout["periods"]] == ["2024-07-07", "2024-10-27", "2025-07-20", "2026-02-08"]
    assert [p["label"] for p in turnout["periods"]] == ["2024年7月 都知事選", "2024年10月 衆院選", "2025年7月 参院選",
                                                        "2026年2月 衆院選"]

    def rows(indicator, period, level="municipalities"):
        path = built.releases / "test" / "values" / indicator / period / f"{level}.json"
        return {r["entity_id"]: r for r in json.loads(path.read_text(encoding="utf-8"))["rows"]} if path.exists() else {}

    # 区市町村の投票率は都選管（小選挙区で分かれる区は「…計」の行を使う）、都道府県は総務省の表
    t = read_turnout(built.raw / "tokyo_election_2024_shugiin_touhyou" / "r6_syuugiin_hirei_touhyou.csv", names)
    assert sorted(t) == sorted(names)
    row = rows("voter_turnout", "2024-10-27")["muni-13199"]
    assert (row["numerator"], row["denominator"]) == t["サンプル区"]
    for period in ("2024-10-27", "2025-07-20", "2026-02-08"):
        prefs = rows("voter_turnout", period, "prefectures")
        for pref in ("13", "14"):
            voters, electorate = fixture.election_turnout(period, pref)
            assert (prefs[f"pref-{pref}"]["numerator"], prefs[f"pref-{pref}"]["denominator"]) == (voters, electorate)
    assert "muni-14199" not in rows("voter_turnout", "2025-07-20")   # 市区町村の投票率は東京都だけ

    def share(period, party, name):
        votes = fixture.election_votes(period, name)
        return votes[fixture.ELECTION_PARTIES[period].index(party)], sum(votes)

    # 令和6年衆院選: 小選挙区で分かれた行（「サンプル区第４区」「…第２６区」）を合計する
    ldp = rows("vote_share_ldp", "2024-10-27")
    num, den = share("2024-10-27", "自由民主党", "サンプル区")
    assert abs(ldp["muni-13199"]["numerator"] - num) < 0.01 and abs(ldp["muni-13199"]["denominator"] - den) < 0.01
    num, den = share("2024-10-27", "自由民主党", "みほん市中区")
    assert abs(ldp["muni-14199"]["value"] - num / den * 100) < 0.01
    # 都道府県の値は都道府県別の表から（市区町村の合計ではない）
    pref = rows("vote_share_ldp", "2024-10-27", "prefectures")["pref-13"]
    votes = fixture.election_prefecture_votes("2024-10-27", "13")
    assert abs(pref["value"] - votes[3] / sum(votes) * 100) < 0.01
    # 表の最後の「合計」の欄を政党の得票数に取り違えない（分母は全政党の合計）
    for period in ["2024-10-27", "2025-07-20", "2026-02-08"]:
        votes = fixture.election_prefecture_votes(period, "14")
        assert abs(rows("vote_share_ldp", period, "prefectures")["pref-14"]["denominator"] - sum(votes)) < 0.01
    # 令和7年参院選: 政党ごとの3列のうち得票総数。空欄の村は値なし（0 にしない）
    sanseito = rows("vote_share_sanseito", "2025-07-20")
    num, den = share("2025-07-20", "参政党", "ためし市")
    assert sanseito["muni-13299"]["numerator"] == num and abs(sanseito["muni-13299"]["denominator"] - den) < 0.01
    assert sanseito["muni-13499"]["value"] is None and "空欄" in sanseito["muni-13499"]["note"]
    assert rows("vote_share_sanseito", "2025-07-20", "prefectures")["pref-14"]["value"] is not None
    # 令和8年衆院選: 区全体の行を使い「…第１」の行は足さない。政令指定都市の市全体の行は使わない
    mirai = rows("vote_share_mirai", "2026-02-08")
    num, den = share("2026-02-08", "チームみらい", "サンプル区")
    assert mirai["muni-13199"]["numerator"] == num and mirai["muni-13199"]["denominator"] == den
    num, den = share("2026-02-08", "チームみらい", "みほん市中区")
    assert mirai["muni-14199"]["numerator"] == num
    ldp = by["vote_share_ldp"]
    assert [p["label"] for p in ldp["periods"]] == ["2024年10月 衆院選（比例）", "2025年7月 参院選（比例）",
                                                    "2026年2月 衆院選（比例）"]
    # 名簿を出していない選挙は値を入れない（参政党は見本の衆院選に出ていない）
    assert [p["period"] for p in by["vote_share_sanseito"]["periods"]] == ["2025-07-20"]
    assert [p["period"] for p in by["vote_share_chudo"]["periods"]] == ["2026-02-08"]
    assert "vote_share_ishin" not in by


def test_soumu_election_names():
    from tdm.ingest.soumu_election import municipality_votes, norm
    names = {norm(n): f"muni-{i}" for i, n in enumerate(["鰺ケ沢町", "檮原町", "茅ヶ崎市", "佐伯市", "大田区"])}
    rows = {norm("鯵ケ沢町"): {"a": 1.0}, norm("梼原町"): {"a": 2.0}, norm("茅ケ崎市"): {"a": 3.0},
            norm("佐伯氏"): {"a": 4.0}, norm("大田区第４区"): {"a": 5.0}, norm("大田区第２６区"): {"a": 6.0}}
    assert municipality_votes(rows, names) == {"muni-0": {"a": 1.0}, "muni-1": {"a": 2.0}, "muni-2": {"a": 3.0},
                                               "muni-3": {"a": 4.0}, "muni-4": {"a": 11.0}}


def test_tokyo_only_sources_skip_same_named_municipalities_in_other_prefectures(tmp_path):
    # 東京都の出典は区市町村名で突き合わせる。府中市は広島県にもあるので、東京都の府中市だけに入れる
    from tdm.ingest import tokyo_election
    conn = connect(":memory:")
    init_schema(conn)
    conn.execute("PRAGMA foreign_keys = OFF")   # 出典の行は省く
    catalog = load_indicators()
    upsert_indicators(conn, catalog)
    for eid in ("muni-13206", "muni-34208"):   # 都道府県の順に取り込むので広島県が後
        conn.execute("INSERT INTO entities (entity_id, entity_type, name) VALUES (?, 'municipality', '府中市')",
                     (eid,))
    path = tmp_path / "touhyou.csv"
    path.write_text("x,\u3000府中市,100,100,200,50,60,110\n", encoding="utf-8-sig")
    result = tokyo_election.ingest(conn, path, "s", catalog,
                                   {"period": "2024-10-27", "layout": "turnout"})
    assert result["unmatched"] == []
    got = conn.execute("SELECT entity_id, value FROM observations WHERE indicator_id = 'voter_turnout'").fetchall()
    assert [(r["entity_id"], round(r["value"], 1)) for r in got] == [("muni-13206", 55.0)]


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
    # 列名が変わったら0件で書かずに止める
    csv_path.write_text("都道府県コード,事故内容\n30,2\n", encoding="cp932")
    with pytest.raises(ValueError, match="列"):
        npa_traffic.read_accidents(csv_path)


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
    # 私立の割合1つにまとめた（公立・国立は出さない。#75）
    ids = {i["id"] for i in load(built, "indicators.json")["indicators"]}
    assert "jhs_students_public" not in ids and "jhs_students_national" not in ids
    # 都道府県の値は「計」の行から（区市町村の分子分母の合計ではない）
    p = rows("jhs_students_private", "prefectures")["pref-13"]
    assert p["denominator"] == 3000


def test_school_municipal(built):
    def rows(ind, period, level):
        return {r["entity_id"]: r for r in load(built, f"values/{ind}/{period}/{level}.json")["rows"]}
    size = rows("elem_class_size", "2025-05-01", "municipalities")
    # 通常の学級（特別支援学級を除く）: (1000 − 20) ÷ (40 − 4)
    assert abs(size["muni-13199"]["value"] - 980 / 36) < 0.001
    assert size["muni-13199"]["numerator"] == 980 and size["muni-13199"]["denominator"] == 36
    assert size["muni-13499"]["value"] is None and size["muni-13499"]["status"] == "not_applicable"   # 学校なし
    special = rows("elem_special_class_share", "2025-05-01", "municipalities")
    assert special["muni-13299"]["value"] == 2.0
    # 都道府県は「計」の行（区市町村の合計と同じ作り）
    pref = rows("elem_special_class_share", "2025-05-01", "prefectures")["pref-13"]
    assert pref["numerator"] == 50 and pref["denominator"] == 2500
    uni = rows("hs_grad_university_rate", "2025-03-31", "municipalities")
    assert uni["muni-13199"]["value"] == 60.0
    assert uni["muni-13299"]["status"] == "withheld"   # 卒業者が10人未満
    assert rows("hs_grad_vocational_rate", "2025-03-31", "municipalities")["muni-13199"]["value"] == 20.0
    assert rows("hs_grad_employment_rate", "2025-03-31", "municipalities")["muni-14199"]["value"] == 30.0
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    assert by["hs_grad_university_rate"]["periods"][-1]["label"] == "2025年3月卒業"
    assert by["elem_class_size"]["category"] == "教育"


def test_preschool_shares(built):
    rows = {r["entity_id"]: r for r in
            load(built, "values/preschool_kindergarten_share/2020-10-01/municipalities.json")["rows"]}
    r = rows["muni-13199"]
    assert r["value"] is None or abs(r["value"] - r["numerator"] / r["denominator"] * 100) < 0.01
    ids = {i["id"] for i in load(built, "indicators.json")["indicators"]}
    assert {"preschool_kindergarten_share", "preschool_nursery_share", "preschool_kodomoen_share"} <= ids


def test_prefecture_rows_include_withheld():
    # 分母が小さくて値を出さない市区町村も、都道府県の分子・分母の合計には入れる（#109）
    from collections import defaultdict
    from tdm.export import _add_prefecture_rows
    rows = defaultdict(list)
    rows[("municipality", "municipalities")] = [
        {"entity_id": "muni-13101", "value": 50.0, "status": "derived", "numerator": 50.0, "denominator": 100.0},
        {"entity_id": "muni-13362", "value": None, "status": "withheld", "_parts": (3.0, 10.0)},
        {"entity_id": "muni-13999", "value": None, "status": "not_applicable", "_parts": (0.0, 0.0)}]
    munis = {"13": [{"entity_id": e} for e in ("muni-13101", "muni-13362", "muni-13999")]}
    _add_prefecture_rows(rows, {"scale": 100, "digits": 1, "kind": "ratio",
                                "legend": {"method": "quantile"}}, munis)
    pref = rows[("prefecture", "prefectures")][0]
    assert pref["numerator"] == 53 and pref["denominator"] == 110
    # 秘匿などで分子・分母もない市区町村があれば、これまでどおり都道府県の値は出さない
    rows[("municipality", "municipalities")][1] = {"entity_id": "muni-13362", "value": None, "status": "suppressed"}
    rows[("prefecture", "prefectures")] = []
    _add_prefecture_rows(rows, {"scale": 100, "digits": 1, "kind": "ratio",
                                "legend": {"method": "quantile"}}, munis)
    assert rows[("prefecture", "prefectures")][0]["value"] is None



def test_zero_prefectures(built):
    # 県内の市区町村がすべて0の都道府県は凡例に記し、地図で色を付けない（#75）
    found = 0
    for f in (built.releases / "test" / "values").glob("*/*/legend.json"):
        muni = json.loads(f.read_text())["levels"].get("municipality", {})
        for pref in muni.get("zero_prefectures", []):
            rows = json.loads((f.parent / "municipalities.json").read_text())["rows"]
            vals = [r["value"] for r in rows if r["entity_id"][5:7] == pref and r["value"] is not None]
            assert vals and all(v == 0 for v in vals)
            found += 1
    assert found


def test_small_area_rows_have_national_rank(built):
    # 全国の順位は書き出し時に数える（値の大きい順、同値は同順位、値のない地域は数えない）
    base = "values/population_total/2020-10-01"
    rows = load(built, f"{base}/13.json")["rows"] + load(built, f"{base}/14.json")["rows"]
    total = load(built, f"{base}/legend.json")["levels"]["small_area"]["count"]
    valued = [r for r in rows if r["value"] is not None]
    assert len(valued) == total and {r["entity_id"][5:7] for r in valued} == {"13", "14"}
    for r in rows:
        if r["value"] is None:
            assert "national_rank" not in r
        else:
            assert r["national_rank"] == sum(o["value"] > r["value"] for o in valued) + 1
    assert min(r["national_rank"] for r in valued) == 1
    # 東京都だけの指標には入れない（都道府県内の順位と同じため）
    crime = load(built, "values/crime_total/2025-01-01/13.json")["rows"]
    assert crime and all("national_rank" not in r for r in crime)


def test_housing_income_and_vacancy(built):
    def rows(ind, period, level):
        return {r["entity_id"]: r for r in load(built, f"values/{ind}/{period}/{level}.json")["rows"]}
    for year in (2023, 2018):
        vals = fixture.housing_income_values(year)
        classes = fixture.HOUSING_INCOME_CLASSES[year]
        for code in ("13199", "13299", "14199"):
            v = [x or 0 for x in vals[code]]
            low = sum(x for x, c in zip(v, classes) if c.startswith("01_") or "～" in c and int(c[3:].split("～")[1][:-4]) <= 300)
            high = sum(x for x, c in zip(v, classes) if c.endswith(("1000～1500万円未満", "1500万円以上")))
            r = rows("household_income_under300_share", f"{year}-10-01", "municipalities")[f"muni-{code}"]
            assert r["denominator"] == sum(v) and r["numerator"] == low   # 分母は収入階級の合計（不詳を含む総数ではない）
            r = rows("household_income_1000plus_share", f"{year}-10-01", "municipalities")[f"muni-{code}"]
            assert r["numerator"] == high
        # 表に載らない小さい町村は0ではなく値なし
        r = rows("household_income_under300_share", f"{year}-10-01", "municipalities")["muni-13499"]
        assert r["value"] is None and "公表されていません" in r["note"]
        # 都道府県の値は表の都道府県の行（市区町村の合計ではない）
        p = rows("household_income_under300_share", f"{year}-10-01", "prefectures")["pref-13"]
        assert p["denominator"] == sum(vals["13000"])
        total, vacant = fixture.housing_stock_values(year)["13199"]
        r = rows("vacant_house_rate", f"{year}-10-01", "municipalities")["muni-13199"]
        assert r["numerator"] == vacant and r["denominator"] == total
        assert rows("vacant_house_rate", f"{year}-10-01", "municipalities")["muni-13499"]["value"] is None
    # 世帯年収の2つは組にまとめず、別々の指標として一覧から選ぶ（種別の欄は出ない。#106）
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    assert by["household_income_under300_share"]["family"] is None
    assert by["household_income_1000plus_share"]["family"] is None


def test_fertility_and_life_expectancy(built):
    def rows(ind, period, level):
        return {r["entity_id"]: r for r in load(built, f"values/{ind}/{period}/{level}.json")["rows"]}
    tfr = rows("total_fertility_rate", "2018-01-01", "municipalities")
    assert tfr["muni-13199"]["value"] == 0.98 and tfr["muni-14199"]["value"] == 1.31
    assert tfr["muni-13499"]["value"] is None   # 「-」は0にしない
    assert rows("total_fertility_rate", "2018-01-01", "prefectures")["pref-13"]["value"] == 1.11
    ind = next(i for i in load(built, "indicators.json")["indicators"] if i["id"] == "total_fertility_rate")
    assert any(p["label"] == "2018〜2022年" for p in ind["periods"])
    male = rows("life_expectancy_male", "2020-01-01", "municipalities")
    female = rows("life_expectancy_female", "2020-01-01", "municipalities")
    assert male["muni-13199"]["value"] == 82.4 and female["muni-13199"]["value"] == 88.3
    assert rows("life_expectancy_female", "2020-01-01", "prefectures")["pref-14"]["value"] == 87.9


def test_population_history_by_prefecture(built):
    vals = fixture.census_history_values()
    rows = {r["entity_id"]: r for r in load(built, "values/population_history/1920-10-01/prefectures.json")["rows"]}
    assert rows["pref-13"]["value"] == vals["13"][1920]
    r = {r["entity_id"]: r for r in load(built, "values/population_history/1945-10-01/prefectures.json")["rows"]}
    assert r["pref-14"]["value"] is None and r["pref-13"]["value"] == vals["13"][1945]   # 「-」は0にしない
    ind = next(i for i in load(built, "indicators.json")["indicators"] if i["id"] == "population_history")
    assert len(ind["periods"]) == 21


def test_economic_census_matches_town_names(built):
    def rows(ind, level):
        return {r["entity_id"]: r for r in load(built, f"values/{ind}/2021-06-01/{level}.json")["rows"]}
    est = rows("establishments", "municipalities")
    assert est["muni-13199"]["value"] == 120 + 15 + 7 + 3   # 市区町村は「その他」や対応できない行も含めた合計
    emp = rows("employees", "municipalities")
    assert emp["muni-13199"]["value"] == 3400 + 0 + 40 + 12   # 「-」は0
    areas = {r["entity_id"]: r for r in load(built, "values/establishments/2021-06-01/13199.json")["rows"]}
    assert areas["area-13199001001"]["value"] == 120   # 「見本町１丁目」→ 見本町1丁目（全角数字の表記ゆれ）
    assert areas["area-13199001002"]["value"] == 15
    other = areas["area-13199001003"]
    assert other["value"] is None and "対応付けられない" in other["note"]   # 0にしない
    # 丁目に分かれていない町には、丁目の行を合計する
    t = {r["entity_id"]: r for r in load(built, "values/establishments/2021-06-01/13299.json")["rows"]}
    assert t["area-13299090000"]["value"] == 3
    from tdm.ingest.estat_economic_census import town_key
    assert town_key("北三条東１５丁目") == town_key("北3条東15丁目")
    assert town_key("浅香山町１丁") == town_key("浅香山町一丁") and town_key("海澤") == town_key("海沢")


def test_school_table_marks():
    # 学校基本調査の「-」は該当なし（0）、「…」は計数不明なので値なし
    from tdm.ingest.estat_school_municipal import _num
    assert _num(["-", "…", "1,234", 5], 0) == 0.0
    assert _num(["-", "…", "1,234", 5], 1) is None
    assert _num(["-", "…", "1,234", 5], 2) == 1234.0 and _num(["-", "…", "1,234", 5], 3) == 5.0


def test_economic_census_stops_on_suppressed_cells(tmp_path):
    # 秘匿（X）・空欄のセルを0として数えない（2021年の表にはないはずなので、あれば止める）
    from tdm.ingest import estat_economic_census
    conn = connect(":memory:")
    init_schema(conn)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("INSERT INTO entities (entity_id, entity_type, name) VALUES ('muni-13101', 'municipality', '千代田区')")
    catalog = {k: d for k, d in load_indicators().items() if d.get("source_kind") == estat_economic_census.KIND}
    cols = sorted({d["column"] for d in catalog.values()})
    head = "KEY_CODE,CITY_NAME,AZA_CODE,AZA_NAME," + ",".join(cols) + "\n"
    path = tmp_path / "tblT001167C13.txt"
    path.write_text(head + head + "13101000000000001,千代田区,1,丸の内,X" + ",-" * (len(cols) - 1) + "\n",
                    encoding="cp932")
    with pytest.raises(ValueError, match="秘匿"):
        estat_economic_census.ingest(conn, [path], "s", catalog, ("2021-06-01", "2021-06-01", "point"), "v")


def test_economic_census_industries(built):
    """業種別（農林漁業・製造業・卸売業，小売業）の従業者数と、全産業に占める割合。"""
    def rows(ind, level):
        return {r["entity_id"]: r for r in load(built, f"values/{ind}/2021-06-01/{level}.json")["rows"]}
    manu = rows("employees_manufacturing", "municipalities")
    assert manu["muni-13199"]["value"] == 3400 // 4 + 40 // 4 + 12 // 4
    share = rows("employees_manufacturing_share", "13199")
    assert share["area-13199001001"]["value"] == 25.0   # 850 ÷ 3400
    assert share["area-13199001002"]["value"] is None   # 従業者0人の町丁目は割合を出さない
    comm = rows("employees_commerce_share", "municipalities")
    assert round(comm["muni-13199"]["value"], 3) == round((1133 + 13 + 4) / 3452 * 100, 3)
    agri = rows("employees_agriculture", "13199")
    assert agri["area-13199001001"]["value"] == 340
    inds = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    assert inds["employees_manufacturing"]["family"] == inds["employees_manufacturing_share"]["family"]
    assert inds["employees_commerce"]["category"] == "商業"


def test_agri_output(built):
    """農業産出額: 千万円→億円、「-」は0、「x」「…」は値なし、23区・政令指定都市の区には値を入れない。"""
    def rows(ind, year, level):
        return {r["entity_id"]: r for r in load(built, f"values/{ind}/{year}-01-01/{level}.json")["rows"]}
    m = rows("agri_output", 2024, "municipalities")
    assert m["muni-13299"]["value"] == 1.2 and m["muni-13499"]["value"] == 0.5
    assert "muni-13199" not in m or m["muni-13199"]["value"] is None   # 23区は「特別区」全体の値だけ
    assert "muni-14199" not in m or m["muni-14199"]["value"] is None   # 政令指定都市の区
    assert rows("agri_output", 2023, "municipalities")["muni-13299"]["value"] == 1.1
    rice = rows("agri_output_rice", 2024, "municipalities")
    assert rice["muni-13299"]["value"] is None and rice["muni-13499"]["value"] == 0   # x は値なし、- は0
    assert rows("agri_output_livestock", 2024, "municipalities")["muni-13499"]["value"] is None   # …
    p = rows("agri_output", 2024, "prefectures")
    assert p["pref-13"]["value"] == 4.7   # 特別区・ためし市・かりの村の合計
    assert p["pref-14"]["value"] == 4.0
    assert rows("agri_output_rice", 2024, "prefectures")["pref-13"]["value"] is None   # 県内に秘匿があれば合計しない


def test_manufacturing_shipments(built):
    def rows(level):
        return {r["entity_id"]: r for r in load(built, f"values/manufacturing_shipments/2024-01-01/{level}.json")["rows"]}
    m = rows("municipalities")
    assert m["muni-13199"]["value"] == 25.0   # 万円→億円
    assert m["muni-13299"]["value"] is None   # X（秘匿）は0にしない
    assert m["muni-13499"]["value"] == 0      # ***（事業所なし）は0
    assert m["muni-14199"]["value"] == 12.0   # 政令指定都市は区の行を使う
    p = rows("prefectures")
    assert p["pref-13"]["value"] == 50.0 and p["pref-14"]["value"] == 80.0   # 都道府県の行


def test_commerce_sales(built):
    def rows(ind, level):
        return {r["entity_id"]: r for r in load(built, f"values/{ind}/2020-01-01/{level}.json")["rows"]}
    r = rows("retail_sales", "municipalities")
    assert r["muni-13199"]["value"] == 70.0 and r["muni-13499"]["value"] == 0.12 and r["muni-14199"]["value"] == 8.0
    w = rows("wholesale_sales", "municipalities")
    assert w["muni-13499"]["value"] is None and w["muni-13299"]["value"] == 40.0
    assert rows("retail_sales", "prefectures")["pref-13"]["value"] == 90.0
    pc = rows("retail_sales_per_capita", "municipalities")["muni-13199"]
    assert pc["value"] is not None and pc["value"] > 0
    inds = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    assert inds["retail_sales"]["category"] == "商業" and inds["agri_output"]["category"] == "農業"


def test_land_survey_points(built):
    data = load(built, "places/land_survey_price.json")
    pts = {p["id"]: p for p in data["points"]}
    assert set(pts) == {"landsv-13199-000-001", "landsv-13299-005-001"}
    p = pts["landsv-13199-000-001"]
    assert p["name"] == "サンプル(都)-1" and pts["landsv-13299-005-001"]["name"] == "ためし(都)5-1"
    periods = [x["period"] for x in data["periods"]]
    assert periods[0] == "1983-07-01" and periods[-1] == "2025-07-01"
    assert pts["landsv-13299-005-001"]["values"][periods.index("2009-07-01")] is None   # 基準地でなかった年は0円にしない
    # 地価公示の点には混ざらない
    assert not any(x["id"].startswith("landsv-") for x in load(built, "places/land_price.json")["points"])
    assert data["source_ids"] != load(built, "places/land_price.json")["source_ids"]


def test_npa_crime_stats_prefecture_values(built):
    # 警察庁「犯罪統計」の都道府県別。北海道は「計」の行、東京都は2列目が空の行
    for ind, k in (("crime_npa_total", 0), ("crime_npa_theft", 1), ("crime_npa_serious", 2)):
        rows = {r["entity_id"]: r for r in load(built, f"values/{ind}/2025-01-01/prefectures.json")["rows"]}
        assert rows["pref-13"]["value"] == fixture.npa_crime_values(2025, "13")[k]
        assert rows["pref-14"]["value"] == fixture.npa_crime_values(2025, "14")[k]
    meta = next(i for i in load(built, "indicators.json")["indicators"] if i["id"] == "crime_npa_total")
    assert [p["period"] for p in meta["periods"]][-1] == "2021-2025"
    assert meta["periods"][-1]["levels"] == ["prefecture"]
    five = {r["entity_id"]: r for r in load(built, "values/crime_npa_total/2021-2025/prefectures.json")["rows"]}
    assert five["pref-13"]["value"] == sum(fixture.npa_crime_values(y, "13")[0] for y in range(2021, 2026))
    rate = {r["entity_id"]: r for r in load(built, "values/crime_npa_total_per_100_residents/2025-01-01/prefectures.json")["rows"]}
    assert rate["pref-13"]["numerator"] == fixture.npa_crime_values(2025, "13")[0] and rate["pref-13"]["denominator"] > 0


def test_npa_crime_stats_checks_national_total(tmp_path):
    from tdm.ingest.npa_crime_stats import read_tables
    fixture._write_npa_crime_stats(tmp_path)
    path = tmp_path / "npa_crime_stats_2025" / "npa_crime_stats_2025.csv"
    assert read_tables(path)[3]["01"] == fixture.npa_crime_values(2025, "01")[0]   # 方面ごとの行は使わない
    path.write_bytes(path.read_bytes().replace("全国,,".encode("cp932"), "全国,,1".encode("cp932"), 1))
    with pytest.raises(ValueError, match="全国"):
        read_tables(path)


def test_police_crime_opendata_counts(built):
    # 窃盗7手口: 市区町村は年ごと、町丁目は5年合計だけ
    def rows(ind, period, chunk):
        return {r["entity_id"]: r for r in load(built, f"values/{ind}/{period}/{chunk}.json")["rows"]}
    munis = rows("street_crime_total", "2025-01-01", "municipalities")
    assert munis["muni-13199"]["value"] == 4 * 7            # 町丁目が空の行も市区町村には入る
    assert munis["muni-13499"]["value"] == 0                # 行のない市区町村は0件
    assert munis["muni-14199"]["value"] == 7
    assert rows("street_crime_total", "2025-01-01", "prefectures")["pref-13"]["value"] == 7 * 7
    meta = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    total = meta["street_crime_total"]
    assert all(p["levels"] == ["municipality", "prefecture"] for p in total["periods"] if not p["aggregate"])
    assert total["default_period"] == "2021-2025"           # 町丁目の値は5年合計にだけある
    assert not (built.releases / "test" / "values/street_crime_total/2025-01-01/13.json").exists()
    areas = rows("street_crime_total", "2021-2025", "13")
    assert areas["area-13199001001"]["value"] == 2 * 7 * 5  # 「見本町１丁目」（全角数字の表記ゆれ）
    assert areas["area-13199001002"]["value"] == 7 * 5      # 「見本町一丁目二」
    assert areas["area-13199001003"]["value"] is None       # 町丁目が空の行が5%を超えるので、記録のない町丁目も値なし
    assert areas["area-13299090000"]["value"] == 7 * 5      # 丁目の行を、地図では丁目に分かれていない町にまとめる
    assert areas["area-13299003003"]["value"] == 7 * 5      # 地図にない町名は、位置参照情報の代表点が入る小地域へ
    assert areas["area-13299001002"]["value"] == 0          # 対応できない行がないので、記録のない町丁目は0件
    bike = rows("street_crime_bicycle", "2021-2025", "13")
    assert bike["area-13199001001"]["value"] == 2 * 5
    rate = rows("street_crime_total_per_100_residents", "2021-2025", "municipalities")["muni-13199"]
    assert rate["numerator"] == 4 * 7 * 5


def test_police_crime_opendata_uncertain_towns(tmp_path):
    # 地図のほうが細かい町は割り振らずに値なし、名前の合わない行が多い市区町村は記録のない町丁目も値なし
    from tdm.ingest import police_crime_opendata as od
    conn = connect(":memory:")
    init_schema(conn)
    conn.execute("PRAGMA foreign_keys = OFF")
    catalog = {k: d for k, d in load_indicators().items() if k == "street_crime_bicycle"}
    upsert_indicators(conn, catalog)
    conn.execute("INSERT INTO entities (entity_id, entity_type, name) VALUES ('muni-27999', 'municipality', '見本市')")
    for i, name in enumerate(["本町１丁目", "本町２丁目", "栄町", "緑町"]):
        eid = f"area-27999{i:06d}"
        conn.execute("INSERT INTO entities (entity_id, entity_type, name, parent_id) VALUES (?, 'small_area', ?, 'muni-27999')",
                     (eid, name))
        conn.execute("INSERT INTO boundaries (boundary_id, boundary_version, entity_id, reference_date, source_id, "
                     "geometry, bbox_west, bbox_south, bbox_east, bbox_north) VALUES (?, 'b', ?, '2020', 's', '{}', 0, 0, 0, 0)",
                     (f"b:{eid}", eid))
    head = "罪名,手口,市区町村コード（発生地）,市区町村（発生地）,町丁目（発生地）\n"
    for y in range(2021, 2026):
        body = head + "窃盗,自転車盗,279994,見本市,本町\n" + "窃盗,自転車盗,279994,見本市,大字栄町\n" * 30
        (tmp_path / f"{y}_zitensyatou.csv").write_text(body, encoding="cp932")
    files = sorted(tmp_path.glob("*.csv"))
    od.ingest(conn, files, "s", catalog, "27", list(range(2021, 2026)), "b")
    got = {r["entity_id"]: (r["value"], r["method_note"]) for r in conn.execute(
        "SELECT entity_id, value, method_note FROM observations WHERE period_kind = 'multi_year'")}
    assert got["area-27999000000"][0] is None and "割り振れない" in got["area-27999000000"][1]
    assert got["area-27999000002"][0] == 150                # 「大字栄町」→ 栄町
    assert got["area-27999000003"][0] == 0                  # 名前の合わない行は5%以下


def test_police_crime_opendata_reorganized_wards(tmp_path):
    # 区を再編した市（浜松市は2024年1月）は、地図にない新しい区の行がある年の区と、その年を含む5年合計の町丁目を値なしにする
    from tdm.ingest import police_crime_opendata as od
    conn = connect(":memory:")
    init_schema(conn)
    conn.execute("PRAGMA foreign_keys = OFF")
    catalog = {k: d for k, d in load_indicators().items() if k == "street_crime_bicycle"}
    upsert_indicators(conn, catalog)
    for eid, kind, name, parent in [("muni-22131", "municipality", "浜松市中区", None),
                                    ("muni-22132", "municipality", "浜松市東区", None),
                                    ("muni-22203", "municipality", "沼津市", None),
                                    ("area-22131000001", "small_area", "元城町", "muni-22131"),
                                    ("area-22203000001", "small_area", "大手町", "muni-22203")]:
        conn.execute("INSERT INTO entities (entity_id, entity_type, name, parent_id) VALUES (?, ?, ?, ?)",
                     (eid, kind, name, parent))
        conn.execute("INSERT INTO boundaries (boundary_id, boundary_version, entity_id, reference_date, source_id, "
                     "geometry, bbox_west, bbox_south, bbox_east, bbox_north) VALUES (?, 'b', ?, '2020', 's', '{}', 0, 0, 0, 0)",
                     (f"b:{eid}", eid))
    head = "罪名,手口,市区町村コード（発生地）,市区町村（発生地）,町丁目（発生地）\n"
    for y in range(2021, 2026):
        body = head + "窃盗,自転車盗,222038,沼津市,大手町\n"
        body += ("窃盗,自転車盗,221384,浜松市中央区,元城町\n" if y >= 2024 else "窃盗,自転車盗,221317,浜松市中区,元城町\n")
        (tmp_path / f"{y}_zitensyatou.csv").write_text(body, encoding="cp932")
    result = od.ingest(conn, sorted(tmp_path.glob("*.csv")), "s", catalog, "22", list(range(2021, 2026)), "b")
    assert result["reorganized"] == {2024: ["浜松市"], 2025: ["浜松市"]}
    got = {(r["entity_id"], r["period_start"][:4], r["period_kind"]): r["value"] for r in conn.execute(
        "SELECT entity_id, period_start, period_kind, value FROM observations")}
    assert got[("muni-22131", "2023", "calendar_year")] == 1
    assert got[("muni-22131", "2024", "calendar_year")] is None    # 0件にしない
    assert got[("muni-22132", "2025", "calendar_year")] is None
    assert got[("muni-22203", "2025", "calendar_year")] == 1       # ほかの市は変わらない
    assert got[("area-22131000001", "2021", "multi_year")] is None
    assert got[("area-22203000001", "2021", "multi_year")] == 5


def test_police_crime_opendata_tab_and_old_town_names(tmp_path):
    # タブ区切りのファイルを読み、地図で省かれた旧町名（「水口町本町２丁目」→地図「本町二丁目」）は末尾で対応付ける
    from tdm.ingest import police_crime_opendata as od
    head = "罪名\t手口\t市区町村コード（発生地）\t市区町村（発生地）\t町丁目（発生地）\n"
    data = (head + "窃盗\t自転車盗\t252093\t甲賀市\t水口町本町２丁目\n").encode("cp932")
    assert od.read_incidents(data) == [("25209", "甲賀市", "水口町本町２丁目", 1)]
    assert od.detect_technique(data) == "zitensyatou"
    areas = {od.town_key("本町二丁目"): ["a1"], od.town_key("新町"): ["a2"], od.town_key("松涛一丁目"): ["a3"]}
    assert od._area_ids(areas, od.town_key("水口町本町２丁目")) == ["a1"]
    assert od._area_ids(areas, od.town_key("西新町")) == []          # 前に残る部分が旧町村名に見えないものは対応付けない
    assert od._area_ids(areas, od.town_key("松濤1丁目")) == ["a3"]   # 字体の違い
    assert od.town_key("中町4丁目丁目") == od.town_key("中町四丁目")
    areas[od.town_key("浄水町")] = ["a4"]
    assert od._area_ids(areas, od.town_key("浄水町伊保原")) == ["a4"]   # 小字まで書いた行は地図の町にまとめる
    assert od._area_ids(areas, od.town_key("浄水町字南平")) == ["a4"]
    assert od._area_ids(areas, od.town_key("浄水町通1丁目")) == []
    assert od.town_key("曾根崎新地1丁目") == od.town_key("曽根崎新地一丁目")   # 旧字体


def test_police_crime_opendata_file_shapes(tmp_path):
    # 発生なしの年は「問合せの結果に行はありません」だけのファイル。ZIP の中の CSV は名前が読めなくても1つなら使う
    import zipfile
    from tdm.ingest import police_crime_opendata as od
    assert od.read_incidents("\ufeff問合せの結果に行はありません".encode("utf-8")) == []
    head = "罪名,手口,市区町村コード（発生地）,市区町村（発生地）,町丁目（発生地）\n"
    body = (head + "窃盗,車上ねらい,342025,呉市,本町\n").encode("cp932")
    with zipfile.ZipFile(tmp_path / "2023_syazyounerai.csv", "w") as z:
        z.writestr("\x93\x8c.csv", body)   # 文字化けした日本語のファイル名
    got = od._files_by_year([tmp_path / "2023_syazyounerai.csv"])
    assert od.read_incidents(got[2023]["syazyounerai"]) == [("34202", "呉市", "本町", 1)]
    # Excel の数値のセル（件数の列など）は「3.0」を30と読まない
    from tdm.xlsx import write_sheets
    write_sheets(tmp_path / "2024_syazyounerai.xlsx",
                 {"Sheet1": [["罪名", "市区町村コード（発生地）", "市区町村（発生地）", "町丁目（発生地）", "件数"],
                             ["窃盗", "342025", "呉市", "本町", 3.0]]})
    data = od._sheet_as_csv(tmp_path / "2024_syazyounerai.xlsx")
    assert od.read_incidents(data) == [("34202", "呉市", "本町", 3)]


def test_weather_normals(built):
    data = load(built, "places/weather_normals.json")
    st = {s["id"]: s for s in data["stations"]}
    assert set(st) == {"wx-44901", "wx-44902", "wx-46901"}   # 地図の範囲外の観測所は取り込まない
    assert [e["id"] for e in data["elements"]] == [
        "sunshine_normal", "precipitation_normal", "snow_depth_normal", "snowfall_normal"]
    s = st["wx-44901"]
    assert s["name"] == "見本" and s["municipality_id"] == "muni-13199"
    assert s["coord"] == [139.72, 35.68]   # 度・分から度に直す
    assert s["values"] == {"sunshine_normal": 1923, "precipitation_normal": 1599,
                           "snow_depth_normal": 6, "snowfall_normal": 8}   # 0.1時間・0.1mm を直す
    assert s["monthly"]["precipitation_normal"][8] == 225
    # 統計値なし（品質0）は値なしにし、0 にしない。統計期間の短い観測所は期間を持つ
    t = st["wx-44902"]
    assert set(t["values"]) == {"precipitation_normal"} and t["years"]["precipitation_normal"] == [2003, 2020, 18]
    # 雪の降らない観測所の正常値 0cm は 0 として載せる
    assert st["wx-46901"]["values"]["snow_depth_normal"] == 0
    assert any(x.startswith("jma_normals_2020@") for x in data["source_ids"])
    # 観測所の値は地域に割り振らない
    assert not any(i["id"].endswith("_normal") for i in load(built, "indicators.json")["indicators"])


def test_prefecture_denominator_ignores_municipalities_without_rows():
    # 分母の指標に行のない区市町村（今はない市区町村など）があっても、都道府県の分母は区市町村の合計で作る
    from tdm.derive import _add_prefecture_denominators
    den = {("muni-13101", None): {"value": 10.0, "source_id": "s"},
           ("muni-13102", None): {"value": 5.0, "source_id": "s"}}
    types = {"muni-13101": "municipality", "muni-13102": "municipality", "muni-13100": "municipality"}
    _add_prefecture_denominators(den, types)
    assert den[("pref-13", None)]["value"] == 15.0
    den = {("muni-13101", None): {"value": 10.0, "source_id": "s"},
           ("muni-13102", None): {"value": None, "source_id": "s"}}
    _add_prefecture_denominators(den, types)
    assert ("pref-13", None) not in den                     # 値のない区市町村があれば作らない


def test_school_aid_rate(built):
    """就学援助率: 文部科学省の PDF（見本はテキスト）の5%刻みの区分を、区分の上の端の値で持つ（#106）。"""
    from tdm.ingest.mext_school_aid import read_rates
    year, rates = read_rates((built.raw / "mext_school_aid_2024" / "13" / "13.txt").read_text(encoding="utf-8"))
    assert year == 2024 and rates[("東京都", "サンプル区")] == 20
    # 上下に折り返された名前をつなぐ。郡名・「役場」付きの名前は取り込むときに市区町村と突き合わせる
    assert rates[("東京都", "ためし市")] == 10 and rates[("東京都", "見本郡かりの村役場")] == 0
    by = {i["id"]: i for i in load(built, "indicators.json")["indicators"]}
    aid = by["school_aid_rate"]
    assert [p["label"] for p in aid["periods"]] == ["2021年度", "2022年度", "2023年度", "2024年度"]
    assert all(p["levels"] == ["municipality"] for p in aid["periods"])   # 都道府県の値は作らない
    rows = {r["entity_id"]: r for r in load(built, "values/school_aid_rate/2024-04-01/municipalities.json")["rows"]}
    assert rows["muni-13199"]["value"] == 20 and rows["muni-13299"]["value"] == 10
    assert rows["muni-13499"]["value"] == 0                    # 「0%未満」は0%（援助を受けた子どもがいない）
    assert rows.get("muni-14199", {}).get("value") is None     # 政令指定都市の区には割り振らない
    old = {r["entity_id"]: r for r in load(built, "values/school_aid_rate/2021-04-01/municipalities.json")["rows"]}
    assert old["muni-13299"]["value"] is None                  # 区分の欄が空なら0ではなく値なし
    # 凡例は区分ごとに1色（全時点の最大の区分まで5%ごと）
    legend = load(built, "values/school_aid_rate/2024-04-01/legend.json")
    assert legend["levels"]["municipality"]["breaks"] == [5, 10, 15, 20]


def test_gsi_port_alias(tmp_path):
    """港湾統計と地名で名前が違う港は「<都道府県>_<港名>@<地名>.json」の地名で引く。"""
    import json
    from tdm.ingest.mlit_transport import read_gsi_ports
    f = tmp_path / "13_青ヶ島@三宝港.json"
    f.write_text(json.dumps([{"geometry": {"coordinates": [139.76, 32.45]}, "properties": {"title": "三宝港"}},
                             {"geometry": {"coordinates": [139.0, 32.0]}, "properties": {"title": "青ヶ島港"}}],
                            ensure_ascii=False), encoding="utf-8")
    assert read_gsi_ports(f) == {("13", "青ヶ島"): [(139.76, 32.45, None)]}


def test_airports_and_ports(built):
    import hashlib
    h = lambda s: hashlib.sha1(s.encode()).hexdigest()[:8]
    air = load(built, "places/airport_passengers.json")
    assert [p["label"] for p in air["periods"]] == ["2024年", "2025年"]
    pts = {p["name"]: p for p in air["points"]}
    # 地図の範囲外（遠く）とどの年も乗降客数が0の空港（ゼロ）は出さない。C28 にない空港（ない）は国土地理院の地名の位置
    assert set(pts) == {"見本国際", "かりの", "ない"}
    assert pts["ない"]["coord"] == [139.68, 35.7] and any(s.startswith("gsi_airport_names@") for s in air["source_ids"])
    a = pts["見本国際"]
    assert a["id"] == f"airport-{h('見本')}" and a["municipality_id"] == "muni-13199"
    assert a["coord"] == [139.731, 35.69]   # 国土数値情報の空港標点
    # 12か月の合計。国際線は乗客・降客・通過客の小計
    assert a["values"] == [145200, 170400] and a["domestic"] == [120000, 120000] and a["international"] == [25200, 50400]
    # 月の値が欠けた年は値なし（0 にしない）
    assert pts["かりの"]["values"] == [7200, None] and pts["かりの"]["international"] == [0, None]
    assert any(s.startswith("mlit_c28_2021@") for s in air["source_ids"])

    port = load(built, "places/port_passengers.json")
    assert [p["label"] for p in port["periods"]] == ["2023年", "2024年"]
    pp = {p["name"]: p for p in port["points"]}
    # どの年も乗降のない港は出さない。港名と同じ名前の都道府県（東京）も港として読む
    assert set(pp) == {"東京", "見本", "みほん", "ない"}
    # Wikidata にない港は国土地理院の地名から。ほかの都道府県の同じ名前の地名は使わない
    assert pp["ない"]["coord"] == [139.67, 35.69] and any(s.startswith("gsi_port_names@") for s in port["source_ids"])
    t = pp["東京"]
    assert t["id"] == f"port-13-{h('東京')}" and t["coord"] == [139.75, 35.7]   # 大阪府の同名の港と取り違えない
    assert t["values"] == [1200, 1500] and t["domestic"] == [1200, 1400]
    assert t["international"] == [None, 100]   # 外国航路の行がない年は値なし
    assert pp["みほん"]["municipality_id"] == "muni-14199"
    assert any(s.startswith("wikidata_ports@") for s in port["source_ids"])
    assert not any(s.startswith("mlit_airports") for s in port["source_ids"])
    # 空港・港の値は地域に割り振らない
    ids = {i["id"] for i in load(built, "indicators.json")["indicators"]}
    assert not ids & {"airport_passengers", "port_passengers"}
