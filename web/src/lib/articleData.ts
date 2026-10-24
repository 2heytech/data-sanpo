// 寄り道の本文で使う数値・地域名（ビルド時だけ）。本文に数値を手で書かず、公開データから出すためのもの。
// 実データで、本文が前提にしている値・地域が見つからないときは例外を投げてビルドを止める
// （データを差し替えたあとに、本文と表が食い違ったまま公開しないため。設計変更記録 #126）。
// 開発用の架空データ（fixture）や都道府県を絞ったプレビューでは地域も値も足りないので、止めずに「—」を出す。
import { loadAreas, loadFacilityPoints, loadIndicators, loadSmallAreas, loadStations, loadValues, RELEASE } from "./data";
import { formatNumber, formatValue, ranked } from "./format";
import type { FacilityPoint, Indicator, Station, ValueRow } from "./types";

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

export interface ArticleCompareRow {
  entity_id: string;
  rank: number;
  from: ValueRow;
  to: ValueRow;
  /** 後の値 ÷ 前の値 */
  ratio: number;
}

/**
 * 2つの時点の値を地域ごとに並べ、後の値÷前の値（倍率）の順に並べる。時点ごとに指標が違ってもよい
 * （例: 1920年は「人口（1920年からの推移）」、2025年は「人口」）。どちらかの値がない地域は除き（0 にしない）、
 * expect に挙げた地域が上から n 件に入っていなければ実データでは止める（ranking と同じ）。
 * 2つの指標の割合（例: 宿泊業で働く人÷働く人）にも使う。minFrom を渡すと、前の値がそれ未満の地域を除く（小さな数の割合が極端になるため）
 */
export function compareRanking(from: { id: string; period: string }, to: { id: string; period: string }, level: ArticleLevel,
  order: "high" | "low", n: number, expect: string[] = [], opts: { minFrom?: number } = {}): ArticleCompareRow[] {
  const before = new Map(rows(from.id, from.period, level).map((r) => [r.entity_id, r]));
  const pairs = rows(to.id, to.period, level).flatMap((r) => {
    const b = before.get(r.entity_id);
    if (!b || b.value === null || r.value === null || b.value <= 0) return [];
    if (opts.minFrom !== undefined && b.value < opts.minFrom) return [];
    return [{ entity_id: r.entity_id, from: b, to: r, ratio: r.value / b.value }];
  });
  if (pairs.length === 0) fail(`${from.id} の ${from.period} と ${to.id} の ${to.period} に、両方の値のある地域がありません`);
  const sign = order === "high" ? -1 : 1;
  const sorted = pairs.sort((a, b) => sign * (a.ratio - b.ratio));
  let rank = 0;
  const list = sorted.map((p, i) => {
    if (i === 0 || p.ratio !== sorted[i - 1].ratio) rank = i + 1;
    return { ...p, rank };
  });
  const top = list.slice(0, n);
  const missing = expect.filter((e) => !top.some((r) => r.entity_id === e));
  if (missing.length) fail(`${from.id}→${to.id} の倍率の${order === "high" ? "上位" : "下位"}${n}に ${missing.join("・")} が入っていません`);
  return top;
}

/** 地域の値がいちばん大きかった時点（複数の指標・時点をまとめて見る。同じ値なら新しい方）。値のない時点は飛ばす */
export function peakPeriod(series: { id: string; period: string }[], entityId: string): { period: string; value: number } | null {
  let best: { period: string; value: number } | null = null;
  const level: ArticleLevel = entityId.startsWith("pref-") ? "prefecture" : "municipality";
  for (const s of series) {
    const v = rows(s.id, s.period, level).find((r) => r.entity_id === entityId)?.value ?? null;
    if (v !== null && (!best || v >= best.value)) best = { period: s.period, value: v };
  }
  if (!best) fail(`${entityId} の値がどの時点にもありません`);
  return best;
}

/**
 * 政令指定都市ごとの、区の値の合計（区ごとの値しかない指標で、市全体と比べるため）。
 * 値のない区が1つでもある市は value を null にする（欠けた合計を市の値にしない）。大きい順
 */
