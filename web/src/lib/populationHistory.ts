// 地域ページの「人口の移り変わり」（国勢調査の各回の人口・世帯数と、5年前からの増減。設計変更記録 #217）。
// 「〇〇 人口」「〇〇 人口 推移」で探して開いた人に、答えの数字1つだけでなく、移り変わりが分かるようにする
import { loadIndicators, loadValues } from "./data";
import type { Indicator } from "./types";

export interface PopulationYear {
  /** 時点の見出し（「2025年10月1日現在」） */
  label: string;
  /** 「2025年」 */
  year: string;
  population: number;
  households: number | null;
  /** 前の回（5年前）からの人口の増加率（%）。最も古い回などは null */
  change: number | null;
}

// 指標・時点ごとの市区町村の値（地域 ID → 値）。約1,900ページが同じファイルを引くので、ビルドの間とっておく
const tables = new Map<string, Map<string, number | null>>();
function valueOf(indicatorId: string, period: string, entityId: string): number | null {
  const key = `${indicatorId}/${period}`;
  let t = tables.get(key);
  if (!t) {
    t = new Map((loadValues(indicatorId, period, "municipalities")?.rows ?? []).map((r) => [r.entity_id, r.value]));
    tables.set(key, t);
  }
  return t.get(entityId) ?? null;
}

const municipalPeriods = (ind: Indicator | undefined) =>
  (ind?.periods ?? []).filter((p) => !p.aggregate && p.levels.includes("municipality"))
    .sort((a, b) => a.period.localeCompare(b.period));

/** 増加率の指標（表の値の書き方に使う）。公開版にないときは null */
export const populationChangeIndicator = () => loadIndicators().find((i) => i.id === "population_change_rate") ?? null;

/** 古い回から順に、人口のある回だけ（区を再編した浜松市の旧区は2025年がない） */
export function populationHistory(entityId: string): PopulationYear[] {
  const indicators = loadIndicators();
  const pop = indicators.find((i) => i.id === "population_total");
  const households = indicators.find((i) => i.id === "households_total");
  const change = populationChangeIndicator();
  const householdPeriods = new Set(municipalPeriods(households).map((p) => p.period));
  const changePeriods = new Set(municipalPeriods(change ?? undefined).map((p) => p.period));
  return municipalPeriods(pop).flatMap((p) => {
    const population = valueOf("population_total", p.period, entityId);
    if (population === null) return [];
    return [{
      label: p.label,
      year: /^\d{4}年/.exec(p.label)?.[0] ?? p.label,
      population,
      households: householdPeriods.has(p.period) ? valueOf("households_total", p.period, entityId) : null,
      change: changePeriods.has(p.period) ? valueOf("population_change_rate", p.period, entityId) : null,
    }];
  });
}
