import type { APIRoute } from "astro";
import { ADSENSE_CLIENT } from "../lib/ads";
import { ALLOW_INDEXING, robotsBody } from "../lib/indexing";

export const GET: APIRoute = ({ site }) => {
  const body = robotsBody(ALLOW_INDEXING, String(new URL("sitemap-index.xml", site)), ADSENSE_CLIENT);
  return new Response(body, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
};
