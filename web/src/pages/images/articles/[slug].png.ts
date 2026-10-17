import type { APIRoute } from "astro";
import { ARTICLES } from "../../../lib/articles";
import { choroplethPng } from "../../../lib/mapImage";
import { articleImage, type ShareImage } from "../../../lib/shareImages";

// 寄り道に置く、記事の主な指標の全国の地図の画像（設計変更記録 #142）
export function getStaticPaths() {
  return ARTICLES.flatMap((article) => {
    const image = articleImage(article);
    return image ? [{ params: { slug: article.slug }, props: { image } }] : [];
  });
}

export const GET: APIRoute = ({ props }) =>
  new Response(choroplethPng((props.image as ShareImage).spec()), { headers: { "Content-Type": "image/png" } });
