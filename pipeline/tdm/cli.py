"""コマンドライン: python -m tdm <command>

  init        管理用DBを作る
  fetch       出典ファイルを取得する（download_url がない出典は取得先を案内する）
  ingest      data/raw の元ファイルを取り込み、派生指標を計算する
  validate    DBの内容を検証する
  export      公開用ファイルを生成する
  build       ingest → validate → export を続けて実行する
  fixture     架空データで build を実行する（開発・CI用）
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import tempfile
from datetime import datetime
from pathlib import Path

from . import fixture
from .config import DEFAULT_PATHS, Paths, load_censuses, load_indicators, load_sources
from .db import (connect, create_secondary_indexes, drop_secondary_indexes, init_schema, tune_for_bulk_load,
                 upsert_indicators)
from .derive import derive_change, derive_density, derive_multi_year_sum, derive_rate
from .export import comparable_areas, export_release
from .fetch import FetchError, fetch_source, source_prefectures
from .ingest import (estat_boundary, estat_census_history, estat_census_municipal, estat_foreign, estat_housing,
                     estat_economic_census, estat_school_basic,
                     estat_small_area, mhlw_vital,
                     keishicho_crime, mlit_facilities, mlit_inbound, mlit_landprice, mlit_stations, nier_gakuryoku,
                     npa_traffic, soumu_furusato, soumu_tax, tokyo_childcare, tokyo_daytime, tokyo_election,
                     tokyo_foreign, tokyo_jhs_progress, tokyo_nurseries, tokyo_schools, tokyo_street_trees)
from .regions import selected_prefectures
from .sources import find_files, register_source
from .validate import validate
from .progress import progress

def cmd_fetch(paths: Paths, keys: list[str]) -> int:
    sources = load_sources()
    prefs = selected_prefectures()
    failed = 0
    for key in keys or list(sources):
        started = time.monotonic()
        try:
            files = fetch_source(key, sources[key], paths.raw / key, prefs=prefs)
        except (FetchError, OSError) as e:
            print(f"取得失敗: {e}", file=sys.stderr)
            failed += 1
            continue
        print(f"[{key}] {len(files)} ファイルを取得しました（{time.monotonic() - started:.0f} 秒）")
        for f in files[:12]:
            print(f"  {f.relative_to(paths.raw / key)} ({f.stat().st_size:,} bytes)")
        if len(files) > 12:
            print(f"  …ほか {len(files) - 12} ファイル")
    return 1 if failed else 0


def ingest_all(paths: Paths, overrides: dict | None = None, prefs: list[str] | None = None) -> dict:
    sources, catalog, censuses = load_sources(), load_indicators(), load_censuses()
    prefs = prefs or selected_prefectures()
    conn = connect(paths.db)
    tune_for_bulk_load(conn)
    init_schema(conn)
    drop_secondary_indexes(conn)
    upsert_indicators(conn, catalog)
    result: dict = {}
    with conn:
        # 古い時点から取り込み、地域名は最新の境界の名称で上書きされるようにする
        for census in censuses:
            latest = census is censuses[-1]
            try:
                result.update(_ingest_census(conn, paths, census, sources, catalog, overrides, prefs))
            except FileNotFoundError as e:
                if latest:
                    raise
                # 過去の時点の元ファイルがなければ、その時点を除いて続ける
                result[census["label"]] = f"元ファイルがないため除外（{e}）"
        # 前回からの増減率は全時点を取り込んだあとに計算する（境界の比較に最新の境界を使う）
        progress("国勢調査の取込が終わった")
        latest_version = censuses[-1]["boundary_version"]
        comparable = {c["period"]: comparable_areas(conn, c["boundary_version"], latest_version)
                      for c in censuses[:-1]}
        for indicator_id, d in catalog.items():
            if d["kind"] == "change":
                result[indicator_id] = derive_change(conn, indicator_id, d, catalog[d["base"]],
                                                     censuses, comparable)
        progress("増減率を計算した")
        # 市区町村の値だけの国勢調査（2025年）。最新の境界の面積で人口密度、前回の調査からの増減率を出す
        result.update(_ingest_municipal_census(conn, paths, sources, catalog, overrides, censuses[-1]))
        # 国勢調査以外の出典（犯罪・交通事故・昼間人口・駅など）。地域IDは最新の境界の町丁・字等を使う
        result.update(_ingest_other_sources(conn, paths, sources, catalog, overrides,
                                            latest_version, prefs))
        progress("国勢調査以外の出典を取り込んだ")
        # 複数年の合計（例: 犯罪の5年合計）は率より先に作り、率も合計から計算する
        for indicator_id, d in catalog.items():
            if d.get("multi_year_total"):
                result[f"{indicator_id} 合計"] = derive_multi_year_sum(
                    conn, indicator_id, d, int(d["multi_year_total"]))
        for indicator_id, d in catalog.items():
            if d.get("denominator_indicator"):
                result[indicator_id] = derive_rate(conn, indicator_id, d, catalog)
        progress("率を計算した")
        create_secondary_indexes(conn)
        progress("索引を作った")
    conn.close()
    return result


def _ingest_municipal_census(conn, paths: Paths, sources: dict, catalog: dict,
                        overrides: dict | None, last_census: dict) -> dict:
    result: dict = {}
    for key, cfg in sources.items():
        if cfg.get("kind") != "census_municipal":
            continue
        files = find_files(paths.raw / key, cfg["files"])
        if not files:
            result[key] = "元ファイルがないため除外"
            continue
        src = register_source(conn, key, cfg, files, overrides)
        table = estat_census_municipal.read_table(files[0], cfg["columns"], cfg.get("filters"))
        period = (cfg["period"], cfg["period"], "point")
        for indicator_id, d in catalog.items():
            if d.get("table") != cfg["table"]:
                continue
            fn = (estat_small_area.ingest_ratio if d["kind"] == "ratio"
                  else estat_small_area.ingest_counts)
            result[f"{key} {indicator_id}"] = fn(conn, table, src, indicator_id, d, period)
        pseudo = {"period": cfg["period"], "label": cfg.get("label", cfg["period"][:4] + "年"),
                  "boundary_version": last_census["boundary_version"]}
        for indicator_id, d in catalog.items():
            if d["kind"] == "density" and catalog[d["numerator"]].get("table") == cfg["table"]:
                result[f"{key} {indicator_id}"] = {"rows": derive_density(
                    conn, indicator_id, d, catalog[d["numerator"]], last_census["boundary_version"],
                    cfg["period"])}
            elif d["kind"] == "change" and catalog[d["base"]].get("table") == cfg["table"]:
                # 前回（最新の小地域まである国勢調査）→ 今回。今回は市区町村だけなので境界の比較は要らない
                result[f"{key} {indicator_id}"] = derive_change(
                    conn, indicator_id, d, catalog[d["base"]], [last_census, pseudo], {})
    return result


def _ingest_other_sources(conn, paths: Paths, sources: dict, catalog: dict,
                          overrides: dict | None, boundary_version: str, prefs: list[str]) -> dict:
    result: dict = {}
    school_tables: list[dict] = []
    tree_files: list[tuple] = []
    nursery_files: list[tuple] = []
    gazetteers: dict = {}
    traffic_indexes: dict = {}   # 交通事故の年ごとのファイルで境界の索引を使い回す
    for key, cfg in sources.items():
        kind = cfg.get("kind")
        if kind not in ("keishicho_crime", "tokyo_daytime", "mlit_stations", "tokyo_schools",
                        "isj_gazetteer", "tokyo_foreign", "npa_traffic", "mlit_landprice",
                        "soumu_tax", "tokyo_childcare", "tokyo_street_trees", "tokyo_election",
                        "tokyo_nurseries", "soumu_furusato", "tokyo_jhs_progress", "mlit_inbound",
                        "nier_gakuryoku", "estat_school_basic", "mlit_schools", "mlit_nurseries",
                        "soumu_juki_foreign", "moj_zairyu_foreign", "estat_housing_income",
                        "estat_housing_stock", "mhlw_tfr", "mhlw_life_table", "estat_census_history",
                        "estat_economic_census", "mlit_landsurvey"):
            continue
        if cfg.get("per_prefecture"):
            # 都道府県ごとの出典は、今回の対象の都道府県のファイルだけを使う（キャッシュにほかの都道府県があっても）
            files = [f for fs in _prefecture_files(paths, key, cfg, prefs).values() for f in fs]
        else:
            files = find_files(paths.raw / key, cfg["files"])
        if not files:
            result[key] = "元ファイルがないため除外"
            continue
        src = register_source(conn, key, cfg, files, overrides)
        progress(f"取込: {key}")
        if kind == "tokyo_schools":
            school_tables += tokyo_schools.tables_of(files, cfg, src)
        elif kind == "isj_gazetteer":
            gazetteers[cfg.get("level", "block")] = (files[0], src)
        elif kind == "keishicho_crime":
            y = cfg["year"]
            period = (f"{y}-01-01", f"{y}-12-31", "calendar_year")
            result[key] = keishicho_crime.ingest(conn, files[0], src, catalog, period,
                                                 cfg.get("encoding", "cp932"))
        elif kind == "npa_traffic":
            y = cfg["year"]
            period = (f"{y}-01-01", f"{y}-12-31", "calendar_year")
            result[key] = npa_traffic.ingest(conn, files[0], src, catalog, period, boundary_version,
                                             cfg.get("encoding", "cp932"), source_prefectures(cfg, prefs),
                                             traffic_indexes)
        elif kind == "tokyo_foreign":
            period = (cfg["period"], cfg["period"], "point")
            result[key] = tokyo_foreign.ingest(conn, files[0], src, catalog, period,
                                               cfg.get("encoding", "utf-8-sig"))
        elif kind == "soumu_juki_foreign":
            result[key] = estat_foreign.ingest_juki(conn, files[0], src, catalog,
                                                    (cfg["period"], cfg["period"], "point"))
        elif kind == "moj_zairyu_foreign":
            result[key] = estat_foreign.ingest_zairyu(conn, files[0], src, catalog,
                                                      (cfg["period"], cfg["period"], "point"), cfg.get("sheet"))
        elif kind == "estat_housing_income":
            result[key] = estat_housing.ingest_income(conn, files[0], src, catalog,
                                                      (cfg["period"], cfg["period"], "point"))
        elif kind == "estat_housing_stock":
            result[key] = estat_housing.ingest_stock(conn, files[0], src, catalog,
                                                     (cfg["period"], cfg["period"], "point"))
        elif kind == "estat_economic_census":
            result[key] = estat_economic_census.ingest(conn, files, src, catalog,
                                                       (cfg["period"], cfg["period"], "point"),
                                                       boundary_version, cfg.get("encoding", "cp932"))
        elif kind == "estat_census_history":
            result[key] = estat_census_history.ingest(conn, files[0], src, catalog)
        elif kind == "mhlw_tfr":
            # ベイズ推定の合計特殊出生率は5年分の出生をまとめた1つの値。multi_year（年計の合計）とは違い、
            # スライドバーの時点として並べたいので年の時点として扱い、表示名は period_labels で付ける
            result[key] = mhlw_vital.ingest_tfr(conn, files[0], src, catalog,
                                                (f"{cfg['first_year']}-01-01", f"{cfg['last_year']}-12-31",
                                                 "calendar_year"))
        elif kind == "mhlw_life_table":
            y = cfg["year"]
            result[key] = mhlw_vital.ingest_life_table(conn, files[0], src, catalog,
                                                       (f"{y}-01-01", f"{y}-12-31", "calendar_year"))
        elif kind == "tokyo_street_trees":
            tree_files.append((src, files[0], cfg.get("encoding", "cp932"), cfg["period"]))
        elif kind == "tokyo_nurseries":
            nursery_files.append((key, files[0], src, cfg))
        elif kind == "tokyo_childcare":
            result[key] = tokyo_childcare.ingest(conn, files[0], src, catalog, cfg["years"])
        elif kind == "tokyo_election":
            result[key] = tokyo_election.ingest(conn, files[0], src, catalog, cfg)
        elif kind == "tokyo_jhs_progress":
            result[key] = tokyo_jhs_progress.ingest(conn, files[0], src, catalog,
                                                    (cfg["period"], cfg["period"], "point"))
        elif kind == "soumu_furusato":
            result[key] = soumu_furusato.ingest(conn, files[0], src, catalog)
        elif kind == "mlit_inbound":
            result[key] = mlit_inbound.ingest(conn, files[0], src, catalog, int(cfg["year"]))
        elif kind == "nier_gakuryoku":
            result[key] = nier_gakuryoku.ingest(conn, files, src, catalog, cfg["school"],
                                                (cfg["period"], cfg["period"], "point"))
        elif kind == "estat_school_basic":
            result[key] = estat_school_basic.ingest(conn, files, src, catalog,
                                                    (cfg["period"], cfg["period"], "point"), prefs)
        elif kind == "soumu_tax":
            y = int(cfg["fiscal_year"])
            result[key] = soumu_tax.ingest(conn, files[0], src, catalog,
                                           (f"{y}-04-01", f"{y + 1}-03-31", "fiscal_year"),
                                           source_prefectures(cfg, prefs))
        elif kind in ("mlit_landprice", "mlit_landsurvey"):   # 地価公示（L01）・都道府県地価調査（L02）
            for indicator_id, d in catalog.items():
                if d.get("source_kind") == kind:
                    for f in files:   # 都道府県ごとのファイル
                        _add_counts(result, f"{key} {indicator_id}",
                                    mlit_landprice.ingest(conn, f, src, indicator_id, d))
        elif kind == "mlit_schools":
            result[key] = mlit_facilities.ingest_schools(conn, files, src, boundary_version,
                                                         source_prefectures(cfg, prefs), cfg["as_of"])
        elif kind == "mlit_nurseries":
            result[key] = mlit_facilities.ingest_nurseries(
                conn, files, src, boundary_version, source_prefectures(cfg, prefs), cfg["as_of"],
                cfg.get("exclude_codes", []), cfg.get("include_codes", []))
        elif kind == "mlit_stations":
            for indicator_id, d in catalog.items():
                if d.get("source_kind") == kind:
                    result[f"{key} {indicator_id}"] = mlit_stations.ingest(
                        conn, files[0], src, indicator_id, d, boundary_version, source_prefectures(cfg, prefs))
        else:
            period = (cfg["period"], cfg["period"], "point")
            for indicator_id, d in catalog.items():
                if d.get("source_kind") == kind:
                    result[f"{key} {indicator_id}"] = tokyo_daytime.ingest(
                        conn, files[0], src, indicator_id, d, period,
                        cfg.get("encoding", "utf-8-sig"))
    traffic_indexes.clear()   # 全国の町丁目の形は数GBあるので、使い終わったらすぐ手放す
    if tree_files:
        period = (tree_files[0][3], tree_files[0][3], "point")
        result["tokyo_street_trees"] = tokyo_street_trees.ingest(
            conn, [f[:3] for f in tree_files], catalog, period, boundary_version)
    for key, path, src, cfg in nursery_files:
        period = (cfg["period"], cfg["period"], "point")
        for indicator_id, d in catalog.items():
            if d.get("source_kind") == "tokyo_nurseries":
                result[f"{key} {indicator_id}"] = tokyo_nurseries.ingest(
                    conn, path, src, gazetteers, indicator_id, d, period, boundary_version)
    if school_tables:
        for indicator_id, d in catalog.items():
            if d.get("source_kind") == "tokyo_schools":
                result[indicator_id] = tokyo_schools.ingest(
                    conn, school_tables, gazetteers, indicator_id, d, boundary_version)
    return result


def _prefecture_files(paths: Paths, key: str, cfg: dict, prefs: list[str]) -> dict[str, list]:
    """都道府県ごとの出典の元ファイル（都道府県コード → ファイル）。取得していない都道府県は含めない。"""
    out = {}
    for pref in source_prefectures(cfg, prefs):
        files = find_files(paths.raw / key / pref, cfg["files"])
        if files:
            out[pref] = files
    return out


def _ingest_census(conn, paths: Paths, census: dict, sources: dict, catalog: dict,
                   overrides: dict | None, prefs: list[str] | None = None) -> dict:
    """国勢調査の1時点を、都道府県ごとに境界 → 表の順で取り込む（design-changes #52）。"""
    prefs = prefs or selected_prefectures()
    result: dict = {}
    label = census["label"]
    period = (census["period"], census["period"], "point")
    key = census["boundary"]
    bcfg = sources[key]
    bfiles = _prefecture_files(paths, key, bcfg, prefs)
    missing = [p for p in prefs if p not in bfiles]
    if missing:
        raise FileNotFoundError(f"{key}: 境界の元ファイルがない都道府県 {', '.join(missing)}")
    # 出典は都道府県をまとめて1つとして登録する（出典一覧に都道府県の数だけ並ばないように）
    bsrc = register_source(conn, key, bcfg, [f for fs in bfiles.values() for f in fs], overrides)
    tables: dict[str, tuple[str, dict]] = {}  # 表 → (source_id, 都道府県 → 元ファイル)
    for d in catalog.values():
        table_name = d.get("table")
        if not table_name or table_name not in census or table_name in tables:
            continue  # この時点の調査にない表（例: 最終学歴は10年ごとの大規模調査のみ）
        tkey = census[table_name]
        cfg = sources[tkey]
        files = _prefecture_files(paths, tkey, cfg, prefs)
        if not files:
            raise FileNotFoundError(f"{tkey}: 元ファイルが見つかりません")
        tables[table_name] = (register_source(conn, tkey, cfg, [f for fs in files.values() for f in fs],
                                              overrides), files)
    for pref in prefs:
        progress(f"国勢調査 {label}: {pref}")
        shp = next(f for f in bfiles[pref] if f.suffix.lower() == ".shp")
        r = estat_boundary.ingest(conn, shp, bsrc, census["boundary_version"], census["period"],
                                  bcfg.get("encoding", "cp932"), pref_code=pref)
        _add_counts(result, f"{label} 境界", r)
        for table_name, (src, files) in tables.items():
            if pref not in files:
                continue  # 東京都だけで取得している表（e-Stat「ファイル」の表など）
            cfg = sources[census[table_name]]
            reader = estat_small_area.READERS[cfg.get("format", "estat_gis")]
            table = reader(files[pref][0], cfg.get("encoding", "cp932"))
            for indicator_id, d in catalog.items():
                if d.get("table") != table_name:
                    continue
                fn = (estat_small_area.ingest_ratio if d["kind"] == "ratio"
                      else estat_small_area.ingest_counts)
                _add_counts(result, f"{label} {indicator_id}", fn(conn, table, src, indicator_id, d, period))
    for indicator_id, d in catalog.items():
        if d["kind"] == "density":
            n = derive_density(conn, indicator_id, d, catalog[d["numerator"]],
                               census["boundary_version"], census["period"])
            result[f"{label} {indicator_id}"] = {"rows": n}
    return result


