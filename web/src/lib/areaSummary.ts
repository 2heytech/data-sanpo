import { formatValue } from "./format";
import type { Indicator, ValueRow } from "./types";

/** 地域ページのあらまし（表の数字から作る短い文章）に使う、指標ごとの値と順位 */
export interface SummaryStat {
  ind: Indicator;
  periodLabel: string;
  row: ValueRow | undefined;
  /** [都道府県内の順位, 全国の順位]。順位がないときは null */
  ranks: [{ rank: number; total: number } | null, { rank: number; total: number } | null];
}

const jp = (n: number) => n.toLocaleString("ja-JP");

/**
 * 地域ページの冒頭に置く文章。表の値と順位から作り、表にない数字（推計など）は足さない。
 * 順位は値の大きい順で、良い・悪いの意味は付けない。
 * excluded は、人口の値がなく都道府県内の順位に入らない同じ都道府県の市区町村（2025年の浜松市の旧区など）。
 * あるときは「（浜松市の区を除く）」「値のある」と書き、都道府県のすべての市区町村の中の順位と読まれないようにする。
 */
export function areaSummary(name: string, pref: string, stats: SummaryStat[], excluded: { region: string | null }[] = []): string[] {
  const byId = new Map(stats.map((s) => [s.ind.id, s]));
  const lines: string[] = [];

  const pop = byId.get("population_total");
  if (pop?.row?.value != null) {
    const prefRank = pop.ranks[0];
    // 除いた市区町村がすべて1つの市の区なら、その市の名前を書く
    const cities = new Set(excluded.map((m) => m.region));
    const city = cities.size === 1 ? [...cities][0] : null;
    const scope = !excluded.length ? `${jp(prefRank?.total ?? 0)}市区町村`
      : city?.endsWith("市") ? `${jp(prefRank?.total ?? 0)}市区町村（${city}の区を除く）` : `値のある${jp(prefRank?.total ?? 0)}市区町村`;
    lines.push(`${name}の人口は${formatValue(pop.row, pop.ind)}（${pop.periodLabel}）` +
      (prefRank && pref ? `で、${pref}の${scope}のうち${prefRank.rank === 1 ? "最も多い" : `${jp(prefRank.rank)}番目に多い`}市区町村です。` : "です。"));
  }
  // 人口の増減・年齢構成・全国順位で目立つ指標は「データから考えられること」（areaInsights）で考察と一緒に書く
  return lines;
}
