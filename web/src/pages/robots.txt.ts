import type { APIRoute } from "astro";
import { ALLOW_INDEXING, robotsBody } from "../lib/indexing";

export const GET: APIRoute = ({ site }) => {
  const body = robotsBody(ALLOW_INDEXING, String(new URL("sitemap-index.xml", site)));
  return new Response(body, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
};
