"""文化庁「国指定文化財等データベース」（https://kunishitei.bunka.go.jp/）から、分類ごとの一覧（CSV）を取得して
1つの CSV にまとめる（docs/design-changes.md #149）。

データベースには一括のダウンロードがなく、検索結果を CSV に出す機能だけがある。全件の CSV 出力はサイトのお知らせ
（2026-05-07）で止まっていて、大きな検索は CSV の作成が時間切れになる。そこで分類 → 都道府県 → 分類ごとの副条件の順に
小さく分けて取得し、行をまとめる。公開版の取込（Actions「Data release」）のたびに数百回の取得をしないよう、
Actions「Prepare derived sources」で取得して Release「derived-sources」に置く。

仕組み（2026-10-18 に確認）:
  1. GET  /bsys/index       → Cookie csrfToken と、フォームの hidden _csrfToken（同じ値）を得る
  2. POST /bsys/searchlist  → 検索結果の HTML。「N 件中」で件数がわかる
  3. POST /utile/csv-list   → CSV（UTF-8 BOM 付き、全項目をダブルクォート、項目内に改行あり）。列はどの分類も同じ18列
     2・3 の本文は同じ（_method=POST, _csrfToken, register_sub_id, seat_pref, screen_id, page_no, ...）。
  - 0件の条件で CSV を求めると HTTP 500 になるので、先に件数を確かめる。
  - CSV の作成は1行あたり約0.03秒かかり、60秒で 504 になる（約1,800行までは通る）。だから大きい分類は都道府県で分ける。
  - 都道府県で検索すると、所在地しだいでほかの都道府県や「２県以上」の行も出るので、行全体が同じものを1行にまとめる。
  - 都道府県の値が壊れている行（"98" など）はどの都道府県で検索しても出ない。検索結果を都道府県の降順に並べると
    そうした行が先頭に来るので、取れていない行を名称（フリーワード）で取り直す（取り残し探し）。

まとめた CSV（Release に置く）は、所有者名・管理団体又は責任者の列を除き（個人の名前があるため。地図にも出さない）、
最後に取得日（UTC）の列を足す。

件数の確かめ方（全国を取得したとき。合わなければ止めて、Release に上げない）:
  - 登録有形文化財（建造物）・史跡名勝天然記念物・重要伝統的建造物群保存地区: CSV の1行が検索の1件。まとめた行数 = 全国の件数。
  - 国宝・重要文化財（建造物）: CSV は棟ごとの行で、検索の件数は「件」。「各都道府県の件数の和 ≥ 全国の件数」
    「各単位の行数 ≥ その件数」「取り残しなし」で確かめる。
"""
from __future__ import annotations

import csv
import gzip
import html
import http.cookiejar
import io
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from ..fetch import USER_AGENT
from ..progress import progress
from ..regions import PREFECTURES

BASE = "https://kunishitei.bunka.go.jp"
HEAD = ["台帳ID", "管理対象ID", "名称", "棟名", "文化財種類", "種別1", "種別2", "国", "時代", "重文指定年月日",
        "国宝指定年月日", "都道府県", "所在地", "保管施設の名称", "所有者名", "管理団体又は責任者", "緯度", "経度"]
