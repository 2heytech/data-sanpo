import type { APIRoute } from "astro";
import { loadIndicators } from "../../../lib/data";
import { choroplethPng } from "../../../lib/mapImage";
import { indicatorPageImage, type ShareImage } from "../../../lib/shareImages";

// 指標ページの冒頭に置く、その指標の全国の地図の画像（設計変更記録 #190）。
// 冒頭の「データから分かること」を出さない指標（犯罪など）は作らない
export function getStaticPaths() {
  return loadIndicators().flatMap((ind) => {
    const image = indicatorPageImage(ind);
    return image ? [{ params: { id: ind.id }, props: { image } }] : [];
  });
}

export const GET: APIRoute = async ({ props }) =>
  new Response(await choroplethPng((props.image as ShareImage).spec()), { headers: { "Content-Type": "image/png" } });
