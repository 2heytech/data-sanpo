// 地域ページの「人口の移り変わり」（国勢調査の各回の人口・世帯数と、5年前からの増減。設計変更記録 #217）。
// 「〇〇 人口」「〇〇 人口 推移」で探して開いた人に、答えの数字1つだけでなく、移り変わりが分かるようにする
import { loadIndicators, loadValues } from "./data";
import type { JukiPopulation } from "./jukiPopulation";
import type { Indicator, ValueRow } from "./types";

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

// 住民基本台帳の人口と1年間の動き（設計変更記録 #238）。値の行（分子つき）を指標・時点ごとにとっておく
const rowTables = new Map<string, Map<string, ValueRow>>();
function rowOf(indicatorId: string, period: string, entityId: string): ValueRow | null {
  const key = `${indicatorId}/${period}`;
  let t = rowTables.get(key);
  if (!t) {
    t = new Map((loadValues(indicatorId, period, "municipalities")?.rows ?? []).map((r) => [r.entity_id, r]));
    rowTables.set(key, t);
  }
  return t.get(entityId) ?? null;
}

/** 住民基本台帳の人口のいちばん新しい1月1日と、その前の1年間からさかのぼった人口の動き。公開版に人口がないときは null */
export function jukiPopulation(entityId: string): JukiPopulation | null {
  const indicators = new Map(loadIndicators().map((i) => [i.id, i]));
  const stocks = municipalPeriods(indicators.get("juki_population"))
    .flatMap((p) => { const v = valueOf("juki_population", p.period, entityId); return v === null ? [] : [{ p, v }]; });
  const latest = stocks.at(-1);
  if (!latest) return null;
  const latestYear = Number(latest.p.period.slice(0, 4));
  const has = (id: string) => new Set(municipalPeriods(indicators.get(id)).map((p) => p.period));
  const value = (id: string, period: string, periods: Set<string>) => periods.has(period) ? valueOf(id, period, entityId) : null;
  const households = has("juki_households");
  const births = has("juki_births"), deaths = has("juki_deaths"), natural = has("juki_natural_change"), social = has("juki_social_change");
  const movedIn = has("in_migration_rate"), movedOut = has("out_migration_rate");
  const stockOf = new Map(stocks.map((s) => [s.p.period, s.v]));
  // 転入・転出の人数は、転入率・転出率の分子（人数の指標そのものは公開していない。#202）
  const numerator = (id: string, period: string, periods: Set<string>) => periods.has(period) ? rowOf(id, period, entityId)?.numerator ?? null : null;
  // いちばん新しい1月1日より後の1年は入れない（区を再編した浜松市の旧区は、2023年1月1日の人口までで、その後の1年を書かない）
  const flowPeriods = municipalPeriods(indicators.get("juki_natural_change") ?? indicators.get("juki_births"))
    .filter((p) => Number(p.period.slice(0, 4)) < latestYear);
  const years = flowPeriods.map((p) => ({
    year: /^\d{4}年/.exec(p.label)?.[0] ?? p.label,
    births: value("juki_births", p.period, births),
    deaths: value("juki_deaths", p.period, deaths),
    natural: value("juki_natural_change", p.period, natural),
    social: value("juki_social_change", p.period, social),
    movedIn: numerator("in_migration_rate", p.period, movedIn),
    movedOut: numerator("out_migration_rate", p.period, movedOut),
    populationAfter: stockOf.get(`${Number(p.period.slice(0, 4)) + 1}-01-01`) ?? null,
  })).filter((y) => y.births !== null || y.natural !== null || y.social !== null).reverse();
  const before = stockOf.get(`${latestYear - 1}-01-01`);
  return {
    label: latest.p.label, population: latest.v,
    households: value("juki_households", latest.p.period, households),
    change: before === undefined ? null : latest.v - before,
    // 表と文は、いちばん新しい1月1日に終わる1年から
    years,
  };
}
