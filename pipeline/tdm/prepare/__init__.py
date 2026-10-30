"""公開版の取込の前に、大きな元データを町丁・字等ごとの小さな集計表にまとめる（docs/design-changes.md #123）。

全国の土地利用細分メッシュ（4年度で約6GB）や標高タイル（約8千枚）を、公開版の取込（Actions「Data release」）の
たびに取り直して集計すると、時間もディスクも足りない。そこで Actions「Prepare derived sources」でこの集計だけを行い、
結果（町丁・字等ごとの CSV と土地利用図のタイル）を GitHub Release「derived-sources」に置く。公開版の取込は
sources.toml の download_url でその結果を取得し、ほかの出典と同じように取り込む。

集計の作り方は config/prepare.toml、結果のファイル名は sources.toml の download_url の最後の部分。
ファイル名には版（-v1 など）を入れ、作り方や元データを変えたら版を上げる（Release の同じ名前のファイルは置き換えない。
古い版を公開版の取込で使っているあいだに中身が変わらないようにするため）。
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from ..config import CONFIG_DIR, Paths, load_sources
from . import cultural_properties, elevation, farmland, land_use, slope, vegetation, zairyu
from .towns import load_towns

METHODS = {"land_use": land_use, "elevation": elevation, "slope": slope, "farmland": farmland,
           "vegetation": vegetation, "cultural_properties": cultural_properties, "zairyu": zairyu}


def load_jobs() -> dict[str, dict]:
    return tomllib.loads((CONFIG_DIR / "prepare.toml").read_text(encoding="utf-8"))


def asset_name(source: dict) -> str:
    """Release に置くファイルの名前（sources.toml の download_url の最後の部分）。"""
    return source["download_url"].rsplit("/", 1)[1]


def outputs_of(job: dict, sources: dict, out_dir: Path) -> dict[str, Path]:
    return {role: out_dir / asset_name(sources[key]) for role, key in job["outputs"].items()}


def run(name: str, paths: Paths, out_dir: Path, prefs: list[str]) -> dict:
    job = load_jobs()[name]
    sources = load_sources()
    outputs = outputs_of(job, sources, out_dir)
    work = paths.data_dir / "prepare" / name
    return METHODS[job["method"]].prepare(job, outputs, work, prefs,
                                          lambda pref: load_towns(paths.raw, sources, pref))
