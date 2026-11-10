// 検索エンジンへの掲載を許可するか。本公開（独自ドメイン）までは止めておき、
// 公開時に環境変数 ALLOW_INDEXING=true でビルドする（設計変更記録 #19）。
export const ALLOW_INDEXING = process.env.ALLOW_INDEXING === "true";

// 検索エンジンには、地図の状態付きの URL（/map/?i=…&a=…）を巡回させない。地域ページ・指標ページから約5万7千通りリンクしていて、
// どれも canonical は /map/ なのに、Googlebot の巡回がこれに取られて地域ページが後回しになっていた（設計変更記録 #151）。
// SNS のリンクの表示（X などの読み取り）は止めないよう、検索や AI のクローラーの巡回だけに絞る。/map/ そのものは読める。
// AI のクローラーも同じ URL に巡回を取られていた（2026-11 の7日間で AI のクローラーの約9割が /map/?…）ので、
// 巡回して集めるものを足す。人が頼んだときに開くもの（ChatGPT-User など）は入れない（設計変更記録 #220）
const SEARCH_CRAWLERS = [
  "Googlebot", "Bingbot",
  "OAI-SearchBot", "GPTBot", "PerplexityBot", "Amazonbot", "ClaudeBot", "Claude-SearchBot", "Applebot", "Meta-ExternalAgent",
];

/** robots.txt の中身 */
export function robotsBody(allowIndexing: boolean, sitemap: string): string {
  if (!allowIndexing) return "User-agent: *\nDisallow: /\n";
  const search = SEARCH_CRAWLERS.map((ua) => `User-agent: ${ua}\n`).join("");
  return `User-agent: *\nAllow: /\n\n${search}Disallow: /map/?\n\nSitemap: ${sitemap}\n`;
}
