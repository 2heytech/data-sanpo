# 開発メモ（Claude 用）

- 設計の原本（基本設計書 v1）は公開リポジトリに置かない。プロジェクトの共有ファイル tokyo-data-map/docs/design-v1.md にある。設計を変えたら docs/design-changes.md に番号付きで「何を・なぜ」を追記する。
- やりとり・文書・コメントは日本語。
- データの原則: 欠測・秘匿を 0 にしない／元データより細かく割り振らない／率は分子・分母から計算。
- 指標を追加するときは pipeline/config/indicators.toml に定義し、取込処理と fixture（tdm/fixture.py）にも例を足す。
- 確認: `cd pipeline && python3 -m pytest`、`cd web && npm run fixture && npm run check && npm test && npm run build`。
