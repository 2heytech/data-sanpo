// 検索エンジンへの掲載を許可するか。本公開（独自ドメイン）までは止めておき、
// 公開時に環境変数 ALLOW_INDEXING=true でビルドする（設計変更記録 #19）。
export const ALLOW_INDEXING = process.env.ALLOW_INDEXING === "true";

// 検索エンジンには、地図の状態付きの URL（/map/?i=…&a=…）を巡回させない。地域ページ・指標ページから約5万7千通りリンクしていて、
// どれも canonical は /map/ なのに、Googlebot の巡回がこれに取られて地域ページが後回しになっていた（設計変更記録 #151）。
// SNS のリンクの表示（X などの読み取り）は止めないよう、Google と Bing の巡回だけに絞る。/map/ そのものは読める
const SEARCH_CRAWLERS = ["Googlebot", "Bingbot"];

/** robots.txt の中身。adsClient は AdSense の発行者ID（なければ空） */
export function robotsBody(allowIndexing: boolean, sitemap: string, adsClient: string): string {
  if (!allowIndexing) {
    // 検索エンジンに載せない間も、広告を設定したら AdSense のクローラ（広告の審査・配信用。検索には載せない）だけは読めるようにする（#62）
    const adsCrawler = adsClient ? "User-agent: Mediapartners-Google\nAllow: /\n\n" : "";
    return `${adsCrawler}User-agent: *\nDisallow: /\n`;
  }
  const search = SEARCH_CRAWLERS.map((ua) => `User-agent: ${ua}\n`).join("");
  return `User-agent: *\nAllow: /\n\n${search}Disallow: /map/?\n\nSitemap: ${sitemap}\n`;
}
