// 都道府県ごとの市区町村ランキングのページ（/prefectures/<コード>/<指標>/。設計変更記録 #237）。
// 「兵庫県 高齢化率 市町村」「北海道で一番広い市町村」のように、都道府県名と指標で探す人の受け皿にする。
// 全国のランキング（指標のページ）では、その県の市区町村が上位・下位の100位の外に畳まれて見つけにくい。
// 指標は、順位の上下で地域を良い・悪いと読ませない中立のものに絞る（所得・犯罪・財政・学力は入れない。地域ページの考察と同じ方針）
import { fitDescription } from "./areaSummary";
import { formatValue, ranked } from "./format";
import { municipalityPeriods } from "./periods";
import type { Indicator, Municipality, Period, ValueRow } from "./types";

export interface PrefIndicatorPage {
  id: string;
  /** 題名・見出しで指標名の前に置く、よく探される呼び名（「高齢化率」）。指標名は括弧で添える */
  alias?: string;
  /** いちばん小さい市区町村を文に書く指標の言い方（「いちばん狭い」）。面積・標高など、小さい側も探される指標だけ。
   * 人口の減り方・地価・産業の額の小さい側は書かない */
  lowest?: string;
}

/** ページを作る指標（10指標 × 47都道府県） */
export const PREF_INDICATOR_PAGES: PrefIndicatorPage[] = [
  { id: "area", lowest: "いちばん狭い" },
  { id: "population_density", lowest: "いちばん低い" },
  { id: "population_change_rate" },
  { id: "aged_65_plus_share", alias: "高齢化率", lowest: "いちばん低い" },
  { id: "children_0_14_share", alias: "年少人口割合", lowest: "いちばん低い" },
  { id: "elevation_mean", lowest: "いちばん低い" },
  { id: "daytime_night_ratio" },
  { id: "land_price_residential" },
  { id: "agri_output" },
  { id: "manufacturing_shipments" },
];

/** 県内で値のある市区町村がこれより少ない、または値がすべて同じ指標はページを作らない */
export const PREF_INDICATOR_MIN = 5;
/** 「全国の上位100位に入る市区町村」の数え方の100 */
export const NATIONAL_TOP = 100;

export const prefIndicatorPath = (prefCode: string, indicatorId: string) => `/prefectures/${prefCode}/${indicatorId}/`;

/** 題名・見出しの指標名（「高齢化率（65歳以上の割合）」「面積」） */
export function prefIndicatorName(ind: Indicator, page: PrefIndicatorPage | undefined): string {
  return page?.alias ? `${page.alias}（${ind.name}）` : ind.name;
}

export interface PrefRankRow extends ValueRow {
  muni: Municipality;
  /** 県内の順位（値のない市区町村は null） */
  rank: number | null;
  /** 全国の市区町村の中の順位 */
  national: { rank: number; total: number } | null;
}

export interface PrefIndicatorRanking {
  period: Period;
  /** 値のある市区町村（県内の順位の順） */
  rows: PrefRankRow[];
  /** 値のない市区町村（区を再編した浜松市の旧区・地価の地点がない町村など） */
  missing: PrefRankRow[];
  /** 都道府県全体の値（都道府県の値がない指標・時点は null） */
  prefRow: ValueRow | null;
  /** 都道府県全体の値の全国の順位（すべて同じ値なら null） */
  prefRank: { rank: number; total: number } | null;
}

type Rows = (id: string, period: string, chunk: "municipalities" | "prefectures") => ValueRow[];

/**
 * 県内の市区町村の順位。市区町村の値がある最も新しい時点（国勢調査は2025年、#118）で数え、
 * 県内で値のある市区町村が PREF_INDICATOR_MIN より少ないとき・値がすべて同じときは次の候補の時点を見る（どれもなければ null）。
 * 値のない市区町村は順位に入れず、最後に並べる（0 にしない）
 */
