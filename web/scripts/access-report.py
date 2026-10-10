"""サイトの訪問状況を Cloudflare から集計し、前の7日と比べて目立つ変化を書き出す（設計変更記録 #91）。

  CLOUDFLARE_ACCOUNT_ID と、Account Analytics の読み取り権限があるトークン
  CLOUDFLARE_ANALYTICS_TOKEN（なければ CLOUDFLARE_API_TOKEN）を環境変数で渡す。
  python3 web/scripts/access-report.py   （Markdown を出力。最後の行は「ALERTS_JSON: {...}」）

  日付は日本時間で区切る。public リポジトリでは実行結果を誰でも見られるので、
  出すのは日ごとの合計と、変化があったときの国・参照元の名前だけにする。
"""
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

HOST = "data-sanpo.com"
JST = timezone(timedelta(hours=9))
API = "https://api.cloudflare.com/client/v4"

# 「変化」とみなす目安
# Web Analytics の数は抜き取り調査からの推計で、訪問が少ないうちは10単位で揺れるので、
# 増減はページビューで見て、少ない日の揺れを拾わないよう下限を置く。
RATIO_UP = 2.0  # 前7日平均の2倍以上
RATIO_DOWN = 0.5  # 前7日平均の半分以下
MIN_VIEWS = 100  # 前日か前7日平均のどちらかがこれ以上のときだけ増減を見る
NEW_COUNTRY_MIN = 30  # 前7日に無かった国が前日にこのページビュー以上
NEW_REFERER_MIN = 10  # 前7日に無かった参照元が前日にこの訪問数以上
REQ_RATIO_UP = 3.0  # リクエスト数（ボットを含む）が前7日平均の3倍以上
REQ_MIN = 5000


def call(token: str, url: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.load(res)


def graphql(token: str, query: str, variables: dict) -> dict:
    res = call(token, f"{API}/graphql", {"query": query, "variables": variables})
    if res.get("errors"):
        raise RuntimeError("; ".join(e.get("message", "") for e in res["errors"])[:500])
    return res["data"]


RUM_QUERY = """
query($account: String!, $start: Time!, $end: Time!) {
  viewer { accounts(filter: {accountTag: $account}) {
    rows: rumPageloadEventsAdaptiveGroups(limit: 10000,
        filter: {datetime_geq: $start, datetime_lt: $end, requestHost: "%s"}) {
      count
      sum { visits }
      dimensions { datetimeHour countryName refererHost }
    }
  } }
}""" % HOST

ZONE_QUERY = """
query($zone: String!, $start: Date!, $end: Date!) {
  viewer { zones(filter: {zoneTag: $zone}) {
    rows: httpRequests1dGroups(limit: 100, filter: {date_geq: $start, date_leq: $end}) {
      sum { requests }
      dimensions { date }
    }
  } }
}"""


def jst_day(ts: str) -> str:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(JST).strftime("%Y-%m-%d")


def changed(today: float, base: float, minimum: float, up: float, down: float | None) -> str | None:
    if max(today, base) < minimum:
        return None
    if base == 0:
        return "up" if today >= minimum else None
    r = today / base
    if r >= up:
        return "up"
    if down is not None and r <= down:
        return "down"
    return None


def main() -> None:
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    token = os.environ.get("CLOUDFLARE_ANALYTICS_TOKEN") or os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if not account or not token:
        sys.exit("CLOUDFLARE_ACCOUNT_ID と CLOUDFLARE_ANALYTICS_TOKEN（または CLOUDFLARE_API_TOKEN）を設定してください")

    today0 = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    days = [(today0 - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(8, 0, -1)]  # 古い順、最後が前日
    target, prev = days[-1], days[:-1]
    start = (today0 - timedelta(days=8)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = today0.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    visits: dict[str, float] = defaultdict(float)
    views: dict[str, float] = defaultdict(float)
    country: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    referer: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    data = graphql(token, RUM_QUERY, {"account": account, "start": start, "end": end})
    for r in data["viewer"]["accounts"][0]["rows"]:
        d = jst_day(r["dimensions"]["datetimeHour"])
        v = r["sum"]["visits"]
        visits[d] += v
        views[d] += r["count"]
        country[d][r["dimensions"]["countryName"] or "不明"] += r["count"]
        ref = (r["dimensions"]["refererHost"] or "").lower()
        if ref and not ref.endswith(HOST):
            referer[d][ref] += v

    # ボットを含むリクエスト数（ゾーンの読み取り権限がないトークンでは取れないので、取れたときだけ）
    requests: dict[str, float] | None = None
    note = ""
    try:
        zones = call(token, f"{API}/zones?name={HOST}")["result"]
        if zones:
            z = graphql(token, ZONE_QUERY, {"zone": zones[0]["id"],
                                            "start": (today0 - timedelta(days=9)).strftime("%Y-%m-%d"),
                                            "end": target})
            # この集計は UTC の日付で区切られる
            requests = {r["dimensions"]["date"]: r["sum"]["requests"] for r in z["viewer"]["zones"][0]["rows"]}
        else:
            note = "ゾーンが見つからないため、リクエスト数は出していません。"
    except (urllib.error.HTTPError, RuntimeError, KeyError, IndexError) as e:
        note = f"リクエスト数は取得できませんでした（{str(e)[:120]}）。"

    alerts: list[dict] = []
    base_views = sum(views[d] for d in prev) / len(prev)
    if (k := changed(views[target], base_views, MIN_VIEWS, RATIO_UP, RATIO_DOWN)):
        alerts.append({"kind": f"pageviews_{k}", "day": target, "value": views[target], "prev_avg": round(base_views, 1)})
    seen_c = {c for d in prev for c in country[d]}
    for c, v in sorted(country[target].items(), key=lambda kv: -kv[1]):
        if c not in seen_c and v >= NEW_COUNTRY_MIN:
            alerts.append({"kind": "new_country", "day": target, "name": c, "value": v})
    seen_r = {h for d in prev for h in referer[d]}
    for h, v in sorted(referer[target].items(), key=lambda kv: -kv[1]):
        if h not in seen_r and v >= NEW_REFERER_MIN:
            alerts.append({"kind": "new_referer", "day": target, "name": h, "value": v})
    if requests:
        rdays = sorted(requests)
        if len(rdays) >= 2:
            last, before = rdays[-1], rdays[-8:-1]
            base_req = sum(requests[d] for d in before) / len(before)
            if changed(requests[last], base_req, REQ_MIN, REQ_RATIO_UP, None):
                alerts.append({"kind": "requests_up", "day": last, "value": requests[last], "prev_avg": round(base_req)})

    print(f"## 訪問状況（日本時間、{days[0]}〜{target}）\n")
    print("| 日付 | 訪問数 | ページビュー |")
    print("|---|--:|--:|")
    for d in days:
        print(f"| {d} | {visits[d]:,.0f} | {views[d]:,.0f} |")
    if requests:
        print("\n| 日付（UTC） | リクエスト数（ボットを含む） |")
        print("|---|--:|")
        for d in sorted(requests)[-8:]:
            print(f"| {d} | {requests[d]:,.0f} |")
    if note:
        print(f"\n{note}")
    print(f"\n前日（{target}）の目立つ変化: {len(alerts)} 件（数は抜き取りからの推計）")
    print("\nALERTS_JSON: " + json.dumps({"day": target, "visits": visits[target], "pageviews": views[target],
                                         "prev_avg_pageviews": round(base_views, 1),
                                         "alerts": alerts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
