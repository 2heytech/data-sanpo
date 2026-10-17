"""国土交通省「位置参照情報」（街区レベル）で住所の位置を求める。

形式（24.0a 東京都、2026-10-03 に GitHub Actions から取得して確認）: CSV（cp932）、列は
都道府県名, 市区町村名, 大字・丁目名, 小字・通称名, 街区符号・地番, 座標系番号, Ｘ座標, Ｙ座標,
緯度, 経度, 住居表示フラグ, 代表フラグ, 更新前履歴フラグ, 更新後履歴フラグ。
丁目は漢数字（「麹町二丁目」）。同じ街区に複数の行があるときは代表フラグ1を使う。

住所の書き方（例: 「麹町2-8」「三番町16」「父島字宮之浜道」）を町丁目と街区に分け、
街区が見つからなければ町丁目内の街区の代表点の平均を使う（精度は「町丁目」と記録する）。
街区レベルのない町村は大字・町丁目レベル（19.0b: 大字町丁目名, 緯度, 経度）の代表点で補う。
町丁目も見つからない住所は位置なしにする（区市町村の中心などには置かない）。
東京都以外（全国の保育所・学校、#138）は都道府県ごとの ZIP を展開せずに置き、ZIP の中の CSV を読む。
"""
from __future__ import annotations

import csv
import io
import itertools
import re
import unicodedata
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ..regions import PREFECTURES

KANJI_DIGITS = "〇一二三四五六七八九"
# 市区町村名の字体の違い（ここdeサーチ・こども家庭庁の表の「梼原町」「須惠町」と境界の「檮原町」「須恵町」）
MUNICIPALITY_VARIANTS = str.maketrans({"梼": "檮", "惠": "恵"})
# 町名の字体・かなの違い（住所の「弥富通」「蛍池西町」「久我森ノ宮町」と位置参照情報の「彌富通」「螢池西町」
# 「久我森の宮町」）。比べるときだけそろえる
TOWN_VARIANTS = str.maketrans({"彌": "弥", "螢": "蛍", "の": "ノ"})
# 京都市の通り名で書いた住所（「新町通今出川上る元新在家町163-1」）の、町名の前までの部分
KYOTO_STREET = re.compile(r"^.*(?:[上下][るル]|[東西]入[るル]?)(?=\D)")
# 住所の先頭に重ねて書かれた都道府県名（ここdeサーチの「町名・番地」に「静岡県駿東郡長泉町…」と書く施設がある）
PREFECTURE_PREFIX = re.compile("^(?:" + "|".join(map(re.escape, PREFECTURES.values())) + ")")


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


def town_key(s: str) -> str:
    """町名を比べるための形。「大字」「字」の有無（位置参照情報の「字翁長」「門田町大字日吉」と住所の「翁長」
    「門田町日吉」）と字体の違いを除く。"""
    return s.translate(TOWN_VARIANTS).replace("大字", "").replace("字", "")


def normalize_municipality(s: str) -> str:
    """位置参照情報の市区町村名は郡名を含む（「西多摩郡瑞穂町」）ので、郡名を除く。"""
    return re.sub(r"^.+?郡(?=.+[町村]$)", "", normalize(s)).translate(MUNICIPALITY_VARIANTS)


@dataclass
class GeoResult:
    lon: float
    lat: float
    precision: str   # "街区" | "町丁目"（町丁目・大字の代表点）
    town: str        # 位置参照情報の大字・丁目名
    level: str = "block"   # 使った位置参照情報（"block"=街区レベル、"oaza"=大字・町丁目レベル）


