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

/** 選挙の名前を時点の順に並べる（例: 「2024年10月 衆院選・2026年2月 衆院選」） */
function electionNames(ind: Indicator): string {
  return ind.periods
    .filter((p) => !p.aggregate)
    .map((p) => p.label.replace(/（比例）$/, ""))
    .join("・");
}

export function indicatorPageText(ind: Indicator, scope: IndicatorPageScope): { title: string; description: string } {
  const allPrefs = scope.nationwide && !scope.partial;
  const party = voteShareParty(ind);
  if (party) {
    const title = scope.muniCount > 0
      ? `${party.short}の得票率 ${scope.hasPrefRows ? "都道府県別・" : ""}市区町村別ランキング（比例代表）`
      : `${party.short}の得票率 都道府県別（比例代表）`;
    const where = scope.hasMuniValues
      ? `${scope.hasPrefRows ? "都道府県別と" : ""}${allPrefs ? "全国の" : ""}市区町村別のランキング`
      : "都道府県別の値";
    const elections = electionNames(ind);
    const description = `${party.full}${party.short !== party.full ? `（${party.short}）` : ""}の比例代表の得票率を、`
      + `${where}で紹介${elections ? `（${elections}）` : ""}。意味・計算方法・出典つき。${ind.description}`;
    return { title, description };
  }
  // 検索で「〇〇 ランキング」と探す人に届くよう、市区町村の値がある指標は題名にランキングと入れる
  const title = scope.muniCount > 0 ? `${ind.name}の市区町村ランキング${allPrefs ? "（全国）" : ""}` : ind.name;
  const where = scope.hasMuniValues
    ? `${allPrefs ? "全国の" : ""}市区町村ランキング${scope.hasPrefRows ? "と都道府県別の値" : ""}`
    : "都道府県別の値";
  const description = `${ind.name}${ind.unit ? `（${ind.unit}）` : ""}の${where}。意味・計算方法・出典つき。${ind.description}`;
  return { title, description };
}
