"""学校ごとの児童・生徒数の、都道府県・市ごとの表の読み方（school_counts.py が使う。docs/design-changes.md #137）。

sources.toml の school_counts の出典は reader で関数を選ぶ。どの関数も（ファイルの一覧, 出典の設定）を受け取り、
SchoolCount の一覧を返す。ファイルは出典の download_files の保存名（例: elementary.csv）で受け取るので、学校の種類は
保存名か表の中身で判断する。形式は2026-10-17 に取得して確認したもの（各関数の docstring）。
"""
from __future__ import annotations

from .akita import read_akita
from .chiba import read_chiba
from .fukuoka_cities import (
    read_fukuoka_toshiken,
    read_kurume,
    read_mizumaki,
    read_ogori,
)
from .hokkaido import read_hokkaido
from .kagawa import read_kagawa
from .kanagawa import read_kanagawa
from .kumamoto import read_kumamoto
from .matsuyama import read_matsuyama
from .mie import read_mie
from .miyazaki_cities import read_hyuga
from .nagasaki_city import read_nagasaki_city
from .nagoya import read_nagoya
from .niigata import read_niigata
from .okayama import read_okayama
from .okinawa_cities import read_ishigaki, read_okinawashi
from .saga_city import read_saga_city
from .saitama import read_saitama
from .shimane import read_shimane
from .shizuoka_city import read_shizuoka_city
from .tokushima import read_tokushima
from .yamanashi import read_yamanashi

READERS = {
    "hokkaido": read_hokkaido, "akita": read_akita, "niigata": read_niigata, "yamanashi": read_yamanashi,
    "saitama": read_saitama, "chiba": read_chiba, "kanagawa": read_kanagawa, "mie": read_mie,
    "shimane": read_shimane, "okayama": read_okayama, "tokushima": read_tokushima, "kagawa": read_kagawa,
    "kumamoto": read_kumamoto,
    "shizuoka_city": read_shizuoka_city, "matsuyama": read_matsuyama, "nagasaki_city": read_nagasaki_city,
    "saga_city": read_saga_city, "nagoya": read_nagoya,
    "kurume": read_kurume, "ogori": read_ogori, "fukuoka_toshiken": read_fukuoka_toshiken, "mizumaki": read_mizumaki,
    "hyuga": read_hyuga, "okinawashi": read_okinawashi, "ishigaki": read_ishigaki,
}
