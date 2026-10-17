// 都道府県ページと寄り道に置く色分け地図の画像（設計変更記録 #142）。
// 画像を作る処理（pages/images/）と、画像を置くページの両方から使う。画像に出る文字は scripts/image-font.mjs がこのファイルから集める。
import type { Article } from "./articles";
import { loadAreas, loadBoundaries, loadIndicators, loadLegend, loadSources, loadValues } from "./data";
import { compactNumber, formatNumber } from "./format";
import type { ChoroplethSpec, MapFeature } from "./mapImage";
import { municipalityPeriods } from "./periods";
import type { Indicator, Prefecture } from "./types";

export interface ShareImage {
  /** 画像の URL のパス */
  path: string;
  alt: string;
  /** 地図でその指標・時点を開く URL */
  mapHref: string;
  /** 画像の中身（境界を読むので、画像を作るときだけ呼ぶ） */
  spec: () => ChoroplethSpec;
}

/** 市区町村の値があるいちばん新しい時点（国勢調査の新しい回を先に。#118） */
function latestMunicipalPeriod(ind: Indicator) {
  for (const period of municipalityPeriods(ind)) {
    const rows = loadValues(ind.id, period, "municipalities")?.rows;
    const legend = loadLegend(ind.id, period)?.levels.municipality;
    const p = ind.periods.find((x) => x.period === period);
    if (p && rows?.some((r) => r.value !== null) && legend) return { period: p, rows, legend };
  }
  return null;
}

const municipalityFeatures = (prefCodes: string[]): MapFeature[] =>
  prefCodes.flatMap((code) => (loadBoundaries(`municipalities/${code}`)?.features ?? [])
    .map((f) => ({ id: f.properties.id, geometry: f.geometry })));

/** 出典の提供者（同じ名前は1つに） */
function providersOf(ind: Indicator, period: string): string[] {
  const ids = ind.periods.find((p) => p.period === period)?.source_ids ?? [];
  const sources = new Map(loadSources().map((s) => [s.source_id, s]));
  return [...new Set(ids.map((id) => sources.get(id)?.provider).filter((p): p is string => !!p))];
}

/** 増減率の区切り（増加に「+」を付ける） */
const signedPercent = (v: number) => `${v > 0 ? "+" : ""}${formatNumber(v, Number.isInteger(v) ? 0 : 1).replace("-", "−")}%`;

/** 都道府県ページの画像: 市区町村別の人口増加率（直近の国勢調査）。区切りは地図と同じく都道府県ごと */
export function prefectureImage(pref: Prefecture): ShareImage | null {
  const ind = loadIndicators().find((i) => i.id === "population_change_rate");
  const latest = ind && latestMunicipalPeriod(ind);
  if (!ind || !latest) return null;
  const munis = loadAreas().municipalities.filter((m) => m.prefecture === pref.code);
  const values = new Map(latest.rows.filter((r) => munis.some((m) => m.id === r.entity_id)).map((r) => [r.entity_id, r.value]));
  if (![...values.values()].some((v) => v !== null)) return null;
  const year = Number(latest.period.period.slice(0, 4));
  const label = `${year - 5}→${year}年`;
  return {
    path: `/images/prefectures/${pref.code}-population-change.png`,
    alt: `${pref.name}の市区町村別の人口増加率（${year - 5}年→${year}年、国勢調査）を色分けした地図`,
    mapHref: `/map/?i=${ind.id}&p=${latest.period.period}&a=pref-${pref.code}`,
    spec: () => {
      const vs = [...values.values()];
      const inc = vs.filter((v) => v !== null && v > 0).length;
      const dec = vs.filter((v) => v !== null && v < 0).length;
      return {
        title: `${pref.name}の市区町村別：人口増加率（${label}）`,
        subtitle: "国勢調査による、5年前と比べた人口の増減",
        facts: [`人口が増えた市区町村：${inc}`, `人口が減った市区町村：${dec}`],
        features: municipalityFeatures([pref.code]),
        frameGeometries: (loadBoundaries("prefectures")?.features ?? [])
          .filter((f) => f.properties.id === `pref-${pref.code}`).map((f) => f.geometry),
        values,
        breaks: latest.legend.by_prefecture?.[pref.code] ?? latest.legend.breaks,
        scheme: loadLegend(ind.id, latest.period.period)!.scheme,
        formatBreak: signedPercent,
        source: "出典：総務省統計局「国勢調査」「境界データ」をもとにデータさんぽが作成（data-sanpo.com）",
        frame: "fit",
      };
    },
  };
}

/** 寄り道の画像: 記事の主な指標の、全国の市区町村別の地図（区切りは全国で1つ） */
export function articleImage(article: Article): ShareImage | null {
  const id = article.mapIndicator ?? article.indicators[0];
  const ind = id ? loadIndicators().find((i) => i.id === id) : undefined;
  const latest = ind && latestMunicipalPeriod(ind);
  if (!ind || !latest) return null;
  const legend = loadLegend(ind.id, latest.period.period)!;
  const change = ind.kind === "change";
  const unit = ind.unit === "%" ? "" : ind.unit;
  const what = `全国の市区町村別の${ind.name}（${latest.period.label}）`;
  return {
    path: `/images/articles/${article.slug}.png`,
    alt: `${what}を色分けした地図`,
    mapHref: `/map/?i=${ind.id}&p=${latest.period.period}`,
    spec: () => ({
      title: article.title,
      subtitle: what,
      features: municipalityFeatures(loadAreas().prefectures.map((p) => p.code)),
      values: new Map(latest.rows.map((r) => [r.entity_id, r.value])),
      breaks: latest.legend.breaks,
      scheme: legend.scheme,
      zeroBlank: legend.zero_blank,
      formatBreak: change ? signedPercent
        : (v) => `${compactNumber(v, Number.isInteger(v) ? 0 : ind.digits)}${ind.unit === "%" ? "%" : ""}`,
      unitLabel: unit ? `単位：${unit}` : undefined,
      // 地図の境界は総務省統計局（国勢調査の境界データ）
      source: `出典：${[...new Set([...providersOf(ind, latest.period.period), "総務省統計局"])].join("・")}の公開データ（統計・境界）をもとにデータさんぽが作成（data-sanpo.com）`,
      frame: "japan",
    }),
  };
}
