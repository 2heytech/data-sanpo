// 都道府県ページ（/prefectures/<コード>/）の文と表を作る処理（設計変更記録 #130）。
// 県内の市区町村へのリンクの入口として、人口の順と、主な指標の県内の上位を並べる
import { popRank } from "./areaSummary";
import { formatNumber, formatValue, ranked } from "./format";
import { municipalityPeriods } from "./periods";
import type { Indicator, Municipality, Period, ValueRow } from "./types";

/**
 * 県内の上位を並べる指標。順位は値の大きい順で、良い・悪いの意味は付けない。
 * 下位（所得の低い方など）は、地域を悪く言うように読めるので並べない（設計変更記録 #113 の考察と同じ方針）
 */
export const PREF_RANKING_IDS = [
  "population_change_rate", "children_0_14_share", "total_fertility_rate", "taxable_income_per_taxpayer",
  "daytime_night_ratio", "population_density", "area", "foreign_residents_share",
];
/** 県内の上位をいくつ並べるか */
export const PREF_TOP = 5;

export interface PrefRankItem { muni: Municipality; text: string; rank: number }
export interface PrefRanking { ind: Indicator; period: Period; items: PrefRankItem[]; prefText: string | null }

type Rows = (id: string, period: string, chunk: "municipalities" | "prefectures") => ValueRow[];

/**
 * 指標の県内の上位。市区町村の値がある最も新しい時点（国勢調査は2025年、#118）で数え、値のない市区町村は除く（0 にしない）。
 * 県内で値のある市区町村が上位の数より少ないとき、値がすべて同じときは出さない
 */
export function prefRanking(ind: Indicator, prefCode: string, munis: Municipality[], rows: Rows): PrefRanking | null {
  const byId = new Map(munis.map((m) => [m.id, m]));
  for (const p of municipalityPeriods(ind)) {
    const period = ind.periods.find((x) => x.period === p);
    if (!period) continue;
    const inPref = rows(ind.id, p, "municipalities").filter((r) => byId.has(r.entity_id) && r.value !== null);
    if (inPref.length < PREF_TOP || new Set(inPref.map((r) => r.value)).size < 2) continue;
    const items = ranked(inPref).filter((r) => r.rank <= PREF_TOP)
      .map((r) => ({ muni: byId.get(r.entity_id)!, text: formatValue(r, ind), rank: r.rank }));
    const pref = period.levels.includes("prefecture")
      ? rows(ind.id, p, "prefectures").find((r) => r.entity_id === `pref-${prefCode}`) : undefined;
    return { ind, period, items, prefText: pref && pref.value !== null ? formatValue(pref, ind) : null };
  }
  return null;
}

export interface PrefPopulation { text: string; label: string; rank: number; total: number }

/**
 * 都道府県ページの冒頭の文。人口と全国の順位、5年前からの増減、市区町村の数。
 * 増減は事実だけ書き、減っていることを課題として書き立てない。
 * wardCities は区ごとに分けて数えている政令指定都市（札幌市など）
 */
export function prefectureLead(name: string, pop: PrefPopulation | null, change: { value: number; label: string } | null,
  muniCount: number, wardCities: string[]): string[] {
  const lines: string[] = [];
  if (pop) {
    const rank = popRank(pop);
    let line = `${name}の人口は${pop.text}（${pop.label}）で、全国${pop.total}都道府県のうち${rank}都道府県です。`;
    if (change) {
      const amount = formatNumber(Math.abs(change.value), 1);
      line += amount === "0.0" ? "5年前からほとんど変わっていません。"
        : change.value > 0 ? `5年前と比べて${amount}%増えています。` : `5年前と比べて${amount}%減っています。`;
    }
    lines.push(line);
  }
  const wards = wardCities.length ? `（${wardCities.join("・")}は区ごとに数えています）` : "";
  lines.push(`${name}には${muniCount.toLocaleString("ja-JP")}の市区町村があります${wards}。` +
    "下の表では、それぞれの人口と、データから見た特徴の一言を並べています。市区町村名から、くわしいデータと順位のページを開けます。");
  return lines;
}

/** 政令指定都市の区（札幌市中央区など）を区ごとに数えている市の名前（区部の東京23区は市区町村そのものなので含めない） */
export function wardCitiesOf(munis: Municipality[]): string[] {
  return [...new Set(munis.filter((m) => m.region?.endsWith("市") && m.name.startsWith(m.region) && m.name.endsWith("区"))
    .map((m) => m.region!))];
}
