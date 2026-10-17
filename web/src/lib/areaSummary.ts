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

/** 人口の順位の言い方。半分より下は「少ない方から」で数える（「188のうち154番目に多い」より読みやすいため） */
export function popRank(r: { rank: number; total: number }): string {
  if (r.rank === 1) return "最も多い";
  if (r.rank === r.total) return "最も少ない";
  return r.rank * 2 <= r.total + 1 ? `${jp(r.rank)}番目に多い` : `少ない方から${jp(r.total - r.rank + 1)}番目の`;
}

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
      (prefRank && pref ? `で、${pref}の${scope}のうち${popRank(prefRank)}市区町村です。` : "です。"));
  }
  // 人口の増減・年齢構成・全国順位で目立つ指標は「データから考えられること」（areaInsights）で考察と一緒に書く
  return lines;
}

/**
 * 地域ページの説明文（検索結果に出る文）。特徴の一言と、いちばん目立つ考察から始め、まちごとに違う文にする（設計変更記録 #130）。
 * 考察が長いときは最初の文（数字と順位）だけを使う
 */
export function areaDescription(a: {
  name: string; place: string; pref: string; title: string | null; firstInsight?: string;
  population: string | null; statCount: number;
}): string {
  const head = a.title ? `${a.name}（${a.place}）をデータで見ると「${a.title}」。` : `${a.name}（${a.place}）のデータ。`;
  const s = a.firstInsight ?? "";
  const insight = s.length <= 110 ? s : s.slice(0, s.indexOf("。") + 1);
  return head + insight + (a.population ? `人口は${a.population}。` : "") +
    `${a.pref ? `${a.pref}内・` : ""}全国の順位など${a.statCount}の指標を、となりの市区町村との比較と出典つきで紹介。`;
}
