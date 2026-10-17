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

const jp = (n: number) => n.toLocaleString("ja-JP");

/** 人口の順位の言い方。半分より下は「少ない方から」で数える（「188のうち154番目に多い」より読みやすいため） */
export function popRank(r: { rank: number; total: number }): string {
  if (r.rank === 1) return "最も多い";
  if (r.rank === r.total) return "最も少ない";
  return r.rank * 2 <= r.total + 1 ? `${jp(r.rank)}番目に多い` : `少ない方から${jp(r.total - r.rank + 1)}番目の`;
}

/**
 * 地域ページの冒頭に置く文章。表の値と順位から作り、表にない数字（推計など）は足さない。
 * 順位は値の大きい順で、良い・悪いの意味は付けない。
 * excluded は、人口の値がなく都道府県内の順位に入らない同じ都道府県の市区町村（2025年の浜松市の旧区など）。
 * あるときは「（浜松市の区を除く）」「値のある」と書き、都道府県のすべての市区町村の中の順位と読まれないようにする。
 */
export function areaSummary(name: string, pref: string, stats: SummaryStat[], excluded: { region: string | null }[] = []): string[] {
  const byId = new Map(stats.map((s) => [s.ind.id, s]));
  const lines: string[] = [];

  const pop = byId.get("population_total");
  if (pop?.row?.value != null) {
    const prefRank = pop.ranks[0];
    // 除いた市区町村がすべて1つの市の区なら、その市の名前を書く
    const cities = new Set(excluded.map((m) => m.region));
    const city = cities.size === 1 ? [...cities][0] : null;
    const scope = !excluded.length ? `${jp(prefRank?.total ?? 0)}市区町村`
      : city?.endsWith("市") ? `${jp(prefRank?.total ?? 0)}市区町村（${city}の区を除く）` : `値のある${jp(prefRank?.total ?? 0)}市区町村`;
    lines.push(`${name}の人口は${formatValue(pop.row, pop.ind, { inText: true })}（${pop.periodLabel}）` +
      (prefRank && pref ? `で、${pref}の${scope}のうち${popRank(prefRank)}市区町村です。` : "です。"));
  }
  // 人口の増減・年齢構成・全国順位で目立つ指標は「データから考えられること」（areaInsights）で考察と一緒に書く
  return lines;
}

/** 説明文の長さの目安。検索結果に出るのはおおむね120字までなので、締めの文は収まるときだけ付ける（寄り道の説明文と同じ。設計変更記録 #144） */
export const DESCRIPTION_MAX = 120;
/** 説明文の最初の事実に使わない、同じ値の数（件数0の市区町村が並ぶときなど、そのまちの特徴とは言いにくいため） */
const DESCRIPTION_MAX_SAME = 10;

/** 考察が「〇市区町村が同じ値」の順位で、同じ値が多すぎるか */
const manySame = (s: string) => {
  const m = /、([\d,]+)(?:市区町村|都道府県)が同じ値/.exec(s);
  return !!m && Number(m[1].replace(/,/g, "")) >= DESCRIPTION_MAX_SAME;
};

/**
 * 説明文に使う考察を選び、最初の文（数字と順位）だけを短くして返す。
 * 「全国1,887市区町村のうち5位」→「全国5位」、「2020年10月1日現在」→「2020年」（本文の考察は変えない）
 */
export function descriptionFact(insights: string[]): string {
  const s = insights.find((x) => !manySame(x)) ?? "";
  const i = s.indexOf("。");
  return (i < 0 ? s : s.slice(0, i + 1))
    .replace(/全国[\d,]+(?:市区町村|都道府県)のうち/g, "全国")
    .replace(/全国[\d,]+(?:市区町村|都道府県)の中で/g, "全国で")
    .replace(/(\d{4}年)\d{1,2}月\d{1,2}日現在/g, "$1");
}

/** 時点の見出しの年（「2025年10月1日現在」→「2025年」） */
export const periodYear = (label: string) => /^\d{4}年(?:度)?/.exec(label)?.[0] ?? label;

/**
 * 地域ページの説明文（検索結果に出る文）。特徴の一言と、いちばん目立つ考察の数字から始め、まちごとに違う文にする（設計変更記録 #130・#144）。
 * 「特徴の一言＋数字の1文＋（注記）＋人口＋締め」で、120字前後に収める。締めは収まるときだけ付ける
 */
export function areaDescription(a: {
  name: string; pref: string; title: string | null; insights: string[];
  population: { text: string; label: string } | null; statCount: number; note?: string;
}): string {
  const where = a.pref ? `（${a.pref}）` : "";
  const head = a.title ? `${a.name}${where}をデータで見ると「${a.title}」。` : `${a.name}${where}のデータ。`;
  const body = head + descriptionFact(a.insights) + (a.note ?? "") +
    (a.population ? `人口${a.population.text}（${periodYear(a.population.label)}）。` : "");
  const tail = `${a.statCount}の指標と順位を紹介。`;
  return (body + tail).length <= DESCRIPTION_MAX ? body + tail : body;
}

/**
 * 区を再編して今はない区。地図と地域ページは2020年国勢調査の境界なので残っている。
 * 題名・説明文・見出しで、今の区と取り違えないように書く（設計変更記録 #144）。
 * 浜松市は2024年1月に7区（22131〜22137）を中央区・浜名区・天竜区の3区にした
 */
export function formerWard(id: string): { label: string; note: string } | null {
  return /^muni-2213[1-7]$/.test(id) ? { label: "2024年再編前の区", note: "2024年1月の区の再編の前の区です。" } : null;
}
