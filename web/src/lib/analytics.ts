// アクセス解析の設定。
// Cloudflare Web Analytics（Cookie を使わないアクセス解析、設計変更記録 #32）。Google アナリティクス（#255）と並べて使う。
// サイトのトークンはビルド時の環境変数 CF_WEB_ANALYTICS_TOKEN（GitHub のリポジトリ変数）で渡す。
// 未設定・形式違いならスクリプトを出さない。
const raw = (process.env.CF_WEB_ANALYTICS_TOKEN ?? "").trim();
export const CF_WEB_ANALYTICS_TOKEN = /^[0-9a-f]{32}$/i.test(raw) ? raw : "";
if (raw && !CF_WEB_ANALYTICS_TOKEN) {
  console.warn("CF_WEB_ANALYTICS_TOKEN の形式が違うため Web Analytics を入れません（英数字32文字のトークンだけを設定してください）");
}

// Google アナリティクス（GA4。設計変更記録 #255）。地図で選んだ指標・共有・楽天のリンクなど、操作ごとの回数を見るために使う。
// 測定 ID はページに載る公開値なので、ここに書く。空なら何も出さない。
// 読み込むのは公開サイトのドメインで開いたときだけ（手元・画面写真用のビルドを開いても送らない。判定は Base.astro）
export const GA_MEASUREMENT_ID = "G-86JN82EKNH";
