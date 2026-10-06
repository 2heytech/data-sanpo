// ビルド時（Astro のページ生成）にだけ使うデータ読込。ブラウザでは使わない。
import { readFileSync } from "node:fs";
import { join } from "node:path";
import release from "../generated/release.json";
import type {
  AreasFile, IndicatorCatalog, LegendFile, ReleaseInfo, Source, ValuesFile,
} from "./types";

export const RELEASE = release as ReleaseInfo;
export const DATA_BASE = `/data/${RELEASE.release_id}`;

// 読んだファイルはビルドの間とっておく（市区町村のページ約1,900件がそれぞれ全指標の値を読むため、
// 毎回読み直すとページの生成に数分かかる）。返した値はページ側で書き換えないこと
const cache = new Map<string, unknown>();

function read<T>(rel: string): T {
  if (!cache.has(rel)) {
    cache.set(rel, JSON.parse(readFileSync(join(process.cwd(), "public", DATA_BASE, rel), "utf8")));
  }
  return cache.get(rel) as T;
}

/** 地図の点レイヤーのデータ（駅・学校・地価公示）。公開版にないときは null */
export function loadPlace(name: string): { name: string; unit: string; description: string; periods: { label: string }[] } | null {
  try {
    return read(`places/${name}.json`);
  } catch {
    return null;
  }
}

export const loadIndicators = () => read<IndicatorCatalog>("indicators.json").indicators;
export const loadAreas = () => read<AreasFile>("areas.json");
export const loadSources = () => read<{ sources: Source[] }>("sources.json").sources;

export function loadValues(indicatorId: string, period: string, chunk: string): ValuesFile | null {
  try {
    return read<ValuesFile>(`values/${indicatorId}/${period}/${chunk}.json`);
  } catch {
    return null;
  }
}

export const loadLegend = (indicatorId: string, period: string) =>
  read<LegendFile>(`values/${indicatorId}/${period}/legend.json`);