def _add_counts(result: dict, key: str, r: dict) -> None:
    """都道府県ごとの取込結果を足し合わせる（件数は合計、対応しないコードはつなげる）。"""
    acc = result.setdefault(key, {})
    for k, v in r.items():
        if isinstance(v, list):
            acc[k] = acc.get(k, []) + v
        elif isinstance(v, (int, float)):
            acc[k] = acc.get(k, 0) + v
        else:
            acc[k] = v


def cmd_validate(paths: Paths) -> int:
    conn = connect(paths.db)
    rep = validate(conn, load_indicators())
    for w in rep.warnings:
        print(f"警告: {w}")
    for e in rep.errors:
        print(f"エラー: {e}", file=sys.stderr)
    print("検証: OK" if rep.ok else f"検証: エラー {len(rep.errors)} 件")
    return 0 if rep.ok else 1


SNAPSHOT_MAX_PREFECTURES = 10


def cmd_export(paths: Paths, release_id: str | None, note: str | None = None) -> int:
    release_id = release_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    conn = connect(paths.db)
    with conn:
        out = export_release(conn, load_indicators(), paths.releases, release_id,
                             load_censuses(), note)
    print(f"公開用ファイルを生成しました: {out}")
    size = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["size"]
    print(f"容量: {size['file_count']:,} ファイル、合計 {size['total_bytes']:,} bytes（圧縮後 {size['total_gzip_bytes']:,}）、"
          f"初回表示 {size['initial_load_gzip_bytes']:,}、"
          f"最大の区市町村 {size['largest_area_load']['gzip_bytes']:,}（圧縮後）")
    for w in size["warnings"]:
        print(f"容量の警告: {w}")
    for e in size["errors"]:
        print(f"容量のエラー: {e}", file=sys.stderr)
    # 管理用DBのスナップショットを同じ release_id で残す（設計書 第10章「保存と復旧」）。
    # 全国では20GB近くあってディスクに入らず、Artifacts にも上げないので作らない（元ファイルから作り直せる）
    prefecture_count = conn.execute("SELECT COUNT(*) FROM entities WHERE entity_type = 'prefecture'").fetchone()[0]
    if prefecture_count <= SNAPSHOT_MAX_PREFECTURES:
        snap = connect(paths.releases / f"{release_id}.sqlite")
        conn.backup(snap)
        snap.close()
    return 1 if size["errors"] else 0


