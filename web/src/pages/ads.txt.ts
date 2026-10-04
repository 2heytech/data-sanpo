import type { APIRoute } from "astro";
import { ADSENSE_CLIENT } from "../lib/ads";

// 広告の販売者を宣言する ads.txt（設計変更記録 #62）。発行者IDは変数 ADSENSE_CLIENT（ca-pub-…）から作る。
// f08c47fec0942fa0 は Google の認証機関ID（AdSense ヘルプの指定どおり）。
export const GET: APIRoute = () => {
  const body = ADSENSE_CLIENT
    ? `google.com, ${ADSENSE_CLIENT.replace(/^ca-/, "")}, DIRECT, f08c47fec0942fa0\n`
    : "# 広告は配信していません\n";
  return new Response(body, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
};
