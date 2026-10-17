import type { APIRoute } from "astro";
import { loadAreas } from "../../../lib/data";
import { choroplethPng } from "../../../lib/mapImage";
import { prefectureImage, type ShareImage } from "../../../lib/shareImages";

// 都道府県ページに置く、市区町村別の人口増加率の地図の画像（設計変更記録 #142）
export function getStaticPaths() {
  return loadAreas().prefectures.flatMap((pref) => {
    const image = prefectureImage(pref);
    return image ? [{ params: { code: pref.code }, props: { image } }] : [];
  });
}

export const GET: APIRoute = ({ props }) =>
  new Response(choroplethPng((props.image as ShareImage).spec()), { headers: { "Content-Type": "image/png" } });