def _print_result(result: dict) -> None:
    for k, v in result.items():
        codes = v.get("unmatched") if isinstance(v, dict) else None
        if isinstance(v, dict) and v.get("incomplete"):
            print(f"    町丁目の合計が区市町村の計と一致しない: {', '.join(v['incomplete'])}")
            v = {**v, "incomplete": len(v["incomplete"])}
        if codes is not None:
            v = {**v, "unmatched": len(codes)}
        print(f"  {k}: {v}")
        if codes:
            print(f"    境界に対応しないコード: {', '.join(codes[:30])}{' …' if len(codes) > 30 else ''}")


def cmd_build(paths: Paths, release_id: str | None, overrides=None, note=None, prefs=None) -> int:
    prefs = prefs or selected_prefectures()
    print(f"取込（{len(prefs)} 都道府県: {','.join(prefs)}）:")
    _print_result(ingest_all(paths, overrides, prefs))
    progress("検証")
    if cmd_validate(paths) != 0:
        return 1
    progress("公開用ファイルの作成（別のプロセスで行う）")
    # 取込で大きくなったメモリ（全国では4GB超）を手放すため、書き出しは新しいプロセスで行う
    argv = [sys.executable, "-m", "tdm", "--data-dir", str(paths.data_dir), "export"]
    if release_id:
        argv += ["--release-id", release_id]
    if note:
        argv += ["--note", note]
    return subprocess.run(argv, check=False).returncode


