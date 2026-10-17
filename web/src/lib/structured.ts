// 検索エンジン向けの構造化データ（JSON-LD）。設計変更記録 #130
import type { Indicator, Source } from "./types";

/** パンくず（トップ ＞ 都道府県 ＞ 市区町村 など）。最後の項目（今のページ）は URL を省く */
export function breadcrumbList(site: URL | undefined, items: { name: string; path?: string }[]): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((it, i) => ({
      "@type": "ListItem", position: i + 1, name: it.name,
      ...(it.path && site ? { item: new URL(it.path, site).href } : {}),
    })),
  };
}

/**
 * 指標ページの Dataset（Google のデータセット検索に載せるため）。
 * サイトで公開している加工済みのデータは CC BY 4.0（README）。元データの出典は isBasedOn に並べる。
 * dataUrl は市区町村の値のファイル（公開版ごとに場所が変わるが、ページも公開のたびに作り直す）
 */
export function indicatorDataset(site: URL | undefined, ind: Indicator, path: string, sources: Source[], dataUrl: string | null,
  areaLevels: string[]): Record<string, unknown> {
  const years = ind.periods.map((p) => p.period.slice(0, 4)).sort();
  const abs = (p: string) => (site ? new URL(p, site).href : p);
  // 説明は50字以上が求められるので、意味に計算方法と、どこで見られるかを足す
  const description = `${ind.description}${areaLevels.length ? `全国の${areaLevels.join("・")}ごとの値。` : ""}計算方法: ${ind.method}` +
    `${/[。．]$/.test(ind.method) ? "" : "。"}公的機関の公開データからデータさんぽが作った値で、地図とランキングで見られます。`;
  return {
    "@context": "https://schema.org",
    "@type": "Dataset",
    name: ind.name,
    description: description.slice(0, 5000),
    url: abs(path),
    keywords: [ind.category, ind.name, "市区町村", "オープンデータ"],
    license: "https://creativecommons.org/licenses/by/4.0/",
    isAccessibleForFree: true,
    creator: { "@type": "Organization", name: "データさんぽ", url: abs("/") },
    temporalCoverage: years[0] === years[years.length - 1] ? years[0] : `${years[0]}/${years[years.length - 1]}`,
    spatialCoverage: { "@type": "Place", name: "日本" },
    variableMeasured: ind.unit ? `${ind.name}（${ind.unit}）` : ind.name,
    ...(sources.length ? {
      isBasedOn: sources.map((s) => ({
        "@type": "CreativeWork", name: s.title, ...(s.url ? { url: s.url } : {}),
        ...(s.provider ? { publisher: { "@type": "Organization", name: s.provider } } : {}),
      })),
    } : {}),
    ...(dataUrl ? {
      distribution: [{ "@type": "DataDownload", encodingFormat: "application/json", contentUrl: abs(dataUrl) }],
    } : {}),
  };
}
