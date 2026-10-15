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

/** 全国で目立つとみなす順位の範囲（上位・下位それぞれ全体のこの割合まで） */
const NOTABLE_SHARE = 0.05;
/** 目立つ指標として挙げる数（上位・下位それぞれ） */
const NOTABLE_COUNT = 3;

const jp = (n: number) => n.toLocaleString("ja-JP");

/**
 * 地域ページの冒頭に置く文章。表の値と順位から作り、表にない数字（推計など）は足さない。
 * 順位は値の大きい順で、良い・悪いの意味は付けない。
 */
export function areaSummary(name: string, pref: string, stats: SummaryStat[]): string[] {
  const byId = new Map(stats.map((s) => [s.ind.id, s]));
  const lines: string[] = [];

  const pop = byId.get("population_total");
  if (pop?.row?.value != null) {
    const prefRank = pop.ranks[0];
    lines.push(`${name}の人口は${formatValue(pop.row, pop.ind)}（${pop.periodLabel}）` +
      (prefRank && pref ? `で、${pref}の${jp(prefRank.total)}市区町村のうち${prefRank.rank === 1 ? "最も多い" : `${jp(prefRank.rank)}番目に多い`}市区町村です。` : "です。"));
  }
  const change = byId.get("population_change_rate");
  if (change?.row?.value != null) {
    const v = change.row.value;
    lines.push(v === 0 ? `5年前の国勢調査から人口は変わっていません（${change.periodLabel}）。`
      : `5年前の国勢調査から人口が${formatValue({ ...change.row, value: Math.abs(v) }, change.ind).replace(/^\+/, "")}${v > 0 ? "増えました" : "減りました"}（${change.periodLabel}）。`);
  }
  const aged = byId.get("aged_65_plus_share");
  if (aged?.row?.value != null) {
    lines.push(`65歳以上の人の割合は${formatValue(aged.row, aged.ind)}です（${aged.periodLabel}）。`);
  }

  // 全国の市区町村の中で値が特に大きい・小さい指標。人口に比例しやすい件数・人数は除き、割合・密度・増減率だけを見る。
  // 政党別の得票率のように同じ組の指標が並ばないよう、組（family か名前の括弧の前）ごとに1つにする
  const candidates = stats.filter((s) => s.ind.kind !== "count" && !s.ind.legend?.band && s.row?.value != null && s.ranks[1]
    && s.ranks[1].total >= 20);
  const pick = (top: boolean) => {
    const seen = new Set<string>();
    return candidates
      .map((s) => {
        const r = s.ranks[1]!;
        // 下位は順位の位置で近似する（同じ値が多い指標では下位に入らないことがあるが、入る指標を誤ることはない）
        return { s, r, pos: top ? r.rank / r.total : (r.total - r.rank + 1) / r.total };
      })
      .filter((x) => x.pos <= NOTABLE_SHARE)
      .sort((a, b) => a.pos - b.pos)
      .filter(({ s }) => {
        const group = s.ind.family ?? s.ind.name.replace(/（[^（）]*）$/, "");
        if (seen.has(group)) return false;
        seen.add(group);
        return true;
      })
      .slice(0, NOTABLE_COUNT)
      .map(({ s, r }) => `${s.ind.name}は${formatValue(s.row, s.ind)}で、全国の${jp(r.total)}市区町村のうち${jp(r.rank)}位と${top ? "大きい" : "小さい"}方です（${s.periodLabel}）。`);
  };
  // 全国で目立つ指標は1つずつ文にする（この地域の特色として読めるように）
  return [...lines, ...pick(true), ...pick(false)];
}