def cmd_fixture(data_dir: Path) -> int:
    if data_dir.exists():
        shutil.rmtree(data_dir)
    paths = Paths(data_dir)
    fixture.write(paths.raw)
    return cmd_build(paths, "dev-fixture", overrides=fixture.FIXTURE_SOURCE,
                     note="開発用の架空データ", prefs=list(fixture.PREF_NAMES))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tdm", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_PATHS.data_dir)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    p = sub.add_parser("fetch")
    p.add_argument("keys", nargs="*")
    sub.add_parser("ingest")
    sub.add_parser("validate")
    for name in ("export", "build"):
        p = sub.add_parser(name)
        p.add_argument("--release-id")
        p.add_argument("--note")
    p = sub.add_parser("fixture")
    p.add_argument("--out", type=Path,
                   default=Path(tempfile.gettempdir()) / "tdm-fixture")
    args = parser.parse_args(argv)
    paths = Paths(args.data_dir)

    if args.command == "init":
        init_schema(connect(paths.db))
        print(f"作成しました: {paths.db}")
        return 0
    if args.command == "fetch":
        return cmd_fetch(paths, args.keys)
    if args.command == "ingest":
        _print_result(ingest_all(paths))
        return 0
    if args.command == "validate":
        return cmd_validate(paths)
    if args.command == "export":
        return cmd_export(paths, args.release_id, args.note)
    if args.command == "build":
        return cmd_build(paths, args.release_id, note=args.note)
    if args.command == "fixture":
        return cmd_fixture(args.out)
    return 2
