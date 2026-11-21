import type { APIRoute } from "astro";
import { mapFallbackData } from "../../lib/mapFallbackData";

// 地図を表示できない環境（WebGL2 が使えないなど）への案内で、選んでいた指標・地域のページへのリンクと静止画の地図を出すためのデータ。
// 案内を出すときだけ地図の処理（map/fallback.ts）が読む（設計変更記録 #196）
export const GET: APIRoute = () =>
  new Response(JSON.stringify(mapFallbackData()), { headers: { "Content-Type": "application/json; charset=utf-8" } });
