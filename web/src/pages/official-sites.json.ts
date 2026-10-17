import type { APIRoute } from "astro";
import sites from "../data/official-sites.json";

// 都道府県・市区町村の公式サイトの URL（Wikidata から集めたもの。web/scripts/official-sites.py で作る）。
// 地図の右の欄が、地域を初めて選んだときに読む（設計変更記録 #135）
export const GET: APIRoute = () =>
  new Response(JSON.stringify(sites), { headers: { "Content-Type": "application/json; charset=utf-8" } });
