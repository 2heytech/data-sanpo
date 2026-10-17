// 地域ページ・都道府県ページの「主な指標」と「となりと比べる」の表で使う、指標の並べ方（設計変更記録 #140）
import { genresFor } from "./genres";
import type { Indicator, Period, ValueRow } from "./types";

export interface StatRank { rank: number; total: number }

/** 1つの指標の値・順位と、比べる地域の値（比べる地域の並びと同じ順） */
export interface StatItem {
  ind: Indicator;
  period: Period;
  row: ValueRow | undefined;
  /** 順位の列（地域ページは都道府県内と全国、都道府県ページは全国）。順位を出さないときは null */
  ranks: (StatRank | null)[];
  neighborRows: (ValueRow | undefined)[];
}

export interface StatGroup { id: string; title: string; categories: { name: string; stats: StatItem[] }[] }

/** 値のある指標だけを、ジャンル・カテゴリごとにまとめる（データなしの行は出さない） */
export function statGroups(items: StatItem[]): StatGroup[] {
  const shown = items.filter((s) => s.row?.value != null);
  return genresFor(shown.map((s) => s.ind.category)).map((g, i) => ({
    id: `g${i + 1}`, title: g.title,
    categories: g.categories.map((c) => ({ name: c, stats: shown.filter((s) => s.ind.category === c) })),
  }));
}

export const rankText = (r: StatRank) => `${r.rank.toLocaleString("ja-JP")}位／${r.total.toLocaleString("ja-JP")}`;
/** 順位のバーの印の位置（左が1位） */
export const markLeft = (r: StatRank) => (r.total > 1 ? ((r.rank - 1) / (r.total - 1)) * 100 : 50);
