import type { APIRoute } from "astro";
import { ADSENSE_CLIENT } from "../lib/ads";
import { ALLOW_INDEXING } from "../lib/indexing";

export const GET: APIRoute = ({ site }) => {
  // 検索エンジンに載せない間も、広告を設定したら AdSense のクローラ（広告の審査・配信用。検索には載せない）だけは読めるようにする（#62）
  const adsCrawler = ADSENSE_CLIENT ? "User-agent: Mediapartners-Google\nAllow: /\n\n" : "";
  const body = ALLOW_INDEXING
    ? `User-agent: *\nAllow: /\n\nSitemap: ${new URL("sitemap-index.xml", site)}\n`
    : `${adsCrawler}User-agent: *\nDisallow: /\n`;
  return new Response(body, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
};