export function prefIndicatorRanking(ind: Indicator, prefCode: string, munis: Municipality[], rows: Rows): PrefIndicatorRanking | null {
  const byId = new Map(munis.map((m) => [m.id, m]));
  for (const p of municipalityPeriods(ind)) {
    const period = ind.periods.find((x) => x.period === p);
    if (!period) continue;
    const all = rows(ind.id, p, "municipalities");
    const inPref = all.filter((r) => byId.has(r.entity_id));
    const valued = inPref.filter((r) => r.value !== null);
    if (valued.length < PREF_INDICATOR_MIN || new Set(valued.map((r) => r.value)).size < 2) continue;
    const nationRanked = ranked(all);
    const nationRank = new Map(nationRanked.map((r) => [r.entity_id, r.rank]));
    const nationTotal = nationRanked.length;
    const rankedRows: PrefRankRow[] = ranked(valued).map((r) => ({
      ...r, muni: byId.get(r.entity_id)!, national: { rank: nationRank.get(r.entity_id)!, total: nationTotal },
    }));
    // 県内の市区町村で、この時点の行がない・値がない市区町村
    const seen = new Set(valued.map((r) => r.entity_id));
    const missing: PrefRankRow[] = munis.filter((m) => !seen.has(m.id)).map((m) => {
      const r = inPref.find((x) => x.entity_id === m.id);
      return { entity_id: m.id, value: null, status: r?.status ?? "missing", muni: m, rank: null, national: null };
    });
    const prefRows = period.levels.includes("prefecture") ? rows(ind.id, p, "prefectures") : [];
    const prefRow = prefRows.find((r) => r.entity_id === `pref-${prefCode}`) ?? null;
    const prefValued = prefRows.filter((r) => r.value !== null);
    const prefRank = prefRow && prefRow.value !== null && new Set(prefValued.map((r) => r.value)).size > 1
      ? { rank: prefValued.filter((r) => (r.value as number) > (prefRow.value as number)).length + 1, total: prefValued.length }
      : null;
    return { period, rows: rankedRows, missing, prefRow, prefRank };
  }
  return null;
}

// ページがあるかどうか（都道府県 × 指標）。約470ページが互いにリンクし、都道府県・指標のページからもリンクするので、ビルドの間とっておく
const available = new Map<string, boolean>();

/**
 * その都道府県・指標のページがあるか。全国の公開版（都道府県が2つ以上）で、PREF_INDICATOR_PAGES の指標のうち
 * 県内の順位が作れるもの（prefIndicatorRanking が null でない）だけ作る
 */
export function hasPrefIndicatorPage(ind: Indicator, prefCode: string, munis: Municipality[], rows: Rows, prefectureCount: number): boolean {
  if (prefectureCount < 2 || !PREF_INDICATOR_PAGES.some((p) => p.id === ind.id)) return false;
  const key = `${prefCode}/${ind.id}`;
  let has = available.get(key);
  if (has === undefined) {
    has = prefIndicatorRanking(ind, prefCode, munis, rows) !== null;
    available.set(key, has);
  }
  return has;
}

/** 順位ごとにまとめた名前（同じ値は同じ順位。名前は3つまで） */
function rankGroups(rows: PrefRankRow[], ind: Indicator, upTo: number) {
  const groups: { rank: number; names: string[]; text: string }[] = [];
  for (const r of rows) {
    if (r.rank === null || r.rank > upTo) break;
    const last = groups.at(-1);
    if (last && last.rank === r.rank) last.names.push(r.muni.name);
    else groups.push({ rank: r.rank, names: [r.muni.name], text: formatValue(r, ind, { inText: true }) });
  }
  return groups;
}
const names = (list: string[], max = 3) => list.slice(0, max).join("・") + (list.length > max ? "など" : "");

/** 「1位は佐用町（46.7%）、2位は上郡町（44.0%）、3位は香美町（43.5%）」。同じ値の市区町村は同じ順位にまとめる */
export function topPhrase(rows: PrefRankRow[], ind: Indicator): string {
  return rankGroups(rows, ind, 3).map((g) => `${g.rank}位は${names(g.names)}（${g.text}）`).join("、");
}

