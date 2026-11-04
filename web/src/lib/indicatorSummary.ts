// 指標ページの冒頭の「データから分かること」（設計変更記録 #190）。
// ランキングの表を言い換えるだけでなく、上位の顔ぶれの偏り・真ん中のまち・前の時点からの変化といった比べ方を、
// 公開データから数えた事実だけで書く。理由の推測は書かない（地域ページの考察とは違い、数字で言えることに限る）。
// 地域を悪く言うように読める指標（犯罪・交通事故・財政の負担など）は要約を出さず、所得・学歴・寿命などは低い方を書かない
// （プロジェクトの「考察の決まり」）。
import { formatNumber, formatValue } from "./format";
import type { Indicator } from "./types";

/** 要約に使う地域と値（都道府県・市区町村・政令指定都市の市全体） */
export interface SummaryArea {
  id: string;
  /** 文に書く名前（全国の指標では都道府県名から。「東京都世田谷区」） */
  label: string;
  /** 偏りを数えるときの都道府県名 */
  prefecture: string;
  value: number | null;
}

/** 前の時点の値（地域 ID → 値）と、その時点の短い名前（「2020年」「2024年10月の衆院選」） */
export interface PreviousValues {
  label: string;
  values: Map<string, number | null>;
}

export interface SummaryInput {
  ind: Indicator;
  /** ランキングの時点の市区町村の値（値なしを含む） */
  municipalities: SummaryArea[];
  /** 都道府県の値 */
  prefectures: SummaryArea[];
  /** 前の時点の値（市区町村の値があれば市区町村、なければ都道府県） */
  previous?: PreviousValues | null;
  /** 政令指定都市の市全体の値（区の値から計算したもの） */
  cities?: SummaryArea[];
  /** 一部の都道府県だけの指標の範囲（「東京都」）。全国の指標は null */
  coverage?: string | null;
}

/** 要約を出すかどうか。none: 出さない、top: 大きい方だけ書く、both: 小さい方も書く */
export type SummaryPolicy = "none" | "top" | "both";

// 大きい方を書くと地域を悪く言うように読めるので、要約を出さない分類と指標
const NO_SUMMARY_CATEGORIES = new Set(["犯罪", "交通事故", "財政"]);
const NO_SUMMARY_IDS = new Set([
  "school_aid_rate", "household_income_under300_share", "waiting_children",
  "elem_special_class_share", "jhs_special_class_share", "education_unknown_share",
]);
// 小さい方を書くと地域を悪く言うように読める（所得・学歴・寿命など）か、名指しが要らない分類と指標
const TOP_ONLY_CATEGORIES = new Set(["所得・税", "学歴", "教育", "選挙", "外国人住民", "子育て"]);
const TOP_ONLY_IDS = new Set(["life_expectancy_male", "life_expectancy_female"]);

export function summaryPolicy(ind: Indicator): SummaryPolicy {
  if (NO_SUMMARY_CATEGORIES.has(ind.category) || NO_SUMMARY_IDS.has(ind.id) || ind.legend?.band) return "none";
  // 国籍別の外国人の数・割合は国籍で地域を語ることになるので出さない（総数・全体の割合だけ）
  if (ind.category === "外国人住民" && ind.name.includes("（")) return "none";
  if (TOP_ONLY_CATEGORIES.has(ind.category) || TOP_ONLY_IDS.has(ind.id)) return "top";
  return "both";
}

/** 時点の短い名前（文の中で「〜と比べると」の前に置く） */
export function shortPeriodLabel(label: string): string {
  const election = /^(\d{4})年(\d{1,2})月 (衆院選|参院選)/.exec(label);
  if (election) return `${election[1]}年${election[2]}月の${election[3]}`;
  const m = /^(\d{4}(?:〜\d{4})?)年(度)?/.exec(label);
  return m ? `${m[1]}年${m[2] ?? ""}` : label;
}

const MIN_RANKED = 5;
const TOP_GROUP = 20;
const MIN_TOP_SHARE = 6;
const MIN_FOR_MIDDLE = 20;
const MIN_FOR_CHANGE = 20;

type Ranked = SummaryArea & { value: number };

const sortDesc = (areas: SummaryArea[]): Ranked[] =>
  areas.filter((a): a is Ranked => a.value !== null).sort((a, b) => b.value - a.value);

/** 文の中の値（単位を詰める。「954,737人」） */
const valueText = (ind: Indicator, value: number) => formatValue({ value, status: "observed" }, ind, { inText: true });
const named = (ind: Indicator, a: Ranked) => `${a.label}（${valueText(ind, a.value)}）`;

/** 「〜の1位は〇〇（値）で、〇〇（値）、〇〇（値）が続きます」と、同じ値が並ぶときの言い方 */
function topSentence(ind: Indicator, ranked: Ranked[], unitWord: string, lead: string): string {
  const top = ranked[0].value;
  const tied = ranked.filter((a) => a.value === top);
  if (tied.length > 1) {
    const names = tied.slice(0, 3).map((a) => a.label).join("・");
    return `${lead}${ind.name}が最も大きい${valueText(ind, top)}の${unitWord}が${tied.length}あります（${names}${tied.length > 3 ? "など" : ""}）。`;
  }
  const next = ranked.slice(1, 3).map((a) => named(ind, a));
  return `${lead}${ind.name}の1位は${named(ind, ranked[0])}で${next.length ? `、${next.join("、")}が続きます` : "す"}。`;
}

