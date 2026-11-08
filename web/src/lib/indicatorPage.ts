import { DESCRIPTION_MAX, fitDescription } from "./areaSummary";
import type { DescriptionLeaders, Leader } from "./indicatorSummary";
import { latestPeriod } from "./periods";
import type { Indicator } from "./types";

// 指標ページの題名と説明文（検索結果に出る文）。設計変更記録 #142
export interface IndicatorPageScope {
  /** 値のある市区町村の数（ランキングに並ぶ数） */
  muniCount: number;
  /** 市区町村の値の行があるか（値なしの行を含む） */
  hasMuniValues: boolean;
  /** 都道府県別の値の表を出すか */
  hasPrefRows: boolean;
  /** 全国の公開版か */
  nationwide: boolean;
  /** 一部の都道府県だけの指標か */
  partial: boolean;
  /** 値のある都道府県の数（説明文の「47都道府県と1,896市区町村の全順位」） */
  prefCount?: number;
  /** 一部の都道府県だけの指標の範囲（「東京都」）。説明文の「東京都の市区町村で〜」 */
  coverageLabel?: string | null;
}

export interface IndicatorPageText {
  title: string;
  description: string;
  /**
   * ページの見出し（h1）。main（指標名）を大きく、sub（「都道府県別・市区町村別ランキング（2020年）」）を小さく、同じ h1 に入れる。
   * Google は長い題名を h1 に差し替えるので、h1 にも「ランキング」と時点を入れておく（#216）
   */
  heading: { main: string; sub: string | null };
}

// 比例代表の得票率は「政党名 得票率」で探されるので、題名を政党名から始める。
// 正式名に略称が含まれない政党だけ、よく使われる略称を題名に使う（日本共産党は「共産党」を含むので不要）
const VOTE_SHARE_NAME = /^比例代表の得票率（(.+)）$/;
const PARTY_SHORT_NAMES: Record<string, string> = { 自由民主党: "自民党", 社会民主党: "社民党" };

function voteShareParty(ind: Indicator): { full: string; short: string } | null {
  const m = VOTE_SHARE_NAME.exec(ind.name);
  if (!m) return null;
  return { full: m[1], short: PARTY_SHORT_NAMES[m[1]] ?? m[1] };
}

// 題名・説明文の時点は、都道府県・市区町村のランキングの時点（新しい国勢調査の回があればそれ。#191）
const rankingPeriod = (ind: Indicator) => ind.periods.find((p) => p.period === latestPeriod(ind));

/**
 * 題名に入れる、ランキングの時点の年（「2020年」「2023年度」「2019〜2023年」「2026年衆院選」）。
 * 年で始まらない時点（「現存植生図…」）や、公開の年度（データの年ではない）は入れない
 */
export function rankingYear(ind: Indicator): string | null {
  const label = rankingPeriod(ind)?.label ?? "";
  if (label.includes("公開")) return null;
  const election = /^(\d{4})年\d{1,2}月 (衆院選|参院選)/.exec(label);
  if (election) return `${election[1]}年${election[2]}`;
  const m = /^(\d{4}(?:〜\d{4})?)年(度)?/.exec(label);
  return m ? `${m[1]}年${m[2] ?? ""}` : null;
}

/** 選挙の名前を時点の順に並べる（例: 「2024年10月 衆院選・2026年2月 衆院選」） */
function electionNames(ind: Indicator): string {
  return ind.periods
    .filter((p) => !p.aggregate)
    .map((p) => p.label.replace(/（比例）$/, ""))
    .join("・");
}

/**
 * 説明文の書き出し（「全国1位の市区町村はどこ？ 」）。検索結果で、開いて確かめたくなるように問いかけで始める（設計変更記録 #144）。
 * 1位の地域名を書かない指標（犯罪など、地域を悪く言うように読める指標。#216）と、1位が並ぶ指標に使う
 */
function hook(scope: IndicatorPageScope): string {
  const allPrefs = scope.nationwide && !scope.partial;
  if (scope.muniCount > 0) return `${allPrefs ? "全国" : ""}1位の市区町村はどこ？ `;
  return `${scope.nationwide ? "全国" : ""}1位の都道府県はどこ？ `;
}

/** 指標の説明は、検索結果で途中で切れないよう、120字に収まるときだけ後ろに付ける（#144） */
const withExplanation = (text: string, ind: Indicator) => fitDescription(text, [ind.description]);

/** 指標名・政党名の後ろに付ける「都道府県別・市区町村別ランキング（2020年）」と、題名でのつなぎ方 */
function rankingSub(ind: Indicator, scope: IndicatorPageScope, party: boolean): { sub: string | null; join: string } {
  const allPrefs = scope.nationwide && !scope.partial;
  const year = rankingYear(ind);
  if (party) {
    const when = year ? `（${year}・比例代表）` : "（比例代表）";
    return scope.muniCount > 0
      ? { sub: `${scope.hasPrefRows ? "都道府県別・" : ""}市区町村別ランキング${when}`, join: " " }
      : { sub: `都道府県別${when}`, join: " " };
  }
  // 「〇〇 都道府県別」「〇〇 市区町村 ランキング 2025」のように探されるので、都道府県別の表があればそう書き、
  // ランキングの時点の年を添える。都道府県の値だけの指標は「〇〇 都道府県別ランキング（年）」（#144）、どちらもなければ名前だけ
  if (scope.muniCount > 0 && scope.hasPrefRows) return { sub: `都道府県別・市区町村別ランキング${year ? `（${year}）` : ""}`, join: " " };
  if (scope.muniCount > 0) {
    const notes = [allPrefs ? "全国" : null, year].filter((x) => !!x);
    return { sub: `市区町村ランキング${notes.length ? `（${notes.join("・")}）` : ""}`, join: "の" };
  }
  if (scope.hasPrefRows) return { sub: `都道府県別ランキング${year ? `（${year}）` : ""}`, join: " " };
  return { sub: null, join: "" };
}