# まとめた CSV に残さない列（登録有形文化財などは個人が所有者のことがある）
DROP = ("所有者名", "管理団体又は責任者")
# CSV が棟ごとの行で、検索の件数（件）と単位が違う分類と、1件あたりの行数の見込み
ROWS_PER_COUNT = {"102": 2.2}
# 検索フォームの都道府県（seat_pref）の選択肢。都道府県名と「２県以上」「地域を定めない」（全角の数字はフォームの値のまま）
EXTRA_UNITS = [("multi", "２県以上"), ("none", "地域を定めない")]
# 都道府県で分けても大きすぎる・失敗するときの副条件（フォームの選択肢）。選択肢に当てはまらない行は取りこぼすので、
# 件数の確認で気づく
SUBSPLITS = {
    "102": ("nation_div_102", ["国宝", "重要文化財"]),
    "101": ("era_101", ["江戸", "明治", "大正", "昭和前", "昭和中", "昭和後"]),
    "401": ("entry_kind1_401[]", ["史跡", "名勝", "天然記念物", "特別史跡", "特別名勝", "特別天然記念物"]),
}
DIRECT_LIMIT = 1500       # 見込みの行数がこれを超える単位は、CSV を試さずに分ける
MIN_INTERVAL = 1.5        # 取得の間隔（秒）
TIMEOUT = 150
RETRYABLE = {500, 502, 503, 504}
RESIDUAL_PAGE_SIZE = 100
RESIDUAL_MAX_PAGES = 5


class Retryable(RuntimeError):
    """時間切れ・5xx。分けるか、待ってやり直す。"""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class Client:
    token: str = ""
    requests: int = 0
    _last: float = 0.0

    def __post_init__(self) -> None:
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def _open(self, path: str, fields: list[tuple[str, str]] | None) -> tuple[int, bytes, float]:
        wait = MIN_INTERVAL - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "ja"}
        data = None
        if fields is not None:
            data = urllib.parse.urlencode(fields).encode("utf-8")
            headers.update({"Content-Type": "application/x-www-form-urlencoded", "Referer": BASE + "/bsys/searchlist"})
        req = urllib.request.Request(BASE + path, data=data, headers=headers, method="POST" if data else "GET")
        started = time.monotonic()
        self.requests += 1
        try:
            with self.opener.open(req, timeout=TIMEOUT) as res:
                body, status = res.read(), res.status
        except urllib.error.HTTPError as e:
            body, status = e.read(), e.code
        except (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError) as e:
            raise Retryable(f"{path}: {e!r}") from e
        finally:
            self._last = time.monotonic()
        return status, body, round(self._last - started, 1)

    def post(self, path: str, params: list[tuple[str, str]]) -> tuple[int, bytes, float]:
        for attempt in (1, 2):
            if not self.token:
                status, body, _ = self._open("/bsys/index", None)
                m = re.search(rb'name="_csrfToken"[^>]*value="([0-9a-f]+)"', body) if status == 200 else None
                if not m:
                    raise RuntimeError(f"国指定文化財等データベースの検索画面を読めません（HTTP {status}）")
                self.token = m.group(1).decode()
            status, body, sec = self._open(path, [("_method", "POST"), ("_csrfToken", self.token)] + params)
            if status in (400, 403) and attempt == 1:
                self.token = ""   # トークン切れ
                continue
            return status, body, sec
        raise AssertionError("unreachable")


