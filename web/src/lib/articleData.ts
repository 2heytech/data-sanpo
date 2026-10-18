// 寄り道の本文で使う数値・地域名（ビルド時だけ）。本文に数値を手で書かず、公開データから出すためのもの。
// 実データで、本文が前提にしている値・地域が見つからないときは例外を投げてビルドを止める
// （データを差し替えたあとに、本文と表が食い違ったまま公開しないため。設計変更記録 #126）。
// 開発用の架空データ（fixture）や都道府県を絞ったプレビューでは地域も値も足りないので、止めずに「—」を出す。
import { loadAreas, loadIndicators, loadSmallAreas, loadValues, RELEASE } from "./data";
import { formatNumber, formatValue, ranked } from "./format";
import type { Indicator, ValueRow } from "./types";

export type ArticleLevel = "municipality" | "prefecture";

const CHUNK: Record<ArticleLevel, string> = { municipality: "municipalities", prefecture: "prefectures" };

export class ArticleDataError extends Error {}

/** 本文の前提が崩れたとき。全国の実データなら止め、架空データ・絞ったプレビューなら null を返す */
function fail(message: string): null {
  if (RELEASE.is_fixture || RELEASE.is_partial) return null;
  throw new ArticleDataError(`寄り道: ${message}（本文を実データに合わせて直してください）`);
}

export function indicator(id: string): Indicator | null {
  return loadIndicators().find((i) => i.id === id) ?? fail(`指標 ${id} がありません`);
}

/** 指標・時点・粒度の値の行（市区町村は地図にある市区町村だけ）。ないときは空 */
export function rows(id: string, period: string, level: ArticleLevel): ValueRow[] {
  const file = loadValues(id, period, CHUNK[level]);
  if (!file) {
    fail(`${id} の ${period} の${level === "municipality" ? "市区町村" : "都道府県"}の値がありません`);
    return [];
  }
  if (level === "prefecture") return file.rows;
  const known = new Set(loadAreas().municipalities.map((m) => m.id));
  return file.rows.filter((r) => known.has(r.entity_id));
}

/** 地域名。市区町村は「〇〇町（〇〇県）」の形（with_pref=false で県名なし）。町丁・字等は名前だけ */
export function areaName(entityId: string, withPref = true): string {
  const areas = loadAreas();
  if (entityId.startsWith("area-")) {
    return loadSmallAreas(entityId.slice(5, 10))?.find((a) => a.id === entityId)?.name ?? fail(`地域 ${entityId} がありません`) ?? "—";
  }
  if (entityId.startsWith("pref-")) {
    return areas.prefectures.find((p) => p.id === entityId)?.name ?? fail(`地域 ${entityId} がありません`) ?? "—";
  }
  const m = areas.municipalities.find((x) => x.id === entityId);
  if (!m) return fail(`地域 ${entityId} がありません`) ?? "—";
  const pref = areas.prefectures.find((p) => p.code === m.prefecture)?.name ?? "";
  return withPref ? `${m.name}（${pref}）` : m.name;
}

/** 地域の値を表示の形（単位つき）で。値がない・地域がないときは実データなら止める。町丁・字等（area-）も使える */
export function value(id: string, period: string, entityId: string): string {
  const ind = indicator(id);
  if (!ind) return "—";
  const row = entityId.startsWith("area-")
    ? loadValues(id, period, entityId.slice(5, 7))?.rows.find((r) => r.entity_id === entityId)
    : rows(id, period, entityId.startsWith("pref-") ? "prefecture" : "municipality").find((r) => r.entity_id === entityId);
  if (!row || row.value === null) return fail(`${id} の ${period} に ${entityId} の値がありません`) ?? "—";
  return formatValue(row, ind);
}

/**
 * 全国の値。率は都道府県の分子・分母の合計から計算し（率の平均にしない）、数は都道府県の値の合計。
 * 値のない都道府県が1つでもあれば全国の値は出さない（欠けた合計を全国の値として書かない）。
 */
export function nationalValue(id: string, period: string): string {
  const ind = indicator(id);
  if (!ind) return "—";
  const prefs = rows(id, period, "prefecture");
  if (prefs.length === 0 || prefs.some((r) => r.value === null)) return fail(`${id} の ${period} に値のない都道府県があります`) ?? "—";
  if (ind.kind === "count") {
    return formatValue({ value: prefs.reduce((s, r) => s + (r.value as number), 0), status: "derived" }, ind);
  }
  if (prefs.some((r) => r.numerator === undefined || r.denominator === undefined)) {
    return fail(`${id} の ${period} の都道府県に分子・分母がありません`) ?? "—";
  }
  const num = prefs.reduce((s, r) => s + r.numerator!, 0);
  const den = prefs.reduce((s, r) => s + r.denominator!, 0);
  return formatValue({ value: (num / den) * (ind.scale ?? 1), status: "derived" }, ind);
}

