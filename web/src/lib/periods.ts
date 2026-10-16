import type { Indicator } from "./types";

/**
 * 市区町村の値を見るときの時点の候補（先に使う方から）。
 * 国勢調査の新しい回（2025年など）が市区町村の値だけで公表されている指標は、町丁目に合わせた既定の時点（2020年）より
 * 新しい回を先に使い、最後に既定の時点を置く（設計変更記録 #118）。
 * 新しい回にその市区町村の値がないとき（2024年に区を再編した浜松市の旧区など）は、呼び出し側で次の候補を使う。
 * 犯罪の年ごとの値など、国勢調査以外の新しい時点には切り替えない（既定の時点は直近5年の合計などのため）。
 * 既定の時点に市区町村の値がない指標（投票率: 最新の衆院選は都道府県の値だけ）は、市区町村の値がある最も新しい時点を最後に置く。
 */
export function municipalityPeriods(ind: Indicator): string[] {
  const newer = ind.periods
    .filter((p) => p.period > ind.default_period && !p.aggregate && p.levels.includes("municipality")
      && p.source_ids.length > 0 && p.source_ids.every((s) => s.startsWith("census")))
    .map((p) => p.period)
    .sort()
    .reverse();
  const levels = ind.periods.find((p) => p.period === ind.default_period)?.levels;
  const fallback = levels && !levels.includes("municipality")
    ? ind.periods.filter((p) => !p.aggregate && p.levels?.includes("municipality")).map((p) => p.period).sort().at(-1)
    : undefined;
  return [...newer, ind.default_period, ...(fallback ? [fallback] : [])];
}
