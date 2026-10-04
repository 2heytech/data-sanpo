// Cloudflare Web Analytics（Cookie を使わないアクセス解析、設計変更記録 #32）。
// サイトのトークンはビルド時の環境変数 CF_WEB_ANALYTICS_TOKEN（GitHub のリポジトリ変数）で渡す。
// 未設定・形式違いならスクリプトを出さない。
const raw = (process.env.CF_WEB_ANALYTICS_TOKEN ?? "").trim();
export const CF_WEB_ANALYTICS_TOKEN = /^[0-9a-f]{32}$/i.test(raw) ? raw : "";
if (raw && !CF_WEB_ANALYTICS_TOKEN) {
  console.warn("CF_WEB_ANALYTICS_TOKEN の形式が違うため Web Analytics を入れません（英数字32文字のトークンだけを設定してください）");
}