/** 値のある地域の数と、条件に当てはまる地域の数（prefCode を渡すと、その都道府県の市区町村だけで数える） */
export function count(id: string, period: string, level: ArticleLevel, test: (v: number) => boolean = () => true, prefCode?: string): string {
  const vals = rows(id, period, level).filter((r) => r.value !== null && (!prefCode || r.entity_id.startsWith(`muni-${prefCode}`)))
    .map((r) => r.value as number);
  if (vals.length === 0) return fail(`${id} の ${period} に値がありません`) ?? "—";
  return formatNumber(vals.filter(test).length, 0);
}

export interface ArticleRankRow extends ValueRow {
  rank: number;
}

/** 市区町村の種類（名前の最後の字）。政令指定都市の区・東京都の特別区は「区」 */
export type MuniKind = "市" | "町" | "村" | "区";

/**
 * 順位の表の行。order="high" は大きい順、"low" は小さい順（順位も小さい方から数える）。
 * expect に挙げた地域が上から n 件に入っていなければ、実データでは止める（本文でその地域を挙げているため）。
 * kind を渡すと、その種類の市区町村（市だけ・村だけなど）の中で数える。atLeast を渡すと、その値以上だけを並べる
 */
export function ranking(id: string, period: string, level: ArticleLevel, order: "high" | "low", n: number, expect: string[] = [],
  opts: { kind?: MuniKind; atLeast?: number } = {}): ArticleRankRow[] {
  const names = opts.kind ? new Map(loadAreas().municipalities.map((m) => [m.id, m.name])) : null;
  const all = rows(id, period, level).filter((r) => (!names || names.get(r.entity_id)?.endsWith(opts.kind!))
    && (opts.atLeast === undefined || (r.value !== null && r.value >= opts.atLeast)));
  const list = order === "high"
    ? ranked(all)
    : ranked(all.map((r) => ({ ...r, value: r.value === null ? null : -r.value }))).map((r) => ({ ...r, value: r.value === null ? null : -r.value }));
  const top = list.slice(0, n);
  const missing = expect.filter((e) => !top.some((r) => r.entity_id === e));
  if (missing.length) fail(`${id} の ${period} の${order === "high" ? "上位" : "下位"}${n}に ${missing.join("・")} が入っていません`);
  return top;
}

/** 順位（大きい方から。同じ値は同じ順位）と、値のある地域の数 */
export function rankOf(id: string, period: string, entityId: string): string {
  const level: ArticleLevel = entityId.startsWith("pref-") ? "prefecture" : "municipality";
  const list = ranked(rows(id, period, level));
  const r = list.find((x) => x.entity_id === entityId);
  if (!r) return fail(`${id} の ${period} に ${entityId} の順位がありません`) ?? "—";
  return `${formatNumber(list.length, 0)}${level === "prefecture" ? "都道府県" : "市区町村"}中${formatNumber(r.rank, 0)}位`;
}

/** 地域の値そのもの（本文で単位を変えて書くとき。例: 百万円 → 億円）。値がないときは実データなら止める */
export function raw(id: string, period: string, entityId: string): number | null {
  const row = rows(id, period, entityId.startsWith("pref-") ? "prefecture" : "municipality").find((r) => r.entity_id === entityId);
  if (!row || row.value === null) return fail(`${id} の ${period} に ${entityId} の値がありません`);
  return row.value;
}

/** 百万円の値を「約230億円」の形に（1億円未満は百万円のまま） */
export function oku(millionYen: number | null): string {
  if (millionYen === null) return "—";
  return millionYen >= 100 ? `約${formatNumber(Math.round(millionYen / 100), 0)}億円` : `${formatNumber(millionYen, 0)}百万円`;
}

/** 本文の前提（「AはBより広い」など）を確かめる。崩れていれば実データでは止める */
export function check(condition: boolean, message: string): void {
  if (!condition) fail(message);
}

/**
 * 時点を追うごとに続けて増えた地域と、最初の時点から最後の時点までの増加率（%、2つの時点の値から計算）。
 * どれかの時点に値のない地域は除き（0 にしない）、total はすべての時点に値のある地域の数
 */
export function steadyGrowth(id: string, periods: string[], level: ArticleLevel): { rows: ArticleRankRow[]; total: number } {
  const byPeriod = periods.map((p) => new Map(rows(id, p, level).map((r) => [r.entity_id, r.value])));
  const grew: ValueRow[] = [];
  let total = 0;
  for (const entity of byPeriod[0].keys()) {
    const vals = byPeriod.map((m) => m.get(entity) ?? null);
    if (vals.some((v) => v === null)) continue;
    total++;
    const v = vals as number[];
    if (v[0] > 0 && v.every((x, i) => i === 0 || x > v[i - 1])) {
      grew.push({ entity_id: entity, value: (v[v.length - 1] / v[0] - 1) * 100, status: "derived",
        numerator: v[v.length - 1] - v[0], denominator: v[0] });
    }
  }
  if (total === 0) fail(`${id} の ${periods.join("・")} に値がありません`);
  return { rows: ranked(grew), total };
}