const followed = (l: Leader, withNext: boolean) =>
  `${l.top}${withNext && l.next.length ? `で、${l.next.join("・")}が続きます` : "です"}。`;

/**
 * 説明文を、都道府県と市区町村の1位から始める（#216。#144 の「1位の地域名は書かない」を、ページ冒頭の要約の決まり #190 に置き換えた）。
 * 「平均標高の都道府県1位は長野県（1,131.4m）で、山梨県・群馬県が続きます。市区町村の1位は長野県川上村（1,624.6m）。」に、
 * 開くと何があるか（全順位・色分け地図・出典）を、120字に収まる長さで続ける。どれも収まらなければ null（今までの問いかけの文にする）
 */
function leadersDescription(ind: Indicator, subject: string, scope: IndicatorPageScope, leaders: DescriptionLeaders,
  party: boolean): string | null {
  const { prefecture: p, municipality: m } = leaders;
  const prefPart = (withNext: boolean) => (p ? `${subject}の都道府県1位は${followed(p, withNext)}` : "");
  const muniAlone = (withNext: boolean) => {
    if (!m) return "";
    return scope.coverageLabel
      ? `${scope.coverageLabel}の市区町村で${subject}の1位は${followed(m, withNext)}`
      : `${subject}の市区町村1位は${followed(m, withNext)}`;
  };
  const muniAfter = m ? `市区町村の1位は${m.top}。` : "";
  const bodies = [
    ...(p ? [prefPart(true) + muniAfter, prefPart(false) + muniAfter, prefPart(true), prefPart(false)] : []),
    muniAlone(true), muniAlone(false),
  ].filter((b) => b.length > 0);
  const year = rankingYear(ind);
  const when = year ? `（${year}${party ? "・比例代表" : ""}）` : party ? "（比例代表）" : "";
  const prefCount = scope.hasPrefRows && scope.prefCount ? `${scope.prefCount}都道府県` : null;
  const muniCount = scope.muniCount > 0
    ? `${scope.coverageLabel ? `${scope.coverageLabel}の` : ""}${scope.muniCount.toLocaleString("ja-JP")}市区町村` : null;
  const counts = [prefCount, muniCount].filter((x) => !!x).join("と");
  const tails = [
    ...(counts ? [`${counts}の全順位を、色分け地図と出典つきで紹介${when}。`, `${counts}の全順位を色分け地図で紹介${when}。`] : []),
    `全順位を色分け地図で紹介${when}。`,
    `全順位を地図で紹介${party ? "（比例代表）" : ""}。`,
  ];
  const shortest = Math.min(...tails.map((t) => t.length));
  const body = bodies.find((b) => b.length + shortest <= DESCRIPTION_MAX);
  return body ? fitDescription(body, tails) : null;
}

export function indicatorPageText(ind: Indicator, scope: IndicatorPageScope, leaders?: DescriptionLeaders | null): IndicatorPageText {
  const allPrefs = scope.nationwide && !scope.partial;
  const party = voteShareParty(ind);
  const main = party ? `${party.short}の得票率` : ind.name;
  const { sub, join } = rankingSub(ind, scope, !!party);
  const title = sub ? `${main}${join}${sub}` : main;
  const heading = { main, sub };
  const fromLeaders = leaders ? leadersDescription(ind, main, scope, leaders, !!party) : null;
  if (fromLeaders) return { title, description: fromLeaders, heading };
  if (party) {
    const where = scope.hasMuniValues
      ? `${scope.hasPrefRows ? "都道府県別と" : ""}${allPrefs ? "全国の" : ""}市区町村別のランキング`
      : "都道府県別の値";
    const elections = electionNames(ind);
    // 問いかけに略称、続く文に正式名を書く（同じなら繰り返さない）
    const description = withExplanation(`${party.short}の得票率が${hook(scope)}`
      + `${party.short !== party.full ? party.full + "の" : ""}比例代表の得票率を、`
      + `${where}で紹介${elections ? `（${elections}）` : ""}。意味・計算方法・出典つき。`, ind);
    return { title, description, heading };
  }
  const where = scope.hasMuniValues
    ? `${allPrefs ? "全国の" : ""}市区町村ランキング${scope.hasPrefRows ? "と都道府県別の値" : ""}`
    : "都道府県別の値";
  // 名前が「（住民100人当たり）」のように括弧で終わる指標が多いので、単位は名前の後ろでなく時点の括弧に入れ、
  // 時点の中の括弧（「2025年度（4月実施）」）は「・」にして、括弧が重ならないようにする（#144）
  const label = rankingPeriod(ind)?.label.replace(/（([^（）]+)）/g, "・$1");
  const notes = [label, ind.unit ? `単位: ${ind.unit}` : null].filter((x) => !!x);
  const paren = notes.length ? `（${notes.join("、")}）` : "";
  const description = withExplanation(scope.muniCount > 0 || scope.hasPrefRows
    ? `${ind.name}が${hook(scope)}${scope.hasMuniValues ? where : "都道府県別のランキング"}${paren}を、意味・計算方法・出典つきで紹介。`
    : `${ind.name}の${where}${paren}。意味・計算方法・出典つき。`, ind);
  return { title, description, heading };
}