def unit_params(cat: str, pref: str | None = None, sub: tuple[str, str] | None = None,
                extra: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    p = [("register_sub_id", cat)] + ([("seat_pref", pref)] if pref else [])
    p += [("screen_id", "index"), ("page_no", "1")] + ([sub] if sub else [])
    return p + (extra or [])


def search(client: Client, params: list[tuple[str, str]], retries: int = 3) -> str:
    for i in range(retries + 1):
        try:
            status, body, _ = client.post("/bsys/searchlist", params)
            if status == 200:
                return body.decode("utf-8", "replace")
            if status not in RETRYABLE:
                raise RuntimeError(f"検索が HTTP {status} になりました: {params}")
        except Retryable:
            pass
        if i < retries:
            time.sleep(5 * 3 ** i)
    raise RuntimeError(f"検索が {retries + 1} 回失敗しました: {params}")


def count(client: Client, params: list[tuple[str, str]]) -> int:
    m = re.search(r'class="searchnum">\s*([\d,]+)\s*件中', search(client, params))
    if not m:
        raise RuntimeError("検索結果の件数が読めません（ページの形が変わった？）")
    return int(m.group(1).replace(",", ""))


def parse_listing(text: str) -> list[dict]:
    """検索結果の表から1件ずつ {id: (台帳ID, 管理対象ID) | None, name, pref} を取り出す。
    棟が複数ある件は詳細へのリンクの代わりに棟の一覧なので id は None。"""
    t = text[text.find('<div class="pc_view">'):]
    t = t[:t.find("</table>")]
    out = []
    for tr in re.findall(r'<tr class="resultback\d">(.*?)</tr>', t, re.S):
        link = re.search(r"heritage/detail/(\d+)/(\d+)", tr)
        tds = [_norm(html.unescape(re.sub(r"<[^>]+>", " ", x))) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        tds = [x for x in tds if x and x != "地図表示"]
        if tds:
            out.append({"id": link.groups() if link else None, "name": tds[0], "pref": tds[-1]})
    return out


def get_csv(client: Client, params: list[tuple[str, str]]) -> list[list[str]]:
    status, body, sec = client.post("/utile/csv-list", params)
    if status in RETRYABLE:
        raise Retryable(f"CSV の作成が HTTP {status} になりました（{sec}秒）")
    if status != 200:
        raise RuntimeError(f"CSV の作成が HTTP {status} になりました: {params}")
    text = body.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if not body.startswith(b"\xef\xbb\xbf") or not rows or rows[0] != HEAD:
        raise RuntimeError(f"CSV の列が違います（{text[:80]!r}）")
    return rows[1:]


@dataclass
class Fetcher:
    client: Client
    prefs: list[str]
    rows: list[list[str]] = field(default_factory=list)
    unit_counts: int = 0          # 都道府県ごとの件数の和（国宝・重要文化財（建造物）の確認に使う）
    warnings: list[str] = field(default_factory=list)

    @property
    def national(self) -> bool:
        return len(self.prefs) == len(PREFECTURES)

    def unit(self, cat: str, label: str, pref: str | None = None, sub: tuple[str, str] | None = None,
             n: int | None = None, level: int = 0, extra: list[tuple[str, str]] | None = None) -> None:
        """1つの単位を取得する（大きすぎる・失敗したら分ける）。"""
        params = unit_params(cat, pref, sub, extra)
        if n is None:
            n = count(self.client, params)
        if level == 1:
            self.unit_counts += n
        if n == 0:
            return
        can_split = level < 2 and (level == 0 or cat in SUBSPLITS)
        if n * ROWS_PER_COUNT.get(cat, 1) > DIRECT_LIMIT and can_split:
            return self.split(cat, label, pref, level)
        tries = 1 if can_split else 4
        for i in range(tries):
            try:
                rows = get_csv(self.client, params)
            except Retryable as e:
                progress(f"  {cat} {label}: {e}")
                if can_split:
                    return self.split(cat, label, pref, level)
                if i + 1 < tries:
                    time.sleep(10 * 3 ** i)
                continue
            if (len(rows) < n) if cat in ROWS_PER_COUNT else (len(rows) != n):
                self.warnings.append(f"{cat} {label}: CSV の行数 {len(rows)} が検索の件数 {n} と合いません")
            self.rows += rows
            progress(f"  {cat} {label}: 件数 {n}・{len(rows)} 行")
            return
        raise RuntimeError(f"{cat} {label}: CSV を {tries} 回取得できませんでした")

    def split(self, cat: str, label: str, pref: str | None, level: int) -> None:
        if level == 0:
            units = [(code, PREFECTURES[code]) for code in self.prefs]
            for code, value in units + (EXTRA_UNITS if self.national else []):
                self.unit(cat, code, value, level=1)
            if self.national:
                self.residual(cat)
        else:
            key, values = SUBSPLITS[cat]
            for j, v in enumerate(values, 1):
                self.unit(cat, f"{label}_{j}", pref, (key, v), level=2)

    def residual(self, cat: str) -> None:
        """都道府県の値が壊れていて、どの都道府県で検索しても出ない行を探して取る（並び順に頼るので、最後に件数で確かめる）。"""
        mine = [r for r in self.rows if r[0] == cat]
        have_ids = {(r[0], r[1]) for r in mine}
        have_names = {_norm(r[2]) for r in mine}
        prefs = set(PREFECTURES.values())
        missing, seen, prev_first = [], set(), None
        for page in range(1, RESIDUAL_MAX_PAGES + 1):
            # ページ送りは pageNumber（page_no は 1 のまま。サイトの「次のページへ」と同じ）
            entries = parse_listing(search(self.client, [
                ("register_sub_id", cat), ("screen_id", "index"), ("page_no", "1"),
                ("sortTarget", "area"), ("sortType", "desc"), ("pageSize", str(RESIDUAL_PAGE_SIZE)),
                ("pageNumber", str(page))]))
            if entries and entries[0] == prev_first:
                raise RuntimeError(f"{cat}: 検索結果のページ送りが効いていません")
            prev_first = entries[0] if entries else None
            for e in entries:
                key = tuple(e["id"]) if e["id"] else e["name"]
                if e["pref"] in prefs or key in seen:
                    continue
                seen.add(key)
                if not (key in have_ids if e["id"] else e["name"] in have_names):
                    missing.append(e)
            if not entries or entries[-1]["pref"] in prefs:
                break
        else:
            raise RuntimeError(f"{cat}: 取り残し探しが {RESIDUAL_MAX_PAGES} ページで終わりません")
        self.unit_counts += len(missing)
        for i, e in enumerate(missing, 1):
            progress(f"  {cat} 取り残し: {e['name']}（{e['pref']}）")
            before = len(self.rows)
            self.unit(cat, f"extra{i}", level=2, extra=[("freeword", e["name"])])
            if e["id"] and not any((r[0], r[1]) == tuple(e["id"]) for r in self.rows[before:]):
                raise RuntimeError(f"{cat}: 取り残し {e['name']} を名称で取得できませんでした")


def fetch_category(client: Client, cat: str, prefs: list[str]) -> list[list[str]]:
    """分類1つの行（行全体が同じものは1行に）。全国のときは件数を確かめ、合わなければ止める。"""
    f = Fetcher(client, prefs)
    expected = count(client, unit_params(cat))
    progress(f"国指定文化財 {cat}: 全国の検索件数 {expected}")
    if f.national:
        f.unit(cat, "all", n=expected)
    else:
        f.split(cat, "all", None, 0)   # 一部の都道府県だけ（試すとき）
    rows = sorted({tuple(r) for r in f.rows if r[0] == cat},
                  key=lambda r: (int(r[1]) if r[1].isdigit() else 10 ** 12, r))
    if f.national:
        if cat in ROWS_PER_COUNT:
            ok = f.unit_counts >= expected and len(rows) >= expected
        else:
            ok = len(rows) == expected
        if not ok or f.warnings:
            raise RuntimeError(f"国指定文化財 {cat}: 件数が合いません（全国 {expected}・都道府県の和 {f.unit_counts}・"
                               f"まとめた行 {len(rows)}）{f.warnings}")
    return [list(r) for r in rows]


def prepare(cfg: dict, outputs: dict[str, Path], work: Path, prefs: list[str], load_towns) -> dict:
    client = Client()
    rows: list[list[str]] = []
    result = {}
    for cat in cfg["categories"]:
        got = fetch_category(client, cat, prefs)
        rows += got
        result[cat] = len(got)
    keep = [i for i, c in enumerate(HEAD) if c not in DROP]
    today = time.strftime("%Y-%m-%d", time.gmtime())
    path = outputs["list"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([HEAD[i] for i in keep] + ["取得日"])
        w.writerows([r[i] for i in keep] + [today] for r in rows)
    result["requests"] = client.requests
    return result
