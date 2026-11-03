// 都道府県ページと寄り道に置く色分け地図の画像（設計変更記録 #142）。
// 画像を作る処理（pages/images/）と、画像を置くページの両方から使う。画像に出る文字は scripts/image-font.mjs がこのファイルから集める。
import type { Article } from "./articles";
import { loadAreas, loadBoundaries, loadIndicators, loadLegend, loadSources, loadValues } from "./data";
import { compactNumber, formatNumber } from "./format";
import type { ChoroplethSpec, MapFeature } from "./mapImage";
import { municipalityPeriods, prefecturePeriods } from "./periods";
import type { Indicator, Prefecture } from "./types";
import { mapHref } from "./urlstate";

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

/** 都道府県の値があるいちばん新しい時点（市区町村の値がない指標の寄り道の画像に使う。#185） */
function latestPrefecturePeriod(ind: Indicator) {
  for (const period of [...prefecturePeriods(ind)].sort().reverse()) {
    const rows = loadValues(ind.id, period, "prefectures")?.rows;
    const legend = loadLegend(ind.id, period)?.levels.prefecture;
    const p = ind.periods.find((x) => x.period === period);
    if (p && rows?.some((r) => r.value !== null) && legend) return { period: p, rows, legend };
  }
  return null;
}

const municipalityFeatures = (prefCodes: string[]): MapFeature[] =>
  prefCodes.flatMap((code) => (loadBoundaries(`municipalities/${code}`)?.features ?? [])
    .map((f) => ({ id: f.properties.id, geometry: f.geometry })));

/** 出典の提供者（同じ名前は1つに。「総務省統計局・経済産業省」のような連名は分けて数え、境界の「総務省統計局」と重ねない） */
function providersOf(ind: Indicator, period: string): string[] {
  const ids = ind.periods.find((p) => p.period === period)?.source_ids ?? [];
  const sources = new Map(loadSources().map((s) => [s.source_id, s]));
  return [...new Set(ids.flatMap((id) => sources.get(id)?.provider?.split("・") ?? []).filter((p) => !!p))];
}

/** 増減率の区切り（増加に「+」を付ける） */
const signedPercent = (v: number) => `${v > 0 ? "+" : ""}${formatNumber(v, Number.isInteger(v) ? 0 : 1).replace("-", "−")}%`;

/** 都道府県ページの画像: 市区町村別の人口増加率（直近の国勢調査）。区切りは地図と同じく全国で共通（#145） */
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
    mapHref: mapHref({ indicator: ind.id, period: latest.period.period, area: `pref-${pref.code}`, level: "municipality" }),
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
        breaks: latest.legend.breaks,
        scheme: loadLegend(ind.id, latest.period.period)!.scheme,
        formatBreak: signedPercent,
        source: "出典：総務省統計局「国勢調査」「境界データ」をもとにデータさんぽが作成（data-sanpo.com）",
        frame: "fit",
      };
    },
  };
}

/**
 * 寄り道の画像: 記事の主な指標の、全国の市区町村別の地図（区切りは全国で1つ）。
 * 1つの都道府県だけの指標（東京都の街路樹など）は、全国の図では小さすぎるので、その都道府県の形に合わせた図にする（#168）。
 * 都道府県の値しかない指標（外国人宿泊者の割合など）は、全国の都道府県別の地図にする（#185）
 */
export function articleImage(article: Article): ShareImage | null {
  const id = article.mapIndicator ?? article.indicators[0];
  const ind = id ? loadIndicators().find((i) => i.id === id) : undefined;
  if (!ind) return null;
  const muni = latestMunicipalPeriod(ind);
  const latest = muni ?? latestPrefecturePeriod(ind);
  if (!latest) return null;
  const byPref = !muni;
  const legend = loadLegend(ind.id, latest.period.period)!;
  const change = ind.kind === "change";
  const unit = ind.unit === "%" ? "" : ind.unit;
  const prefs = loadAreas().prefectures;
  const only = !byPref && ind.prefectures?.length === 1 ? prefs.find((p) => p.code === ind.prefectures![0]) : undefined;
  const what = `${only ? only.name : "全国"}の${byPref ? "都道府県" : "市区町村"}別の${ind.name}（${latest.period.label}）`;
  return {
    path: `/images/articles/${article.slug}.png`,
    alt: `${what}を色分けした地図`,
    // 地図も画像と同じ単位の色分けで開く（縮尺に任せると都道府県別になるため。#146）
    mapHref: mapHref({ indicator: ind.id, period: latest.period.period, level: byPref ? "prefecture" : "municipality", ...(only ? { area: `pref-${only.code}` } : {}) }),
    spec: () => ({
      title: article.title,
      subtitle: what,
      features: byPref
        ? (loadBoundaries("prefectures")?.features ?? []).map((f) => ({ id: f.properties.id, geometry: f.geometry }))
        : municipalityFeatures(only ? [only.code] : prefs.map((p) => p.code)),
      ...(only ? {
        frameGeometries: (loadBoundaries("prefectures")?.features ?? [])
          .filter((f) => f.properties.id === `pref-${only.code}`).map((f) => f.geometry),
      } : {}),
      values: new Map(latest.rows.map((r) => [r.entity_id, r.value])),
      breaks: latest.legend.breaks,
      scheme: legend.scheme,
      zeroBlank: legend.zero_blank,
      formatBreak: change ? signedPercent
        : (v) => `${compactNumber(v, Number.isInteger(v) ? 0 : ind.digits)}${ind.unit === "%" ? "%" : ""}`,
      unitLabel: unit ? `単位：${unit}` : undefined,
      // 地図の境界は総務省統計局（国勢調査の境界データ）
      source: `出典：${[...new Set([...providersOf(ind, latest.period.period), "総務省統計局"])].join("・")}の公開データ（統計・境界）をもとにデータさんぽが作成（data-sanpo.com）`,
      frame: only ? "fit" : "japan",
    }),
  };
}
