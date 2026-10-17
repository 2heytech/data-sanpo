"""都道府県・市区町村の公式サイトの URL を Wikidata から集め、web/src/data/official-sites.json に書く（設計変更記録 #135）。

地図の右の欄で「〇〇の公式サイト」を別のタブで開くために使う。Wikidata のデータは CC0（出典の表示や再配布の条件なし）。
地方公共団体コード（P429）を持つ項目の「公式ウェブサイト」（P856）から、公開版の地域ごとに1つ選ぶ。

  python3 web/scripts/official-sites.py <公開版の areas.json のパスか URL> [--check]

  --check を付けると、選んだ URL を開いて確かめる。
    - 別のドメインへ転送されたら転送先を使う（例: city.saitama.jp → city.saitama.lg.jp）
    - 名前が引けない（DNS）・404・410、または開けたページの題名に地域の名前がなければ載せない
    - 応答がない・拒否された（海外からの接続を断る自治体が多い）ものは、自治体のドメインの形
      （lg.jp、または city./town./vill./pref. で始まる .jp）なら載せ、そうでなければ載せない
  取れない地域は載せない（地図にもリンクを出さない）。
"""
import json
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html import unescape
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "data" / "official-sites.json"
UA = "data-sanpo-official-sites/1.0 (https://data-sanpo.com)"
JAPANESE = "Q5287"
QUERY = """
SELECT ?item ?code ?label ?site ?rank ?lang ?until ?dissolved WHERE {
  ?item p:P429 ?cs . ?cs ps:P429 ?code .
  ?item p:P856 ?ws . ?ws ps:P856 ?site . ?ws wikibase:rank ?rank .
  OPTIONAL { ?ws pq:P407 ?lang . }
  OPTIONAL { ?ws pq:P582 ?until . }
  OPTIONAL { ?item wdt:P576 ?dissolved . }
  OPTIONAL { ?item rdfs:label ?label FILTER(LANG(?label) = "ja") }
}
"""
# Wikidata の値が別の自治体のサイトや自治体以外のサイトを指していたもの（2026-10-17 に確かめた）。直るまで載せない
EXCLUDE = {
    "muni-02381": "板柳町の項目に鶴田町のサイトが入っている",
}
# 題名に漢字の名前がないが、開いて自治体のサイトだと確かめたもの
TITLE_OK = {
    "muni-01465": "題名がひらがな（けんぶち町）",
    "muni-22213": "題名が「ポータルサイト」",
    "muni-23563": "題名がひらがな（とよね村）",
    "muni-39405": "題名が異体字（梼原町）",
    "muni-46502": "題名が「トップページ」",
    "pref-05": "題名が「美の国あきたネット」",
    "pref-13": "題名が「都庁総合ホームページ」",
}
OFFICIAL_HOST = re.compile(r"(\.lg\.jp|^(www\d?\.)?(city|town|vill|pref)\.[a-z0-9.-]+\.jp)$")