@contextmanager
def _open_csv(path: Path, encoding: str):
    """CSV を開く。ZIP（展開せずに置いた全国の位置参照情報）なら中の CSV を開く。"""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv") and not n.lower().startswith("md_"))
            with z.open(name) as raw:
                yield io.TextIOWrapper(raw, encoding=encoding, newline="")
    else:
        with path.open(encoding=encoding, newline="") as f:
            yield f


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
        # 市区町村 → town_key → 位置参照情報の町名（最初に使うときに作る）
        self._town_index: dict[str, dict[str, set[str]]] | None = None
        # (市区町村, 町名) → town_key(小字) → 小字
        self._koaza_index: dict[tuple[str, str], dict[str, str]] = {}

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
        with _open_csv(path, encoding) as f:
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
        with _open_csv(path, encoding) as f:
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

    def _towns(self, muni: str) -> dict[str, set[str]]:
        if self._town_index is None:
            self._town_index = {}
            for m, t in itertools.chain(self.blocks, self.oaza):
                self._town_index.setdefault(m, {}).setdefault(town_key(t), set()).add(t)
            for m, t, k in self.koaza:
                self._koaza_index.setdefault((m, t), {})[town_key(k)] = k
        return self._town_index.get(muni, {})

    def _same_towns(self, muni: str, town: str) -> list[str]:
        """住所の町名と、「字」の有無・字体の違いだけが違う位置参照情報の町名（そのものを先に）。"""
        return [town] + sorted(self._towns(muni).get(town_key(town), set()) - {town})

    def _by_prefix(self, muni: str, town: str) -> GeoResult | None:
        """町名のあとに小字や地番の符号が続く住所（「寺中町リ10」「橘町久保38-3」「門田町日吉小金井63」）。
        位置参照情報の町名で住所の町名の頭に合う最も長いものを探し、続きがその町の小字ならその小字の点、
        続きが短く（2文字まで）町名が町・村・丁目・通で終わるならその町の代表点にする。"""
        key, towns = town_key(town), self._towns(muni)
        for n in range(len(key) - 1, 1, -1):
            head, rest = key[:n], key[n:]
            for t in sorted(towns.get(head, ())):
                if (k := self._koaza_index.get((muni, t), {}).get(rest)) and len(rest) <= 6:
                    return self._town(muni, t, k)
                if len(rest) <= 2 and head.endswith(("町", "村", "丁目", "通")):
                    return self._town(muni, t)
        return None

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
        # 町名・番地の欄に都道府県・郡・市区町村名を重ねて書いた住所（「静岡県駿東郡長泉町下土狩87-1」）と、
        # 政令指定都市の区名から書いた住所（市区町村が「静岡市葵区」で「葵区古庄4-2-11」）
        a = PREFECTURE_PREFIX.sub("", a)
        a = re.sub(rf"^[^\d]+?郡(?={re.escape(muni)})", "", a)
        ward = re.match(r"^.+市(.+区)$", muni)
        for head in (muni, ward[1] if ward else None):
            if head and a.startswith(head):
                a = a[len(head):]
                break
        # 町名の前の「字」（「字翁長665」）、京都市の通り名
        a = re.sub(r"^大?字", "", a)
        if muni.startswith("京都市"):
            a = KYOTO_STREET.sub("", a)
        # 札幌市などの「月寒東2条18丁目」の「条」は、位置参照情報では漢数字（「月寒東二条十八丁目」）
        a = re.sub(r"(\d+)条", lambda m: (kanji_number(int(m[1])) if 0 < int(m[1]) < 100 else m[1]) + "条", a)
        # 「3ー1ー5」（長音符を区切りに使う）、「1丁目10番5号」（丁目を数字で書く）も「3-1-5」「1-10-5」にそろえる
        a = re.sub(r"(?<=\d)[ー―─]", "-", a)
        # 番地のない「北11条西5丁目」と、札幌市白石区などの「南郷通1丁目南8-1」（位置参照情報は「南郷通一丁目南」）は
        # 丁目を漢数字にして町名に含める。堺市の「東湊町1丁59-1」の「丁」は丁目と同じに扱う
        a = re.sub(r"(\d+)丁目(?=$|[東西南北])",
                   lambda m: (kanji_number(int(m[1])) if 0 < int(m[1]) < 100 else m[1]) + "丁目", a)
        a = re.sub(r"(\d+)丁目?(?=\d)", r"\1-", a)
        a = re.sub(r"(\d+)丁目", r"\1-", a)
        a = re.sub(r"(\d+)番地?", r"\1-", a).replace("号", "")
        # 「51の1」「22番地の1」の「の」と、文字化けした区切り（「2?3?24」）
        a = re.sub(r"(?<=[\d-])の(?=\d)", "-", a)
        a = re.sub(r"(?<=\d)[?\ufffd](?=\d)", "-", a)
        a = re.sub(r"[-‐－−]+", "-", a).rstrip("-")
        if not re.match(r"^\D", a):
            # 大字を書かない住所（「神津島村807」「御蔵島村」）は、大字が1つだけの町村ならその大字
            towns = {t for (mm, t) in self.oaza if mm == muni} | {t for (mm, t) in self.blocks if mm == muni}
            if len(towns) == 1:
                a = towns.pop() + a
        m = re.match(r"^(?P<town>.*?)(?P<nums>\d+(?:-\d+)*)", a)
        if not m:
            # 番地のない住所。町名で見つからなければ末尾の丁目・条を外して引く（「南美唄町下五条二丁目」→「南美唄町下」）
            t = a
            while t:
                for t2 in self._same_towns(muni, t):
                    if r := self._town(muni, t2):
                        return r
                t, shorter = re.sub(r"[〇一二三四五六七八九十]+(?:丁目|条)$", "", t), t
                if t == shorter:
                    break
            # 番地のない住所（「父島字宮之浜道」「青ケ島村無番地」）
            m2 = re.match(r"^(?P<town>.+?)字(?P<koaza>.+)$", a)
            if m2:
                return self._town(muni, m2["town"], m2["koaza"])
            return None
        town = m["town"].rstrip("-")
        nums = m["nums"].split("-")
        town_koaza = None
        candidates = []
        # 「父島字宮之浜道」の「字」（「川副町大字西古賀」の「大字」は町名の一部なので分けない）。
        # 位置参照情報の町名が「大里字稲嶺」のように「字」を含むこともあるので、分けない町名も先に試す
        if len(parts := re.split(r"(?<!大)字", town, maxsplit=1)) == 2:
            candidates.append((town, nums))
            town, town_koaza = parts
        # 「町名＋丁目-街区」と「町名-街区（丁目なし）」の両方を試す
        chome = town and len(nums) >= 2 and 0 < int(nums[0]) < 100
        if chome:
            candidates.append((town + kanji_number(int(nums[0])) + "丁目", nums[1:]))
        candidates.append((town, nums))
        if chome:
            # 堺市の「新堀町一丁」（丁目でなく丁）と、住所で「町」を省いた町名（「元桜田3丁目」→「元桜田町三丁目」）
            candidates.append((town + kanji_number(int(nums[0])) + "丁", nums[1:]))
            if not town.endswith("町"):
                candidates.append((town + "町" + kanji_number(int(nums[0])) + "丁目", nums[1:]))
        # 地番の前の「甲」「乙」（「三河内乙1189」）は大字名ではない
        if town[-1:] in ("甲", "乙", "丙") and len(town) > 2:
            candidates.append((town[:-1], nums))
        # 位置参照情報に「大字」がない町名（住所は「鍋島町大字蛎久」）と、住所に「大字」がない町名
        # （位置参照情報は「川副町大字早津江」）も試す
        if "大字" in town:
            candidates.append((town.replace("大字", ""), nums))
        elif m3 := re.match(r"^(.+?町)(.{2,})$", town):
            candidates.append((f"{m3[1]}大字{m3[2]}", nums))
        # 住所どおりの町名で引けなければ、「字」の有無・字体だけが違う町名で引き直す
        for variants in (False, True):
            names = [(t, rest, self._same_towns(muni, t)[1:] if variants else [t]) for t, rest in candidates if t]
            for _, rest, ts in names:
                for t in ts:
                    blocks = self.blocks.get((muni, t))
                    if blocks:
                        for k in ("-".join(rest[:2]), rest[0]):
                            if k in blocks:
                                lon, lat, _ = blocks[k]
                                return GeoResult(lon, lat, "街区", t)
            for _, _, ts in names:
                for t in ts:
                    if r := self._town(muni, t, town_koaza):
                        return r
        return self._by_prefix(muni, town) if town else None
