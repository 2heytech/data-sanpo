import { fitDescription } from "./areaSummary";
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

const rankingPeriod = (ind: Indicator) => ind.periods.find((p) => p.period === ind.default_period);

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
 * 答え（1位の地域名）は書かない（犯罪など、地域を悪く言うように読める指標もあるため）
 */
function hook(scope: IndicatorPageScope): string {
  const allPrefs = scope.nationwide && !scope.partial;
  if (scope.muniCount > 0) return `${allPrefs ? "全国" : ""}1位の市区町村はどこ？ `;
  return `${scope.nationwide ? "全国" : ""}1位の都道府県はどこ？ `;
}

/** 指標の説明は、検索結果で途中で切れないよう、120字に収まるときだけ後ろに付ける（#144） */
const withExplanation = (text: string, ind: Indicator) => fitDescription(text, [ind.description]);

export function indicatorPageText(ind: Indicator, scope: IndicatorPageScope): { title: string; description: string } {
  const allPrefs = scope.nationwide && !scope.partial;
  const year = rankingYear(ind);
  const party = voteShareParty(ind);
  if (party) {
    const when = year ? `（${year}・比例代表）` : "（比例代表）";
    const title = scope.muniCount > 0
      ? `${party.short}の得票率 ${scope.hasPrefRows ? "都道府県別・" : ""}市区町村別ランキング${when}`
      : `${party.short}の得票率 都道府県別${when}`;
    const where = scope.hasMuniValues
      ? `${scope.hasPrefRows ? "都道府県別と" : ""}${allPrefs ? "全国の" : ""}市区町村別のランキング`
      : "都道府県別の値";
    const elections = electionNames(ind);
    // 問いかけに略称、続く文に正式名を書く（同じなら繰り返さない）
    const description = withExplanation(`${party.short}の得票率が${hook(scope)}`
      + `${party.short !== party.full ? party.full + "の" : ""}比例代表の得票率を、`
      + `${where}で紹介${elections ? `（${elections}）` : ""}。意味・計算方法・出典つき。`, ind);
    return { title, description };
  }
  // 「〇〇 都道府県別」「〇〇 市区町村 ランキング 2025」のように探されるので、都道府県別の表があればそう書き、
  // ランキングの時点の年を添える。都道府県の値だけの指標は「〇〇 都道府県別ランキング（年）」（#144）、どちらもなければ名前だけ
  let title = ind.name;
  if (scope.muniCount > 0 && scope.hasPrefRows) {
    title = `${ind.name} 都道府県別・市区町村別ランキング${year ? `（${year}）` : ""}`;
  } else if (scope.muniCount > 0) {
    const notes = [allPrefs ? "全国" : null, year].filter((x) => !!x);
    title = `${ind.name}の市区町村ランキング${notes.length ? `（${notes.join("・")}）` : ""}`;
  } else if (scope.hasPrefRows) {
    title = `${ind.name} 都道府県別ランキング${year ? `（${year}）` : ""}`;
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
  return { title, description };
}
