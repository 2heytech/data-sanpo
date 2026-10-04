"""指標の利用回数を Workers Analytics Engine から集計して表にする（設計変更記録 #32）。

  CLOUDFLARE_ACCOUNT_ID と、Account Analytics の読み取り権限があるトークン
  CLOUDFLARE_ANALYTICS_TOKEN（なければ CLOUDFLARE_API_TOKEN）を環境変数で渡す。
  python3 web/scripts/usage-report.py [日数]   （既定 30日、Markdown の表を出力）
"""
import json
import os
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

DATASET = "tdm_indicator_usage"
ROOT = Path(__file__).resolve().parents[2]


def query(account: str, token: str, sql: str) -> list[dict]:
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{account}/analytics_engine/sql",
        data=sql.encode(),
        headers={"Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return json.load(res)["data"]
    except urllib.error.HTTPError as e:
        sys.exit(f"集計の取得に失敗しました（HTTP {e.code}）: {e.read().decode(errors='replace')[:500]}")


def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    token = os.environ.get("CLOUDFLARE_ANALYTICS_TOKEN") or os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if not account or not token:
        sys.exit("CLOUDFLARE_ACCOUNT_ID と CLOUDFLARE_ANALYTICS_TOKEN（または CLOUDFLARE_API_TOKEN）を設定してください")
    rows = query(account, token, f"""
        SELECT blob1 AS indicator, blob2 AS how, SUM(_sample_interval) AS hits
        FROM {DATASET}
        WHERE timestamp > NOW() - INTERVAL '{days}' DAY
        GROUP BY indicator, how
        FORMAT JSON""")
    names = {k: v["name"] for k, v in tomllib.loads((ROOT / "pipeline/config/indicators.toml").read_text()).items()}
    counts: dict[str, dict[str, int]] = {}
    for r in rows:
        counts.setdefault(r["indicator"], {"open": 0, "switch": 0})[r["how"]] = int(float(r["hits"]))
    order = sorted(counts.items(), key=lambda kv: (-(kv[1]["open"] + kv[1]["switch"]), kv[0]))
    print(f"## 指標の利用回数（直近 {days} 日）\n")
    if not order:
        print("まだ記録がありません。")
        return
    print("| 指標 | 合計 | 切り替えて表示 | ページを開いたとき |")
    print("|---|--:|--:|--:|")
    for ind, c in order:
        print(f"| {names.get(ind, ind)} | {c['open'] + c['switch']:,} | {c['switch']:,} | {c['open']:,} |")
    print("\n「ページを開いたとき」は地図ページを開いた時点で表示された指標（既定の指標や共有URLの指標）です。")


if __name__ == "__main__":
    main()