export interface PrefIndicatorTextInput {
  pref: string;
  ind: Indicator;
  page: PrefIndicatorPage | undefined;
  ranking: PrefIndicatorRanking;
  /** 政令指定都市の市全体の値（「神戸市は557.0km²」の文。区から計算できない指標は空） */
  cities: { name: string; text: string | null }[];
}

/**
 * 冒頭の「データから分かること」。表と同じ公開データから数えた事実だけを書き、理由の推測は書かない。
 * 小さい側は lowest のある指標だけ書く
 */
export function prefIndicatorFacts(a: PrefIndicatorTextInput): string[] {
  const { pref, ind, page, ranking } = a;
  const count = ranking.rows.length;
  const lines = [`${pref}の${count.toLocaleString("ja-JP")}市区町村のうち、${topPhrase(ranking.rows, ind)}です。`];
  if (page?.lowest && count > 3) {
    const bottom = ranking.rows.filter((r) => r.rank === ranking.rows.at(-1)!.rank);
    lines.push(`${page.lowest}のは${names(bottom.map((r) => r.muni.name))}で、${formatValue(bottom[0], ind, { inText: true })}です。`);
  }
  if (ranking.prefRow && ranking.prefRow.value !== null) {
    const rank = ranking.prefRank ? `で、全国${ranking.prefRank.total}都道府県のうち${ranking.prefRank.rank}位` : "";
    lines.push(`${pref}全体では${formatValue(ranking.prefRow, ind, { inText: true })}${rank}です。`);
  }
  const top = ranking.rows.filter((r) => r.national && r.national.rank <= NATIONAL_TOP);
  const total = ranking.rows[0]?.national?.total;
  if (top.length && total && total > NATIONAL_TOP * 2) {
    lines.push(`全国${total.toLocaleString("ja-JP")}市区町村の中で上位${NATIONAL_TOP}位に入るのは、` +
      `${names(top.map((r) => r.muni.name))}の${top.length}市区町村です。`);
  }
  for (const c of a.cities) {
    lines.push(`政令指定都市の${c.name}は、区ごとに並べています${c.text ? `（${c.name}全体では${c.text}）` : ""}。`);
  }
  return lines;
}

/** 題名（「兵庫県の高齢化率（65歳以上の割合） 市区町村ランキング（2025年）」） */
export function prefIndicatorTitle(pref: string, ind: Indicator, page: PrefIndicatorPage | undefined, year: string | null): string {
  return `${pref}の${prefIndicatorName(ind, page)} 市区町村ランキング${year ? `（${year}）` : ""}`;
}

/** 説明文（検索結果に出る文）。県内の1〜3位の名前と値から始め、県ごと・指標ごとに違う文にする（120字前後） */
export function prefIndicatorDescription(a: PrefIndicatorTextInput & { year: string | null }): string {
  const { pref, ind, page, ranking } = a;
  const name = prefIndicatorName(ind, page);
  const groups = rankGroups(ranking.rows, ind, 3);
  const first = groups[0];
  const rest = groups.slice(1).map((g) => `${g.rank}位は${names(g.names, 2)}`).join("、");
  const head = `${pref}の${name}の市区町村ランキング${a.year ? `（${a.year}）` : ""}。` +
    `1位は${names(first.names, 2)}（${first.text}）${rest ? `、${rest}` : ""}。`;
  const count = `${pref.slice(-1)}内${ranking.rows.length.toLocaleString("ja-JP")}市区町村`;
  const prefText = ranking.prefRow && ranking.prefRow.value !== null && ranking.prefRank
    ? `、${pref}全体の値（全国${ranking.prefRank.rank}位）` : "";
  return fitDescription(head, [
    `${count}の全順位と全国の中の順位${prefText}を紹介。`,
    `${count}の全順位と全国の中の順位を紹介。`,
    `${count}の全順位を紹介。`,
  ]);
}