def fetch(url: str, timeout: int = 30) -> tuple[str, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as res:
        return res.geturl(), res.read(300_000)


def load_areas(src: str) -> dict[str, str]:
    """公開版の地域（都道府県・市区町村）の id → 名前"""
    raw = fetch(src)[1] if src.startswith("http") else Path(src).read_bytes()
    areas = json.loads(raw)
    names = {f"pref-{p['code']}": p["name"] for p in areas["prefectures"]}
    names.update({m["id"]: m["name"] for m in areas["municipalities"]})
    return names


def entity_id(code: str) -> str:
    # 地方公共団体コードは検査数字つきの6桁。都道府県は「13000x」の形
    return f"pref-{code[:2]}" if code[2:5] == "000" else f"muni-{code[:5]}"


def candidates() -> dict[str, list[dict]]:
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": QUERY, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as res:
                rows = json.load(res)["results"]["bindings"]
            break
        except urllib.error.HTTPError as e:
            # 続けて問い合わせると断られる（429）ので、間をあけてやり直す
            if e.code != 429 or attempt == 3:
                raise
            time.sleep(int(e.headers.get("Retry-After") or 60) + 5)
    # 1つの値（文）に言語の修飾子が複数つくと行が分かれるので、文ごとにまとめる
    stmts: dict[tuple, dict] = {}
    for r in rows:
        v = {k: x["value"] for k, x in r.items()}
        key = (v["item"], v["site"], v["rank"])
        s = stmts.setdefault(key, {"id": entity_id(v["code"]), "label": v.get("label", ""), "site": v["site"],
                                   "rank": v["rank"].rsplit("#", 1)[-1], "langs": set(), "ended": False})
        if "lang" in v:
            s["langs"].add(v["lang"].rsplit("/", 1)[-1])
        if "until" in v or "dissolved" in v:
            s["ended"] = True
    out: dict[str, list[dict]] = {}
    for s in stmts.values():
        # 廃止された自治体（浜松市の旧区など）、終わった・非推奨の値、日本語以外のページは使わない
        if s["ended"] or s["rank"] == "DeprecatedRank" or (s["langs"] and JAPANESE not in s["langs"]):
            continue
        out.setdefault(s["id"], []).append(s)
    return out


def pick(cands: list[dict]) -> str:
    """推奨の順位 → .jp のドメイン → https → 短いパス（トップページ）の順で選ぶ"""
    def score(s: dict):
        u = urllib.parse.urlsplit(s["site"])
        return (s["rank"] != "PreferredRank", not (u.hostname or "").endswith(".jp"), u.scheme != "https",
                len(u.path.strip("/")), s["site"])
    return sorted(cands, key=score)[0]["site"]


def short_name(name: str) -> str:
    """題名と照らす名前。政令市の区は区の名前だけ（横浜市中区 → 中）、市町村は「市・町・村」を除く"""
    name = re.sub(r"^.+?市(?=.+区$)", "", name)
    return re.sub(r"(都|道|府|県|市|区|町|村)$", "", name)


def check(eid: str, name: str, url: str) -> tuple[str | None, str]:
    official = bool(OFFICIAL_HOST.search(urllib.parse.urlsplit(url).hostname or ""))
    for attempt in range(3):
        try:
            final, body = fetch(url)
            break
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None, f"HTTP {e.code}"
            return (url, f"HTTP {e.code}（載せる）") if official else (None, f"HTTP {e.code}")
        except Exception as e:  # noqa: BLE001
            reason = getattr(e, "reason", e)
            if isinstance(reason, socket.gaierror):
                return None, "名前が引けない"
            if attempt < 2:   # 接続が切れることがあるので、少し待って開き直す
                time.sleep(5)
                continue
            return (url, f"開けない（載せる）: {reason}") if official else (None, f"開けない: {reason}")
    m = re.search(rb'charset=["\']?([\w-]+)', body[:5000], re.I)
    try:
        text = body.decode(m.group(1).decode() if m else "utf-8", "replace")
    except LookupError:
        text = body.decode("utf-8", "replace")
    t = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
    title = unescape(t.group(1)).strip() if t else ""
    # 題名がない・文字化けしたページは名前を確かめられないので、自治体のドメインの形かどうかで決める
    if not title or "\ufffd" in title:
        if OFFICIAL_HOST.search(urllib.parse.urlsplit(final).hostname or ""):
            return final, ""
        return None, "題名が読めない"
    if short_name(name) not in title and eid not in TITLE_OK:
        return None, f"題名に名前がない: {title[:60]}"
    return final, ""


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    names = load_areas(args[0])
    found = candidates()
    sites = {eid: pick(found[eid]) for eid in names if eid in found and eid not in EXCLUDE}
    if "--check" in sys.argv:
        with ThreadPoolExecutor(16) as ex:
            results = dict(zip(sites, ex.map(lambda eid: check(eid, names[eid], sites[eid]), sites)))
        for eid, (url, note) in sorted(results.items()):
            if note:
                print(f"{eid} {names[eid]} {sites[eid]}: {note}", file=sys.stderr)
            if url:
                sites[eid] = url
            else:
                del sites[eid]
    missing = sorted(set(names) - set(sites))
    print(f"{len(sites)} / {len(names)} 地域。載せない: {', '.join(names[m] for m in missing)}", file=sys.stderr)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": "Wikidata の「公式ウェブサイト」（P856）。CC0",
        "retrieved": date.today().isoformat(),
        "sites": dict(sorted(sites.items())),
    }, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
