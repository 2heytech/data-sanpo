// 地域ページの考察と特徴の一言（areaProfile）を、ビルドの間とっておく。
// 地域ページと都道府県ページ（県内の市区町村の一覧に特徴の一言を出す）の両方で使うため、同じ市区町村を2回計算しない。
// 都道府県ページの考察（loadPrefectureProfile）も、読む値をここでまとめる
import { areaProfile, type AreaProfile, type InsightData } from "./areaInsights";
import { loadAreas, loadFacilityPoints, loadIndicators, loadPlace, loadPlacePoints, loadValues } from "./data";
import { prefectureProfile, type PrefInsightData } from "./prefectureInsights";
import type { FacilityPoint } from "./types";

let data: InsightData | null = null;
// 国指定文化財の点（全国。地域ページの考察で名前を挙げる。設計変更記録 #163）。公開版にないときは null
let culture: { label: string; points: FacilityPoint[] } | null = null;
const cache = new Map<string, AreaProfile>();

export function loadAreaProfile(muniId: string): AreaProfile {
  if (!data) {
    const index = loadPlace("cultural_properties");
    const points = index ? loadFacilityPoints("cultural_properties") : [];
    culture = points.length ? { label: index!.periods[0]?.label ?? "", points } : null;
    const byId = new Map(loadIndicators().map((i) => [i.id, i]));
    data = {
      indicator: (id) => byId.get(id),
      indicators: () => [...byId.values()],
      rows: (id, period) => loadValues(id, period ?? byId.get(id)?.default_period ?? "", "municipalities")?.rows ?? [],
      places: () => loadPlacePoints(),
      areas: () => loadAreas(),
      culture: () => culture,
    };
  }
  let p = cache.get(muniId);
  if (!p) {
    p = areaProfile(muniId, data);
    cache.set(muniId, p);
  }
  return p;
}

let prefData: PrefInsightData | null = null;

/** 都道府県ページの考察と特徴の一言（都道府県の値で、全国47都道府県の中の順位を見る。設計変更記録 #140） */
export function loadPrefectureProfile(code: string, name: string): AreaProfile {
  if (!prefData) {
    const byId = new Map(loadIndicators().map((i) => [i.id, i]));
    prefData = {
      indicator: (id) => byId.get(id),
      indicators: () => [...byId.values()],
      rows: (id, period) => loadValues(id, period, "prefectures")?.rows ?? [],
    };
  }
  return prefectureProfile(code, name, prefData);
}
