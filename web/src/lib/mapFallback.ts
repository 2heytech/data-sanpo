// 地図を表示できない環境（WebGL2 が使えないなど）で、地図の代わりに出す案内の中身（設計変更記録 #196）。
// 指標の名前・静止画の地図（指標ページの画像、#190）と地域の名前は、ビルドのときに FALLBACK_URL にまとめ、案内を出すときだけブラウザが読む。
// このファイルはブラウザでも使うので、ファイルを読む処理（lib/data）は入れない（データを作る処理は mapFallbackData.ts）
import { municipalityCodeOf, type MapState } from "./urlstate";

export const FALLBACK_URL = "/map/fallback.json";

export interface FallbackImage {
  /** 画像の URL のパス */
  path: string;
  alt: string;
}

export interface MapFallbackData {
  /** 地図を開いたときの指標（地図の既定と同じ、指標の一覧の先頭） */
  default: string;
  /** 指標の ID → 名前と、全国の地図の画像（画像を作らない指標は image なし） */
  indicators: Record<string, { name: string; image?: FallbackImage }>;
  /** 都道府県コード2桁 → 名前 */
  prefectures: Record<string, string>;
  /** 市区町村の ID → 名前（政令指定都市の区は「札幌市中央区」の形） */
  municipalities: Record<string, string>;
}

export interface FallbackLink {
  href: string;
  text: string;
  note: string;
}

export interface FallbackView {
  /** 先頭に並べるリンク（選んでいた指標のページ、選んでいた地域のページ） */
  links: FallbackLink[];
  /** 静止画の地図（押すとその指標のページ） */
  image: (FallbackImage & { href: string }) | null;
}

const indicatorPage = (id: string) => `/indicators/${id}/`;

/**
 * 地図の URL の状態（指標・選んだ地域）から、案内に出すリンクと静止画の地図を決める。
 * 指標が分からないときは地図の既定の指標。その指標の画像がない（犯罪など、#190）ときは既定の指標の画像にする
 */
export function fallbackView(state: Pick<MapState, "indicator" | "area">, data: MapFallbackData): FallbackView {
  const id = state.indicator && data.indicators[state.indicator] ? state.indicator : data.default;
  const ind = data.indicators[id];
  const links: FallbackLink[] = [];
  if (ind) {
    links.push({ href: indicatorPage(id), text: `「${ind.name}」のランキング`, note: "全国の順位の表と、指標の意味・出典" });
  }
  const area = state.area ? areaLink(state.area, data) : null;
  if (area) links.push(area);
  const imageId = ind?.image ? id : data.default;
  const image = data.indicators[imageId]?.image;
  return { links, image: image ? { ...image, href: indicatorPage(imageId) } : null };
}

/** 選んでいた地域のページ。町丁・字等はページがないので、その市区町村のページにする */
function areaLink(areaId: string, data: MapFallbackData): FallbackLink | null {
  const pref = /^pref-(\d{2})$/.exec(areaId)?.[1];
  if (pref) {
    const name = data.prefectures[pref];
    return name ? { href: `/prefectures/${pref}/`, text: `${name}のデータ`, note: "市区町村の人口ランキングと、主な指標の全国順位" } : null;
  }
  const code = municipalityCodeOf(areaId);
  const muniId = code ? `muni-${code}` : null;
  const name = muniId ? data.municipalities[muniId] : undefined;
  if (!muniId || !name) return null;
  const prefName = data.prefectures[code!.slice(0, 2)] ?? "";
  return {
    href: `/areas/${muniId}/`,
    text: `${prefName}${name}のデータ`,
    note: areaId === muniId ? "データで見た特徴と、主な指標の全国順位" : "選んでいた町丁目がある市区町村のページ",
  };
}
