// 地図の右の欄から、選んだ地域の市区町村・都道府県のページと、指標のランキングのページへのリンク（設計変更記録 #218）。
// 地域名の「›」や欄の下の文字のリンクだけでは、ページがあることに気づきにくいので、値と順位のすぐ下に、
// 何が見られるかを添えたボタンの形で並べる
import { esc } from "../lib/html";
import { ICON_INDICATOR, ICON_MUNICIPALITY, ICON_PREFECTURE } from "../lib/navIcons";

export interface PageLink {
  href: string;
  kind: "municipality" | "prefecture" | "indicator";
  title: string;
  note: string;
}

const ICONS: Record<PageLink["kind"], string> = {
  municipality: ICON_MUNICIPALITY, prefecture: ICON_PREFECTURE, indicator: ICON_INDICATOR,
};
const ICON_NEXT = '<svg class="icon dp-next" viewBox="0 0 16 16" aria-hidden="true"><path d="m6 3.5 4.5 4.5L6 12.5"/></svg>';

/**
 * 選んだ地域（町丁・字等ならその市区町村）・都道府県のページと、指標のページ。近い地域から順に並べる。
 * 都道府県だけの指標でも、選んだ市区町村のページは出す（地域のページには市区町村の値の指標がある）
 */
export function detailPageLinks(o: {
  municipality: { id: string; name: string } | null;
  prefecture: { code: string; name: string } | null;
  indicator: { id: string; name: string };
  prefectureOnly: boolean;
}): PageLink[] {
  return [
    ...(o.municipality ? [{
      href: `/areas/${o.municipality.id}/`, kind: "municipality" as const, title: `${o.municipality.name}のページ`,
      note: "人口の移り変わりと、指標の全国順位",
    }] : []),
    ...(o.prefecture ? [{
      href: `/prefectures/${o.prefecture.code}/`, kind: "prefecture" as const, title: `${o.prefecture.name}のページ`,
      note: "特徴と、市区町村の人口ランキング",
    }] : []),
    {
      href: `/indicators/${o.indicator.id}/`, kind: "indicator", title: `${o.indicator.name}のランキング`,
      note: `${o.prefectureOnly ? "都道府県別" : "全国"}の順位と、意味・計算方法・出典`,
    },
  ];
}

export function pageLinksHtml(links: PageLink[], label = "くわしく見るページ"): string {
  return `<nav class="detail-pages" aria-label="${esc(label)}">${links.map((l) => `<a href="${esc(l.href)}">`
    + `<svg class="icon dp-icon" viewBox="0 0 24 24" aria-hidden="true">${ICONS[l.kind]}</svg>`
    + `<span><strong>${esc(l.title)}</strong><small>${esc(l.note)}</small></span>${ICON_NEXT}</a>`).join("")}</nav>`;
}
