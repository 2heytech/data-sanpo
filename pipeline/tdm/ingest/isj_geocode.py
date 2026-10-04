"""国土交通省「位置参照情報」（街区レベル）で住所の位置を求める。

形式（24.0a 東京都、2026-10-03 に GitHub Actions から取得して確認）: CSV（cp932）、列は
都道府県名, 市区町村名, 大字・丁目名, 小字・通称名, 街区符号・地番, 座標系番号, Ｘ座標, Ｙ座標,
緯度, 経度, 住居表示フラグ, 代表フラグ, 更新前履歴フラグ, 更新後履歴フラグ。
丁目は漢数字（「麹町二丁目」）。同じ街区に複数の行があるときは代表フラグ1を使う。

住所の書き方（例: 「麹町2-8」「三番町16」「父島字宮之浜道」）を町丁目と街区に分け、
街区が見つからなければ町丁目内の街区の代表点の平均を使う（精度は「町丁目」と記録する）。
街区レベルのない町村は大字・町丁目レベル（19.0b: 大字町丁目名, 緯度, 経度）の代表点で補う。
町丁目も見つからない住所は位置なしにする（区市町村の中心などには置かない）。
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

KANJI_DIGITS = "〇一二三四五六七八九"


def kanji_number(n: int) -> str:
    """1〜99 を丁目の表記（漢数字）にする。"""
    if n < 10:
        return KANJI_DIGITS[n]
    tens, ones = divmod(n, 10)
    return ("" if tens == 1 else KANJI_DIGITS[tens]) + "十" + (KANJI_DIGITS[ones] if ones else "")


def normalize(s: str) -> str:
    """表記ゆれ（全角数字・ヶ/ケ・空白）をそろえる。"""
    s = unicodedata.normalize("NFKC", s).strip()
    # 「會」は旧字体（例: 青梅市小曾木を「小會木」と書く住所がある）
    s = s.replace("會", "曾")
    s = s.replace("ヶ", "ケ").replace("ヵ", "カ").replace("之", "ノ").replace("　", "").replace(" ", "")
    s = re.sub(r"^大字", "", s)
    return s


def normalize_municipality(s: str) -> str:
    """位置参照情報の市区町村名は郡名を含む（「西多摩郡瑞穂町」）ので、郡名を除く。"""
    return re.sub(r"^.+?郡(?=.+[町村]$)", "", normalize(s))


@dataclass
class GeoResult:
    lon: float
    lat: float
    precision: str   # "街区" | "町丁目"（町丁目・大字の代表点）
    town: str        # 位置参照情報の大字・丁目名
    level: str = "block"   # 使った位置参照情報（"block"=街区レベル、"oaza"=大字・町丁目レベル）


def _mean(pts) -> tuple[float, float]:
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


class Gazetteer:
    def __init__(self) -> None:
        # (市区町村, 大字・丁目) → 街区 → (経度, 緯度, 代表フラグ)
        self.blocks: dict[tuple[str, str], dict[str, tuple[float, float, int]]] = {}
        # (市区町村, 大字, 小字) → 点の一覧（小字のある地域）
        self.koaza: dict[tuple[str, str, str], list[tuple[float, float]]] = {}
        # (市区町村, 大字・町丁目) → 代表点（大字・町丁目レベル。街区レベルのない町村を補う）
        self.oaza: dict[tuple[str, str], tuple[float, float]] = {}

    @classmethod
    def read(cls, path: Path | None, oaza_path: Path | None = None,
             encoding: str = "cp932") -> "Gazetteer":
        g = cls()
        if path:
            g._read_blocks(path, encoding)
        if oaza_path:
            g._read_oaza(oaza_path, encoding)
        return g

    def _read_blocks(self, path: Path, encoding: str) -> None:
        with path.open(encoding=encoding, newline="") as f:
            reader = csv.reader(f)
            head = next(reader)
            col = {name: i for i, name in enumerate(head)}
            for row in reader:
                if row[col["更新後履歴フラグ"]] not in ("0", ""):
                    continue   # 更新された古い行は使わない
                muni = normalize_municipality(row[col["市区町村名"]])
                town = normalize(row[col["大字・丁目名"]])
                block = normalize(row[col["街区符号・地番"]])
                lon, lat = float(row[col["経度"]]), float(row[col["緯度"]])
                rep = int(row[col["代表フラグ"]] or 0)
                koaza = normalize(row[col["小字・通称名"]])
                if koaza:
                    self.koaza.setdefault((muni, town, koaza), []).append((lon, lat))
                cur = self.blocks.setdefault((muni, town), {})
                if block not in cur or (rep and not cur[block][2]):
                    cur[block] = (lon, lat, rep)

    def _read_oaza(self, path: Path, encoding: str) -> None:
        """大字・町丁目レベル（列: 都道府県コード, 都道府県名, 市区町村コード, 市区町村名,
        大字町丁目コード, 大字町丁目名, 緯度, 経度, 原典資料コード, 大字・字・丁目区分コード）。"""
        with path.open(encoding=encoding, newline="") as f:
            reader = csv.reader(f)
            head = next(reader)
            col = {name: i for i, name in enumerate(head)}
            for row in reader:
                key = (normalize_municipality(row[col["市区町村名"]]), normalize(row[col["大字町丁目名"]]))
                self.oaza[key] = (float(row[col["経度"]]), float(row[col["緯度"]]))

    def _town_center(self, key) -> tuple[float, float] | None:
        pts = self.blocks.get(key)
        if not pts:
            return None
        reps = [p for p in pts.values() if p[2]] or list(pts.values())
        return _mean(reps)

    def _town(self, muni: str, town: str, koaza: str | None = None) -> GeoResult | None:
        """町丁目・大字の代表点（街区が見つからないとき）。"""
        if koaza and (pts := self.koaza.get((muni, town, koaza))):
            return GeoResult(*_mean(pts), "町丁目", town + "字" + koaza)
        if c := self._town_center((muni, town)):
            return GeoResult(c[0], c[1], "町丁目", town)
        if c := self.oaza.get((muni, town)):
            return GeoResult(c[0], c[1], "町丁目", town, "oaza")
        return None

    def locate(self, municipality: str, address: str) -> GeoResult | None:
        muni = normalize_municipality(municipality)
        a = normalize(address)
        a = re.split(r"[(（]", a)[0]
        if a.startswith(muni):
            a = a[len(muni):]
        # 「3ー1ー5」（長音符を区切りに使う）、「1丁目10番5号」（丁目を数字で書く）も「3-1-5」「1-10-5」にそろえる
        a = re.sub(r"(?<=\d)[ー―─]", "-", a)
        a = re.sub(r"(\d+)丁目", r"\1-", a)
        a = re.sub(r"(\d+)番地?", r"\1-", a).replace("号", "")
        a = re.sub(r"[-‐－−]+", "-", a).rstrip("-")
        if not re.match(r"^\D", a):
            # 大字を書かない住所（「神津島村807」「御蔵島村」）は、大字が1つだけの町村ならその大字
            towns = {t for (mm, t) in self.oaza if mm == muni} | {t for (mm, t) in self.blocks if mm == muni}
            if len(towns) == 1:
                a = towns.pop() + a
        m = re.match(r"^(?P<town>.*?)(?P<nums>\d+(?:-\d+)*)", a)
        if not m:
            if a in {t for (mm, t) in self.oaza if mm == muni}:
                return self._town(muni, a)
            # 番地のない住所（「父島字宮之浜道」「青ケ島村無番地」）
            m2 = re.match(r"^(?P<town>.+?)字(?P<koaza>.+)$", a)
            if m2:
                return self._town(muni, m2["town"], m2["koaza"])
            return None
        town = m["town"].rstrip("-")
        nums = m["nums"].split("-")
        town_koaza = None
        if "字" in town:
            town, town_koaza = town.split("字", 1)
        # 「町名＋丁目-街区」と「町名-街区（丁目なし）」の両方を試す
        candidates = []
        if town and len(nums) >= 2 and 0 < int(nums[0]) < 100:
            candidates.append((town + kanji_number(int(nums[0])) + "丁目", nums[1:]))
        candidates.append((town, nums))
        for t, rest in candidates:
            blocks = self.blocks.get((muni, t))
            if blocks:
                for k in ("-".join(rest[:2]), rest[0]):
                    if k in blocks:
                        lon, lat, _ = blocks[k]
                        return GeoResult(lon, lat, "街区", t)
        for t, _ in candidates:
            if t and (r := self._town(muni, t, town_koaza)):
                return r
        return None
