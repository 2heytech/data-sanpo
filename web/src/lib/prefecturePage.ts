// 都道府県ページ（/prefectures/<コード>/）の文と表を作る処理（設計変更記録 #130）。
// 県内の市区町村へのリンクの入口として、人口の順と、主な指標の県内の上位を並べる
import { descriptionFact, fitDescription, popRank } from "./areaSummary";
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
 * 都道府県ページ「データで見る〇〇県」の概要の文。人口と全国の順位、5年前からの増減、市区町村の数。
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
  lines.push(`${name}には${muniCount.toLocaleString("ja-JP")}の市区町村があります${wards}。`);
  return lines;
}

/**
 * 都道府県ページの説明文（検索結果に出る文）。特徴の一言と、いちばん目立つ考察の数字から始め、都道府県ごとに違う文にする。
 * 地域ページの areaDescription と同じく120字前後に収め、締め（開くと何が分かるか）は収まる長さのものを付ける（設計変更記録 #144）
 */
export function prefectureDescription(a: { name: string; title: string | null; insights: string[]; muniCount: number; top3: string; statCount: number }): string {
  const head = a.title ? `${a.name}をデータで見ると「${a.title}」。` : `${a.name}のデータ。`;
  // 「都内」「道内」「府内」「県内」
  const inside = `${a.name.slice(-1)}内`;
  const munis = `${inside}${a.muniCount.toLocaleString("ja-JP")}市区町村`;
  return fitDescription(head + descriptionFact(a.insights), [
    ...(a.top3 ? [`${munis}（${a.top3}など）の人口ランキングと、${a.statCount}の指標の全国順位が分かります。`] : []),
    `${munis}の人口ランキングと、${a.statCount}の指標の全国順位が分かります。`,
    `${a.statCount}の指標の全国順位が分かります。`,
  ]);
}

/**
 * 海をへだてて向かい合い、橋・トンネル・航路で結ばれている都道府県の組。境界は接していないが、隣の都道府県として比べる
 * （北海道と沖縄県には境界の接する都道府県がないため。山口県と福岡県、兵庫県と徳島県も行き来が多い）
 */
export const SEA_NEIGHBORS: [string, string][] = [["01", "02"], ["28", "36"], ["35", "40"], ["46", "47"]];

/**
 * 隣の都道府県。市区町村の隣（境界が接する市区町村）のうち、ほかの都道府県のものから求める。
 * 海をへだてた組（SEA_NEIGHBORS）は sea を付けて加える。都道府県コードの順
 */
export function prefectureNeighbors(munis: Municipality[]): Map<string, { code: string; sea: boolean }[]> {
  const prefOf = new Map(munis.map((m) => [m.id, m.prefecture]));
  const land = new Map<string, Set<string>>();
  const add = (a: string, b: string) => land.set(a, (land.get(a) ?? new Set()).add(b));
  for (const m of munis) {
    for (const n of m.neighbors) {
      const p = prefOf.get(n);
      if (p && p !== m.prefecture) add(m.prefecture, p);
    }
  }
  const codes = new Set(munis.map((m) => m.prefecture));
  const out = new Map<string, { code: string; sea: boolean }[]>();
  for (const code of codes) {
    const list = [...(land.get(code) ?? [])].map((c) => ({ code: c, sea: false }));
    for (const [a, b] of SEA_NEIGHBORS) {
      const other = a === code ? b : b === code ? a : null;
      if (other && codes.has(other) && !list.some((x) => x.code === other)) list.push({ code: other, sea: true });
    }
    out.set(code, list.sort((x, y) => x.code.localeCompare(y.code)));
  }
  return out;
}

/** 政令指定都市の区（札幌市中央区など）を区ごとに数えている市の名前（区部の東京23区は市区町村そのものなので含めない） */
export function wardCitiesOf(munis: Municipality[]): string[] {
  return [...new Set(munis.filter((m) => m.region?.endsWith("市") && m.name.startsWith(m.region) && m.name.endsWith("区"))
    .map((m) => m.region!))];
}