export function cityTotals(id: string, period: string): { city: string; value: number | null; wards: number }[] {
  const byId = new Map(rows(id, period, "municipality").map((r) => [r.entity_id, r.value]));
  const cities = new Map<string, (number | null)[]>();
  for (const m of loadAreas().municipalities) {
    if (!m.region?.endsWith("市") || !m.name.startsWith(m.region)) continue;
    cities.set(m.region, [...(cities.get(m.region) ?? []), byId.get(m.id) ?? null]);
  }
  return [...cities].map(([city, vals]) => ({
    city, wards: vals.length, value: vals.some((v) => v === null) ? null : vals.reduce<number>((s, v) => s + v!, 0),
  })).sort((a, b) => (b.value ?? -Infinity) - (a.value ?? -Infinity));
}

/** 政令指定都市の区の値の合計（cityTotals の1市分）。値がない・市がないときは実データなら止める */
export function cityTotal(id: string, period: string, city: string): number | null {
  const hit = cityTotals(id, period).find((c) => c.city === city);
  if (!hit || hit.value === null) return fail(`${id} の ${period} に ${city} の区の合計がありません`);
  return hit.value;
}

/** 駅（名前と事業者で探す。地図に重ねる「駅」の点）。見つからないときは実データなら止める */
export function station(name: string, operator: string): Station | null {
  return loadStations().stations.find((s) => s.name === name && s.operator === operator)
    ?? fail(`駅 ${name}（${operator}）がありません`);
}

/** 駅の年度の乗降客数（年度は "2019-04-01" の形）。値がないときは実データなら止める */
export function stationCount(s: Station | null, period: string): number | null {
  const i = loadStations().periods.indexOf(period);
  const v = s && i >= 0 ? s.values[i] : null;
  if (v === null || v === undefined) return fail(`駅 ${s?.name ?? "?"} の ${period} の乗降客数がありません`);
  return v;
}

export interface StationChangeRow {
  station: Station;
  rank: number;
  from: number;
  to: number;
  /** 後の年度 ÷ 前の年度 */
  ratio: number;
}

/**
 * 2つの年度の乗降客数を駅ごとに比べる（同じ事業者の値どうし。事業者の違う値は足さない）。
 * 比べる駅は、since から from までの毎年度と to に値があり、from の値が min 以上 max 未満の駅
 * （開業して間もない駅の伸びや、数え方の違いで値が大きく動く大きな駅を除くため）。倍率の大きい順
 */
export function stationChanges(from: string, to: string, opts: { since: string; min: number; max: number }): StationChangeRow[] {
  const { periods, stations } = loadStations();
  const [s0, f, t] = [periods.indexOf(opts.since), periods.indexOf(from), periods.indexOf(to)];
  if (s0 < 0 || f < 0 || t < 0) {
    fail(`駅の乗降客数に ${opts.since}・${from}・${to} の年度がありません`);
    return [];
  }
  const pairs = stations.flatMap((s) => {
    const a = s.values[f], b = s.values[t];
    if (a === null || b === null || a < opts.min || a >= opts.max) return [];
    if (s.values.slice(s0, f + 1).some((v) => v === null)) return [];
    return [{ station: s, from: a, to: b, ratio: b / a }];
  });
  if (pairs.length === 0) fail(`駅の乗降客数に ${from} と ${to} の両方の値がある駅がありません`);
  const sorted = pairs.sort((a, b) => b.ratio - a.ratio || a.station.id.localeCompare(b.station.id));
  let rank = 0;
  return sorted.map((p, i) => {
    if (i === 0 || p.ratio !== sorted[i - 1].ratio) rank = i + 1;
    return { ...p, rank };
  });
}

/** stationChanges の上から n 駅。expect に挙げた駅（ID）が入っていなければ実データでは止める */
export function stationRanking(from: string, to: string, opts: { since: string; min: number; max: number }, n: number,
  expect: (Station | null)[] = []): StationChangeRow[] {
  const top = stationChanges(from, to, opts).slice(0, n);
  const missing = expect.filter((e) => !e || !top.some((r) => r.station.id === e.id));
  if (missing.length) fail(`駅の乗降客数の伸びの上位${n}に ${missing.map((e) => e?.name ?? "?").join("・")} が入っていません`);
  return top;
}

/** 国指定文化財などの点（都道府県ごとのファイルを全国分）のうち、条件に当てはまるものの数 */
export function facilityCount(name: string, test: (p: FacilityPoint) => boolean): number | null {
  const points = loadFacilityPoints(name);
  if (points.length === 0) return fail(`点のデータ ${name} がありません`);
  return points.filter(test).length;
}
