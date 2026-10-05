# データさんぽ

[データさんぽ](https://data-sanpo.com) のソースコード。国勢調査などの公開統計を、都道府県・市区町村・町丁目の地図で見られるサイトです。

- 設計: 基本設計書 v1（2026-10-03）からの変更点を [docs/design-changes.md](docs/design-changes.md) に記録しています（設計書の原本はこのリポジトリに置いていません）
- 構成: Python + SQLite でデータを管理・加工 → JSON/GeoJSON を生成 → Astro で静的サイトをビルド →
  Cloudflare Workers Static Assets で配信。地図は MapLibre GL JS + 地理院タイル。閲覧時にDBへは接続しない。

```
pipeline/   取得・加工・検証・公開ファイル生成（Python, SQLite）
  config/   出典（sources.toml）と指標カタログ（indicators.toml）
  tdm/      処理本体。schema.sql が管理用DBの定義
web/        サイト本体（Astro, TypeScript, MapLibre）
docs/       設計書と変更記録
data/       元データ・DB・公開版（Git管理外）
```

## 必要なもの

- Python 3.11 以上、Node.js 22 以上

```sh
python3 -m pip install -e "pipeline[dev]"
cd web && npm install
```

## 架空データで動かす（開発用）

```sh
cd web
npm run fixture   # 架空データで pipeline を実行し、web/public/data に配置
npm run dev       # http://localhost:4321/
```

画面上部に「開発用の架空データ」と表示されます。

## 実データで動かす

### GitHub Actions で実行（推奨）

Actions タブの「Data release」を手動実行すると、e-Stat からの取得 → 検証 → 公開版生成 → サイトのビルドを行い、
結果を Artifacts に保存します。`deploy` をオンにすると Cloudflare にデプロイします
（Secrets に `CLOUDFLARE_API_TOKEN` と `CLOUDFLARE_ACCOUNT_ID`、Variables に本番URLの `SITE_URL` が必要）。

画面や文言だけを直したときは `site_only` をオンにすると、データは作り直さずに前回全国で公開したデータ
（GitHub Release `published-data` に保存）でサイトだけビルドします。取込・書き出し（`pipeline/tdm`・`pipeline/config`）を
変えたときは使えません（ワークフローが止めます）。

### 手元のPCで実行

`python -m tdm fetch` で取得するか、行政サイトのファイルを手動でダウンロードして `data/raw/<出典キー>/` に置きます。

| 出典キー | 内容 | 置くファイル |
|---|---|---|
| `census2020_small_area_boundary` | 令和2年国勢調査 小地域境界 東京都（世界測地系緯度経度・Shapefile） | 展開した `.shp` `.dbf` `.shx` `.prj` |
| `census2020_small_area_population` | 小地域集計 東京都 男女別人口総数及び世帯総数 | `.txt` または `.csv` |
| `census2020_small_area_age` | 小地域集計 東京都 年齢（5歳階級、4区分）別、男女別人口 | `.txt` または `.csv` |

入手先のURLは `pipeline/config/sources.toml` を参照してください。

```sh
cd pipeline
python3 -m tdm build --release-id 20261003-census2020   # 取込 → 検証 → 公開版の生成
cd ../web
npm run prepare-data   # data/releases の最新版を配置（DATA_RELEASE_DIR で指定も可）
npm run dev
```

列名が想定と違う場合は、取込時にファイルの項目名一覧を表示して止まります。
`pipeline/config/indicators.toml` の `column` 等に実際の項目名を追加してください。

## テストとビルド

```sh
cd pipeline && python3 -m pytest
cd web && npm run check && npm test && npm run build
```

## 公開（Cloudflare Workers Static Assets）

```sh
cd web
npm run build
npx wrangler login
npm run deploy
```

公開版のデータ（`data/releases/<release_id>/`）と Git の commit を `manifest.json` で紐付けています。
障害時は `npx wrangler rollback` で直前のデプロイに戻します。

## データの扱い（要点）

- 欠測・秘匿は「値なし」として表示し、0 に置き換えない
- 区市町村の割合は町丁目の割合の平均ではなく、区市町村の人数から計算する
- 分母が小さい町丁目の割合は表示しない（`min_denominator`）
- 再配布条件を満たさない出典（`redistributable = false`）は公開ファイルに出力しない

## ライセンス

- コード: [MIT License](LICENSE)
- サイトで公開している加工済みのデータ（JSON・GeoJSON など）: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ja)。
  使うときは「データさんぽ（https://data-sanpo.com）が加工」と、元データの出典をあわせて表示してください。
  元データの出典と利用規約は `pipeline/config/sources.toml` とサイトの「出典」ページにあります。
- サイト名「データさんぽ」・ロゴ・サイトの文章: 上の2つの対象外で、権利を留保します。
