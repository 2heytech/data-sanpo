// 住民基本台帳の人口・世帯数（毎年1月1日）と、1年間の人口の動き（出生・死亡・転入・転出。設計変更記録 #238）。
// 地域ページの「人口の移り変わり」で、国勢調査より新しい人口と、人口が増えた・減った内訳を見せる。
// 「〇〇市 人口」で探して開いた人に、いちばん新しい数と、その1年の動きを答える
import { formatNumber } from "./format";

export interface JukiYear {
  /** 1年間（1月1日〜12月31日）の見出し（「2025年」） */
  year: string;
  births: number | null;
  deaths: number | null;
  /** 出生 − 死亡 */
  natural: number | null;
  /** 転入・転出と、住民票の職権による記載・消除などの差 */
  social: number | null;
  movedIn: number | null;
  movedOut: number | null;
  /** その年の終わり（次の1月1日）の人口 */
  populationAfter: number | null;
}

export interface JukiPopulation {
  /** いちばん新しい1月1日の見出し（「2026年1月1日現在」） */
  label: string;
  population: number;
  households: number | null;
  /** 1年前の1月1日からの人口の増減（人）。1年前の値がなければ null */
  change: number | null;
  /** 1年間の動き（新しい年から） */
  years: JukiYear[];
}

const n = (v: number) => formatNumber(v, 0);
/** 増減の数（「+3,336人」「-2,836人」「±0人」）。表では単位を付けない */
export const signed = (v: number, unit = "人") => `${v > 0 ? "+" : v < 0 ? "-" : "±"}${n(Math.abs(v))}${unit}`;

/** 1月1日の日付の見出しから「2026年1月1日」だけを取り出す */
const dateOf = (label: string) => label.replace(/現在$/, "");

/**
 * 人口の欄の文。1月1日の人口・世帯数、その前の1年間の出生・死亡（自然増減）と転入・転出（社会増減）、1年間の増減を、
 * 公表された数のまま書く（理由の推測は書かない）
 */
export function jukiLines(name: string, j: JukiPopulation): string[] {
  const lines = [`住民基本台帳では、${dateOf(j.label)}現在の${name}の人口は${n(j.population)}人` +
    `${j.households !== null ? `、世帯数は${n(j.households)}世帯` : ""}です。`];
  const y = j.years[0];
  if (!y) return lines;
  if (y.births !== null && y.deaths !== null) {
    lines.push(`${y.year}の1年間に生まれた人は${n(y.births)}人、亡くなった人は${n(y.deaths)}人でした` +
      `${y.natural !== null ? `（自然増減は${signed(y.natural)}）` : ""}。`);
  }
  if (y.social !== null) {
    lines.push(y.movedIn !== null && y.movedOut !== null
      ? `転入した人は${n(y.movedIn)}人、転出した人は${n(y.movedOut)}人で、` +
        `住民票のそのほかの増減も合わせた社会増減は${signed(y.social)}でした。`
      : `転入・転出などによる社会増減は${signed(y.social)}でした。`);
  }
  if (j.change !== null) {
    lines.push(j.change === 0 ? "1年前の1月1日と比べて、人口は変わっていません。"
      : `1年前の1月1日と比べて、人口は${n(Math.abs(j.change))}人${j.change > 0 ? "増えて" : "減って"}います。`);
  }
  return lines;
}
