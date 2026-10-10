"""出典ファイルの取得。

download_url のある出典をダウンロードし、ZIP なら展開して data/raw/<キー>/ に置く。
行政サイトがエラー画面（HTML）を返した場合は、正常なファイルと取り違えないよう失敗にする。
取得結果（URL・日時・サイズ・sha256）は data/raw/<キー>/_fetch.json に残す。
per_prefecture = true の出典は都道府県ごとに download_url の {pref} を置き換えて data/raw/<キー>/<都道府県>/ に置く。
同じURLで取得済み（_fetch.json がある）なら取得し直さない（GitHub Actions のキャッシュから戻した元ファイルを使う）。
keep_rows = { column = "列名", value = "値" } のあるCSVは、その列が値に一致する行（と1行目の列名）だけを
残して保存する（例: 全国の交通事故から東京都の行だけ。sha256 は取得したままのファイルのもの）。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from .db import now_iso

USER_AGENT = "data-sanpo/0.1 (+https://github.com/2heytech/data-sanpo)"
TIMEOUT = 120


class FetchError(RuntimeError):
    pass


def _looks_like_html(data: bytes) -> bool:
    head = data[:512].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def _safe_extract(z: zipfile.ZipFile, dest: Path) -> list[Path]:
    out = []
    for info in z.infolist():
        if info.is_dir():
            continue
        name = PurePosixPath(info.filename)
        if name.is_absolute() or ".." in name.parts:
            raise FetchError(f"ZIP内に不正なパスがあります: {info.filename}")
        target = dest / Path(*name.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(z.read(info))
        out.append(target)
    return out


def keep_rows(data: bytes, column: str, value: str, encoding: str = "cp932") -> bytes:
    """CSVの1行目（列名）と、column の値が value の行だけを残す。"""
    lines = data.decode(encoding, errors="replace").splitlines(keepends=True)
    if not lines:
        return data
    header = [c.strip() for c in next(csv.reader([lines[0]]))]
    if column not in header:
        raise FetchError(f"keep_rows の列 {column} がありません。列名: {header[:10]} …")
    i = header.index(column)
    kept = [lines[0]] + [ln for ln in lines[1:]
                         if (row := next(csv.reader([ln]), [])) and len(row) > i and row[i].strip() == value]
    return "".join(kept).encode(encoding, errors="replace")


def _is_office_file(data: bytes) -> bool:
    """Excel（.xlsx）などの Office のファイルも ZIP なので、展開せずにそのまま保存する。"""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return "[Content_Types].xml" in z.namelist()


RETRIES = 3


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
                return res.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            # 404 などはやり直しても変わらない。一時的な失敗（5xx・接続断）だけ間をあけてやり直す
            if isinstance(e, urllib.error.HTTPError) and e.code < 500 or attempt == RETRIES - 1:
                raise
            time.sleep(5 * (attempt + 1))
    raise AssertionError("unreachable")


def source_prefectures(cfg: dict, prefs: list[str]) -> list[str]:
    """都道府県ごとの出典で、取得・取込の対象にする都道府県（prefectures で限った出典はその範囲だけ、
    exclude_prefectures に書いた都道府県は除く。例: 東京都は別の出典で詳しい値があるので全国の出典から除く）。"""
    allowed = cfg.get("prefectures")
    excluded = cfg.get("exclude_prefectures", [])
    return [p for p in prefs if (allowed is None or p in allowed) and p not in excluded]


def _already_fetched(dest: Path, url: str) -> list[Path] | None:
    meta = dest / "_fetch.json"
    if not meta.exists():
        return None
    info = json.loads(meta.read_text(encoding="utf-8"))
    files = [dest / f for f in info.get("files", [])]
    if info.get("url") == url and files and all(f.exists() for f in files):
        return files
    return None


def _already_fetched_files(dest: Path, urls: dict[str, str]) -> list[Path] | None:
    """download_files の出典で、前回すべてのファイルを同じ URL から取得していればそのファイル。"""
    meta = dest / "_fetch.json"
    if not meta.exists():
        return None
    info = json.loads(meta.read_text(encoding="utf-8"))
    got = {d.get("file"): d.get("url") for d in info.get("downloads", [])}
    files = [dest / name for name in urls]
    if all(got.get(name) == url for name, url in urls.items()) and all(f.exists() for f in files):
        return files
    return None


# e-Stat「ファイル」の一覧（政府統計 → 提供分類1 → 都道府県（提供分類2）→ 表）。statInfId は都道府県・表ごとに違う
# e-Stat のサイトのリンクと同じ形（下の階層を一覧にするときは tclassNval=0 を付ける。付けないと一覧が空のページになる）
ESTAT_FILES_LIST = ("https://www.e-stat.go.jp/stat-search/files?page={page}&layout=datalist&toukei=00200521"
                    "&tstat={tstat}&cycle=0&tclass1={tclass1}{tclass2}")
_TAG = re.compile(r"<[^>]+>")


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub(" ", html))


# 一覧のページは表ごとに同じものを読むので、1回の実行の間は読んだものを使い回す（e-Stat の一覧は応答が遅い）
_PAGE_CACHE: dict[tuple[object, str], str] = {}


def _pages(url: str, downloader, max_pages: int = 10):
    """一覧の各ページの HTML（新しい項目が出なくなるまで）。"""
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        key = (downloader, url.format(page=page))
        if key not in _PAGE_CACHE:
            _PAGE_CACHE[key] = downloader(key[1]).decode("utf-8", errors="replace")
        html = _PAGE_CACHE[key]
        ids = set(re.findall(r"(?:statInfId|tclass2)=(\d+)", html))
        if not ids - seen:
            return
        seen |= ids
        yield html


def find_prefecture_classes(lookup: dict, downloader) -> dict[str, str]:
    """都道府県コード → 提供分類2（tclass2）。分類のリンクの近くにある都道府県名で対応付ける。"""
    from .regions import PREFECTURES
    by_name = {name: code for code, name in PREFECTURES.items()}
    out: dict[str, str] = {}
    url = ESTAT_FILES_LIST.format(tstat=lookup["tstat"], tclass1=lookup["tclass1"], tclass2="&tclass2val=0", page="{page}")
    for html in _pages(url, downloader):
        for m in re.finditer(r"tclass2=(\d+)", html):
            near = _text(html[m.end():m.end() + 600])
            name = next((n for n in by_name if n in near[:80]), None)
            if name and by_name[name] not in out:
                out[by_name[name]] = m.group(1)
    return out


def find_file_id(lookup: dict, tclass2: str, downloader) -> str | None:
    """都道府県の一覧から、表番号（例: 第13表）の CSV の statInfId を探す。"""
    table = re.compile(re.escape(lookup["table"]) + r"(?![0-9０-９-])")
    url = ESTAT_FILES_LIST.format(tstat=lookup["tstat"], tclass1=lookup["tclass1"],
                                  tclass2=f"&tclass2={tclass2}&tclass3val=0", page="{page}")
    for html in _pages(url, downloader):
        prev = 0
        for m in re.finditer(r"statInfId=(\d+)", html):
            # 直前の statInfId からこのリンクまでの文字に表題がある（同じ表の Excel・CSV のリンクが続くこともある）
            if table.search(_text(html[prev:m.start()])):
                return m.group(1)
            prev = m.end()
    return None


def find_file_ids_flat(lookup: dict, downloader, max_pages: int = 80) -> dict[str, str]:
    """都道府県の分類を経ずに、提供分類1の一覧（全都道府県のファイルが並ぶ）から表番号と都道府県名で探す。"""
    from .regions import PREFECTURES
    table = re.compile(re.escape(lookup["table"]) + r"(?![0-9０-９-])")
    by_name = {name: code for code, name in PREFECTURES.items()}
    url = ESTAT_FILES_LIST.format(tstat=lookup["tstat"], tclass1=lookup["tclass1"], tclass2="&tclass2val=0", page="{page}")
    out: dict[str, str] = {}
    for html in _pages(url, downloader, max_pages):
        prev = 0
        for m in re.finditer(r"statInfId=(\d+)", html):
            text = _text(html[prev:m.start()])
            prev = m.end()
            name = next((n for n in by_name if n in text), None)
            if name and table.search(text) and by_name[name] not in out:
                out[by_name[name]] = m.group(1)
    return out


def _describe_list(lookup: dict, downloader) -> str:
    """一覧のページの形がわからないときの手がかり（リンクの形と本文の冒頭）。"""
    url = ESTAT_FILES_LIST.format(tstat=lookup["tstat"], tclass1=lookup["tclass1"], tclass2="&tclass2val=0", page=1)
    html = _PAGE_CACHE.get((downloader, url)) or downloader(url).decode("utf-8", errors="replace")
    links = sorted({re.sub(r"\d{6,}", "N", h) for h in re.findall(r'href="([^"]*)"', html) if "stat" in h.lower()})
    return f"{len(html)} 文字、リンク {links[:15]}、本文 {_text(html)[:400]!r}"


# 推測した statInfId で取得し、中身を確かめたファイル（取得の段階で取り直さないために残す）
_VERIFIED: dict[str, bytes] = {}
GUESS_SPREAD = 2  # 推測した番号の前後いくつまで試すか
GUESS_SPREAD_WIDE = 80  # 分かっている番号が1つだけで見つからないとき（都道府県ごとに表がまとまる並び方など）


def estat_file_matches(data: bytes, table: str, pref: str) -> bool:
    """e-Stat「ファイル」の小地域集計CSVが、その表（例: 第13表）でその都道府県のものか。"""
    text = data[:200_000].decode("cp932", errors="replace")
    records = list(csv.reader(io.StringIO(text)))
    title = re.compile(re.escape(table) + r"(?![0-9０-９-])")
    if not any(title.search(",".join(r)) for r in records[:6]):
        return False
    at = next((i for i, r in enumerate(records) if "市区町村コード" in [c.strip() for c in r]), None)
    if at is None:
        return False
    col = [c.strip() for c in records[at]].index("市区町村コード")
    codes = [r[col].strip() for r in records[at + 1:at + 50] if len(r) > col and r[col].strip().isdigit()]
    return bool(codes) and all(c[:2] == pref for c in codes)


def _guess_file_id(cfg: dict, ids: dict[str, str], pref: str, downloader, wide: bool = True) -> str | None:
    """一覧から探せないとき: 同じ表の statInfId は都道府県の順に一定の間隔で並んでいるので、分かっている都道府県の
    番号から推測し、取得した中身（表番号と地域コード）で確かめる。e-Stat の一覧は画面の処理で作られ、HTML からは読めない。
    間隔は分かっている2つの都道府県から求める（1つしか分からないときは1とし、見つからなければ広く探す）。"""
    known = sorted((int(p), int(i)) for p, i in ids.items() if i.isdigit())
    if not known or not cfg.get("download_url"):
        return None
    target = int(pref)
    near = sorted(known, key=lambda kv: abs(kv[0] - target))
    p0, i0 = near[0]
    step = 1
    if len(near) > 1 and near[1][0] != p0:
        step = max(1, round((near[1][1] - i0) / (near[1][0] - p0)))
    guess = i0 + step * (target - p0)
    spreads = [GUESS_SPREAD] if len(known) > 1 or not wide else [GUESS_SPREAD, GUESS_SPREAD_WIDE]
    tried: set[int] = set()
    for spread in spreads:
        for delta in sorted(range(-spread, spread + 1), key=abs):
            n = guess + delta
            if n in tried:
                continue
            tried.add(n)
            sid = f"{n:012d}"
            url = cfg["download_url"].replace("{pref}", pref).replace("{id}", sid)
            try:
                data = downloader(url)
            except Exception:  # noqa: BLE001 - 番号がない・取得できないときは次の候補へ
                continue
            if estat_file_matches(data, cfg["estat_lookup"]["table"], pref):
                _VERIFIED[url] = data
                return sid
    return None


def resolve_file_ids(key: str, cfg: dict, dest: Path, prefs: list[str], downloader) -> dict[str, str]:
    """estat_lookup の出典の、都道府県ごとの statInfId。調べた結果は data/raw/<キー>/_ids.json に残す。"""
    path = dest / "_ids.json"
    ids: dict[str, str] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    ids.update(cfg.get("known_ids", {}))
    # 探しても見つからなかった都道府県は記録し、毎回探し直さない（_missing.json を消せば探し直す）
    miss_path = dest / "_missing.json"
    not_found: list[str] = json.loads(miss_path.read_text(encoding="utf-8")) if miss_path.exists() else []
    missing = [p for p in prefs if p not in ids and p not in not_found]
    if missing:
        lookup = cfg["estat_lookup"]
        classes = find_prefecture_classes(lookup, downloader)
        print(f"[{key}] e-Stat の都道府県の分類 {len(classes)} 件")
        flat = {} if classes else find_file_ids_flat(lookup, downloader)
        if not classes:
            print(f"[{key}] 一覧から直接探して {len(flat)} 件")
            if not flat:
                print(f"[{key}] 一覧のページ: {_describe_list(lookup, downloader)}")
        wide = True  # 広く探すのは1回の実行で一度だけ（見つからなければほかの都道府県でも見つからない）
        for pref in missing:
            found = (flat.get(pref) or (classes.get(pref) and find_file_id(lookup, classes[pref], downloader))
                     or _guess_file_id(cfg, ids, pref, downloader, wide))
            if found:
                ids[pref] = found
            else:
                wide = False
                not_found.append(pref)
                print(f"[{key}] {pref}: {lookup['table']} のファイルが見つかりません（この都道府県は取り込みません）")
        dest.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ids, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        if not_found:
            miss_path.write_text(json.dumps(sorted(set(not_found))), encoding="utf-8")
    return ids


def fetch_source(key: str, cfg: dict, dest: Path, downloader=download,
                 prefs: list[str] | None = None) -> list[Path]:
    if cfg.get("per_prefecture"):
        files: list[Path] = []
        targets = source_prefectures(cfg, prefs or [])
        ids = resolve_file_ids(key, cfg, dest, targets, downloader) if cfg.get("estat_lookup") else {}
        for pref in targets:
            if cfg.get("estat_lookup") and pref not in ids:
                continue
            # {pref_dir} は都道府県ごとのフォルダ名（例: 国立教育政策研究所の 13_tokyo）。pref_dirs に書く
            url = (cfg["download_url"].replace("{pref}", pref).replace("{id}", ids.get(pref, ""))
                   .replace("{pref_dir}", cfg.get("pref_dirs", {}).get(pref, "")))
            sub = dest / pref
            cached = _already_fetched(sub, url)
            if cached is None:
                name = cfg.get("download_filename", "").replace("{pref}", pref) or None
                get = (lambda u: _VERIFIED.pop(u, None) or downloader(u))
                cached = fetch_source(f"{key}/{pref}", {**cfg, "per_prefecture": False, "download_url": url,
                                                        "download_filename": name}, sub, get)
            files += cached
        return files
    if cfg.get("download_files"):
        return _fetch_files(key, cfg["download_files"], dest, downloader)
    url = cfg.get("download_url")
    if url and cfg.get("cache") and (cached := _already_fetched(dest, url)):
        return cached  # 変わらないファイル（過去の年の統計など）は取得済みのものを使う
    if not url:
        raise FetchError(f"[{key}] download_url が未設定です。手動で取得してください: {cfg['url']}")
    try:
        data = downloader(url)
    except (FetchError, OSError) as e:
        # 配布元が一時的に（または GitHub Actions からの接続を）拒んだとき、前回の取得分（キャッシュ）があれば使う
        prior = _already_fetched(dest, url)
        if prior is None:
            raise
        print(f"[{key}] 取得できないため前回の取得分を使います（{e}）", file=sys.stderr)
        return prior
    if _looks_like_html(data):
        raise FetchError(f"[{key}] ファイルではなくHTMLが返されました。URLを確認してください: {url}")
    dest.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(io.BytesIO(data)) and not _is_office_file(data):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            files = _safe_extract(z, dest)
    else:
        name = cfg.get("download_filename") or Path(url.split("?")[0]).name or "download.bin"
        target = dest / name
        rule = cfg.get("keep_rows")
        target.write_bytes(keep_rows(data, rule["column"], str(rule["value"]), cfg.get("encoding", "cp932"))
                           if rule else data)
        files = [target]
    (dest / "_fetch.json").write_text(json.dumps({
        "url": url, "retrieved_at": now_iso(), "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "files": [f.relative_to(dest).as_posix() for f in files],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return files


def _fetch_files(key: str, urls: dict[str, str], dest: Path, downloader) -> list[Path]:
    """1つの出典が複数のファイルからなる場合（download_files = {保存名 = URL}）。"""
    dest.mkdir(parents=True, exist_ok=True)
    files, meta = [], []
    for name, url in urls.items():
        try:
            data = downloader(url)
        except (FetchError, OSError) as e:
            prior = _already_fetched_files(dest, urls)
            if prior is None:
                raise
            print(f"[{key}] 取得できないため前回の取得分を使います（{e}）", file=sys.stderr)
            return prior
        if _looks_like_html(data):
            raise FetchError(f"[{key}] {name}: ファイルではなくHTMLが返されました。URLを確認してください: {url}")
        target = dest / name
        target.write_bytes(data)
        files.append(target)
        meta.append({"url": url, "file": name, "bytes": len(data),
                     "sha256": hashlib.sha256(data).hexdigest()})
    (dest / "_fetch.json").write_text(json.dumps({
        "retrieved_at": now_iso(), "downloads": meta,
        "files": [f.relative_to(dest).as_posix() for f in files],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return files
