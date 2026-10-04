// サイトの Worker。静的ファイル（ページを含む）は Workers Static Assets がそのまま返し、
// ここに来るのは wrangler.jsonc の run_worker_first に書いた /api/* だけ（設計変更記録 #32）。
// 独自ドメインへの転送は Worker では行わない（#61。www は Cloudflare の Redirect Rules、workers.dev はページ内のスクリプト）。
import ids from "../src/generated/indicator-ids.json";
import { handleUsage, type AnalyticsEngineDataset } from "./usage";

interface Env {
  ASSETS: { fetch(request: Request): Promise<Response> };
  USAGE?: AnalyticsEngineDataset;
}

const INDICATOR_IDS: ReadonlySet<string> = new Set(ids as string[]);

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const { pathname } = new URL(request.url);
    if (pathname === "/api/usage") return handleUsage(request, env.USAGE, INDICATOR_IDS);
    if (pathname.startsWith("/api/")) return new Response("Not Found", { status: 404 });
    return env.ASSETS.fetch(request);
  },
};
