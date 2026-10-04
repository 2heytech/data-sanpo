// 検索エンジンへの掲載を許可するか。本公開（独自ドメイン）までは止めておき、
// 公開時に環境変数 ALLOW_INDEXING=true でビルドする（設計変更記録 #19）。
export const ALLOW_INDEXING = process.env.ALLOW_INDEXING === "true";
