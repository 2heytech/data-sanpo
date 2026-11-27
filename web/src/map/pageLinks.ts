// 地図の右の欄から、選んだ地域の市区町村・都道府県のページと、指標のランキングのページへのリンク（設計変更記録 #218）。
// 地域名の「›」や欄の下の文字のリンクだけでは、ページがあることに気づきにくいので、値と順位のすぐ下に、
// 何が見られるかを添えたボタンの形で並べる
import { esc } from "../lib/html";
import { ICON_INDICATOR, ICON_MUNICIPALITY, ICON_PREFECTURE } from "../lib/navIcons";
import { isDesignatedWard } from "../lib/designatedCities";
import { affiliateLink, rakutenFurusatoSearchUrl } from "../lib/rakutenUrl";
import type { Municipality } from "../lib/types";

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

// 選んだ地域の返礼品を楽天ふるさと納税で探すリンク（広告、設計変更記録 #257）。くわしく見るページの下に1つだけ置く。
// 地図の上には重ねず、右の欄（スマホでは下のパネルの「地域の情報」）の中だけに出す。アフィリエイトID がなければ出さない
const ICON_GIFT = '<rect x="3.5" y="8" width="17" height="4" rx="1"/><path d="M5 12v8.5h14V12M12 8v12.5"/>'
  + '<path d="M12 8C11 5.5 9.5 4 8 4.5S7 8 12 8zM12 8c1-2.5 2.5-4 4-3.5S17 8 12 8z"/>';
const ICON_OUT = '<svg class="icon df-out" viewBox="0 0 16 16" aria-hidden="true">'
  + '<path d="M9.5 2.5h4v4M13.5 2.5 7.5 8.5M12 9.5v3.5a.5.5 0 0 1-.5.5h-8a.5.5 0 0 1-.5-.5v-8a.5.5 0 0 1 .5-.5H7"/></svg>';

export interface FurusatoLink {
  href: string;
  /** 「都城市のふるさと納税の返礼品」 */
  title: string;
}

/**
 * 選んだ市区町村（町丁・字等ならその市区町村）の返礼品を探すリンク。市区町村を選んでいなければ都道府県の中を探す。
 * 政令指定都市の区は区ごとの寄附先がないので、市の返礼品を探す（地域ページの欄と同じ。#189）
 */
export function furusatoLink(affiliateId: string, o: {
  prefName: string;
  municipality: Pick<Municipality, "name" | "region"> | null;
}): FurusatoLink | null {
  if (!o.prefName) return null;
  const m = o.municipality;
  const target = m ? (isDesignatedWard(m) ? m.region! : m.name) : "";
  const href = affiliateLink(affiliateId, rakutenFurusatoSearchUrl(o.prefName, target));
  return href ? { href, title: `${target || o.prefName}のふるさと納税の返礼品` } : null;
}

/** GA の furusato_click の link_text は、選んだ地域の名前を入れない固定の言葉にする（#255 の「選んだ地域はイベントに入れない」） */
export function furusatoLinkHtml(link: FurusatoLink): string {
  return `<a class="detail-furusato" href="${esc(link.href)}" target="_blank" rel="sponsored noopener" data-furusato-kind="map" data-track-text="地図の地域の情報">`
    + `<svg class="icon df-icon" viewBox="0 0 24 24" aria-hidden="true">${ICON_GIFT}</svg>`
    + `<span><strong>${esc(link.title)}</strong><small><span class="ad-mark">広告</span>楽天ふるさと納税で探す（別のタブ）</small></span>`
    + `${ICON_OUT}</a>`;
}