/** 小さい方: 1つなら名前、同じ値が並ぶなら数（0が並ぶときは「値が0の〜がN」） */
function bottomSentence(ind: Indicator, ranked: Ranked[], unitWord: string): string | null {
  const low = ranked[ranked.length - 1].value;
  if (low === ranked[0].value) return null;
  const tied = ranked.filter((a) => a.value === low);
  if (tied.length === 1) return `最も小さいのは${named(ind, tied[0])}です。`;
  if (low === 0) return `値が0の${unitWord}が${tied.length.toLocaleString("ja-JP")}あります。`;
  return `最も小さい${valueText(ind, low)}の${unitWord}が${tied.length.toLocaleString("ja-JP")}あります。`;
}

/** 上位20に同じ都道府県が多いとき（6以上）の文 */
function concentrationSentence(ranked: Ranked[]): string | null {
  if (ranked.length < TOP_GROUP * 5) return null;
  const counts = new Map<string, number>();
  for (const a of ranked.slice(0, TOP_GROUP)) counts.set(a.prefecture, (counts.get(a.prefecture) ?? 0) + 1);
  const [pref, n] = [...counts.entries()].sort((a, b) => b[1] - a[1])[0];
  return n >= MIN_TOP_SHARE ? `上位${TOP_GROUP}のうち${n}が${pref}の市区町村です。` : null;
}

/** 全国の真ん中のまちとの比べ（「中央値」と書かず、真ん中に来るまちと書く。地域ページと同じ言い方） */
function middleSentence(ind: Indicator, ranked: Ranked[], where: string): string | null {
  if (ranked.length < MIN_FOR_MIDDLE || ind.kind === "change") return null;
  const middle = ranked[Math.floor((ranked.length - 1) / 2)].value;
  if (middle <= 0) return null;
  const ratio = ranked[0].value / middle;
  const times = ratio >= 2 ? `で、1位はその約${formatNumber(ratio, ratio < 10 ? 1 : 0)}倍です` : "です";
  return `${where}を値の順に並べると、ちょうど真ん中に来るまちは${valueText(ind, middle)}${times}。`;
}

/** 前の時点からの変化（両方の時点に値のある地域のうち、増えた・減った数） */
function changeSentence(ind: Indicator, ranked: Ranked[], previous: PreviousValues, unitWord: string): string | null {
  if (ind.kind === "change") return null;
  let up = 0, down = 0, both = 0;
  for (const a of ranked) {
    const before = previous.values.get(a.id);
    if (before === null || before === undefined) continue;
    both += 1;
    if (a.value > before) up += 1;
    else if (a.value < before) down += 1;
  }
  if (both < MIN_FOR_CHANGE || up + down === 0) return null;
  // 人数・件数・金額は「増え・減り」、割合などは「上がり・下がり」
  const amount = ind.kind === "count" || /円$/.test(ind.unit) || ind.unit === "人";
  const [upA, upB, downA, downB] = amount ? ["増え", "増えて", "減り", "減って"] : ["上がり", "上がって", "下がり", "下がって"];
  const fmt = (n: number) => n.toLocaleString("ja-JP");
  // 多い方を先に書く。片方しかないときは「〜で増えています」
  const [first, second] = up >= down
    ? [{ n: up, a: upA, b: upB }, { n: down, a: downA, b: downB }]
    : [{ n: down, a: downA, b: downB }, { n: up, a: upA, b: upB }];
  const body = second.n
    ? `${fmt(first.n)}で${first.a}、${fmt(second.n)}で${second.b}います`
    : `${fmt(first.n)}で${first.b}います`;
  return `${previous.label}と比べると、両方の時点に値のある${fmt(both)}${unitWord}のうち${body}。`;
}

/**
 * 指標ページの冒頭に出す文（3〜6文）。出さない指標や、比べるだけの地域がないときは空の配列
 */
export function indicatorSummary(input: SummaryInput): string[] {
  const { ind } = input;
  const policy = summaryPolicy(ind);
  if (policy === "none") return [];
  const munis = sortDesc(input.municipalities);
  const prefs = sortDesc(input.prefectures);
  const lines: string[] = [];
  const scope = input.coverage ? `${input.coverage}の` : "";
  if (munis.length >= MIN_RANKED) {
    lines.push(topSentence(ind, munis, "市区町村", `${scope}市区町村で見ると、`));
    // 政令指定都市は区ごとに並べているので、人数・件数で市全体が1位を上回るときは書き添える
    const city = sortDesc(input.cities ?? [])[0];
    if (city && ind.kind === "count" && city.value > munis[0].value) {
      lines.push(`政令指定都市は区ごとに並べています。市全体で見ると${named(ind, city)}が最も大きくなります。`);
    }
    if (policy === "both") {
      const low = bottomSentence(ind, munis, "市区町村");
      if (low) lines.push(low);
    }
    if (!input.coverage) {
      const c = concentrationSentence(munis);
      if (c) lines.push(c);
    }
    const middle = middleSentence(ind, munis, input.coverage ? `${input.coverage}の市区町村` : "全国の市区町村");
    if (middle) lines.push(middle);
    if (prefs.length >= 10) {
      const next = prefs.slice(1, 3).map((a) => named(ind, a));
      lines.push(`都道府県別の1位は${named(ind, prefs[0])}で${next.length ? `、${next.join("、")}が続きます` : "す"}。`);
    }
    if (input.previous) {
      const ch = changeSentence(ind, munis, input.previous, "市区町村");
      if (ch) lines.push(ch);
    }
  } else if (prefs.length >= MIN_RANKED) {
    lines.push(topSentence(ind, prefs, "都道府県", "都道府県で見ると、"));
    if (policy === "both") {
      const low = bottomSentence(ind, prefs, "都道府県");
      if (low) lines.push(low);
    }
    if (input.previous) {
      const ch = changeSentence(ind, prefs, input.previous, "都道府県");
      if (ch) lines.push(ch);
    }
  }
  return lines;
}
