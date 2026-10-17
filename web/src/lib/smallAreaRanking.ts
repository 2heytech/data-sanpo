// 地域ページの「町丁目別ランキング」。国勢調査の町丁・字等ごとの値から、市区町村の中の上位を表にする（設計変更記録 #142）。
// 地域を悪く言うように読めないよう、人口・人口の増加・子どもの割合のような中立か良い方の指標だけにし、下位は出さない。
import { ranked } from "./format";
import type { Indicator, Period, ValueRow } from "./types";

export interface SmallAreaTableSpec {
  id: string;
  title: string;
  /** 0 より大きい値だけを並べる（人口が増えた町丁目） */
  positiveOnly?: boolean;
}

export const SMALL_AREA_TABLES: SmallAreaTableSpec[] = [
  { id: "population_total", title: "人口が多い町丁目" },
  { id: "population_change_rate", title: "人口が増えた町丁目（5年間の増加率）", positiveOnly: true },
  { id: "children_0_14_share", title: "15歳未満の割合が高い町丁目" },
];

/** 値のある町丁目がこれより少ない市区町村では、その表を出さない（並べても市区町村の中の比較にならないため） */
export const MIN_SMALL_AREAS = 8;

/** 町丁目の値がある、いちばん新しい時点（複数年の合計は除く） */
export function latestSmallAreaPeriod(ind: Indicator): Period | null {
  const ps = ind.periods.filter((p) => p.levels.includes("small_area") && !p.aggregate);
  return ps.length ? ps.reduce((a, b) => (b.period > a.period ? b : a)) : null;
}

/**
 * 市区町村の中の上位。値のある町丁目が20以上なら10位まで、それより少なければ5位まで（同じ値は同じ順位で並べる）。
 * positiveOnly のときは0より大きい町丁目だけで、3つ未満なら出さない
 */
export function topSmallAreas(rows: ValueRow[], positiveOnly = false): (ValueRow & { rank: number })[] {
  const withValue = rows.filter((r) => r.value !== null);
  if (withValue.length < MIN_SMALL_AREAS) return [];
  const usable = positiveOnly ? withValue.filter((r) => (r.value as number) > 0) : withValue;
  if (positiveOnly && usable.length < 3) return [];
  const size = withValue.length >= 20 ? 10 : 5;
  return ranked(usable).filter((r) => r.rank <= size);
}
