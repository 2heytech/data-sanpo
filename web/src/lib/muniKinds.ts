// 市・町・村・東京23区ごとの順位（設計変更記録 #247）。
// 「日本一小さい市」「北海道で一番小さい市町村」「日本一大きい村」のように、市・町・村を分けて探す検索に、指標ページの中で答える。
// 市区町村ランキングは市・町・村・区を1つの順位にしているので、いちばん狭いのが村になり、いちばん狭い市はすぐに見えない。
// 政令指定都市は区の合計を1つの市として数え（市全体の値を区から計算できない市は入れない）、区は入れない
import type { CityValue } from "./designatedCities";
import type { Municipality, ValueRow } from "./types";

export type MuniKind = "市" | "町" | "村" | "東京23区";
export const MUNI_KINDS: MuniKind[] = ["市", "町", "村", "東京23区"];

/** 市・町・村ごとの順位を出す指標と、大きい側・小さい側の言い方 */
export const KIND_PAGES: Record<string, { more: string; less: string }> = {
  area: { more: "広い", less: "狭い" },
  population_total: { more: "人口が多い", less: "人口が少ない" },
  population_density: { more: "人口密度が高い", less: "人口密度が低い" },
  elevation_mean: { more: "平均標高が高い", less: "平均標高が低い" },
};

/** 上位・下位それぞれの数 */
export const KIND_SIZE = 10;

/** 市区町村の種類。政令指定都市の区は null（市全体で数える） */
export function muniKind(m: Pick<Municipality, "name" | "region">, isDesignatedWard: boolean): MuniKind | null {
  if (m.region === "区部") return "東京23区";
  if (isDesignatedWard) return null;
  if (m.name.endsWith("市")) return "市";
  if (m.name.endsWith("町")) return "町";
  if (m.name.endsWith("村")) return "村";
  return null;
}

export interface KindEntry {
  /** 地域 ID（政令指定都市は null。地域ページがない） */
  id: string | null;
  name: string;
  prefecture: string;
  row: ValueRow;
  rank: number;
}

export interface KindRanking {
  kind: MuniKind;
  /** 値のある数 */
  total: number;
  /** 大きい順（total が KIND_SIZE × 2 以下なら全部） */
  top: KindEntry[];
  /** 小さい順（top に全部入れたときは空） */
  bottom: KindEntry[];
}

function rankBy(entries: Omit<KindEntry, "rank">[], dir: 1 | -1): KindEntry[] {
  const sorted = [...entries].sort((a, b) => dir * ((b.row.value as number) - (a.row.value as number)));
  let rank = 0;
  return sorted.map((e, i) => {
    if (i === 0 || e.row.value !== sorted[i - 1].row.value) rank = i + 1;
    return { ...e, rank };
  });
}

/**
 * 市・町・村・東京23区ごとの順位。値のない市区町村は入れない（0 にしない）。
 * cities は政令指定都市の市全体の値（designatedCities.ts の cityValues。値のない市は入れない）
 */
export function kindRankings(munis: Municipality[], rows: ValueRow[], wardIds: Set<string>, cities: CityValue[]): KindRanking[] {
  const byId = new Map(munis.map((m) => [m.id, m]));
  const groups = new Map<MuniKind, Omit<KindEntry, "rank">[]>();
  const add = (kind: MuniKind, e: Omit<KindEntry, "rank">) => groups.set(kind, [...(groups.get(kind) ?? []), e]);
  for (const r of rows) {
    const m = byId.get(r.entity_id);
    if (!m || r.value === null) continue;
    const kind = muniKind(m, wardIds.has(m.id));
    if (kind) add(kind, { id: m.id, name: m.name, prefecture: m.prefecture, row: r });
  }
  for (const c of cities) {
    if (c.value === null) continue;
    add("市", { id: null, name: c.city.name, prefecture: c.city.prefecture, row: { entity_id: `city-${c.city.prefecture}-${c.city.name}`, value: c.value, status: "derived" } });
  }
  return MUNI_KINDS.flatMap((kind) => {
    const list = groups.get(kind) ?? [];
    if (list.length < 2 || new Set(list.map((e) => e.row.value)).size < 2) return [];
    const top = rankBy(list, 1);
    if (list.length <= KIND_SIZE * 2) return [{ kind, total: list.length, top, bottom: [] }];
    return [{ kind, total: list.length, top: top.slice(0, KIND_SIZE), bottom: rankBy(list, -1).slice(0, KIND_SIZE) }];
  });
}

const names = (list: string[]) => list.slice(0, 3).join("・") + (list.length > 3 ? "など" : "");

/**
 * 冒頭の「データから分かること」に足す2文（市・町・村の大きい側と小さい側）。
 * 「市・町・村に分けると、いちばん広い市は岐阜県高山市（2,177.61km²）、町は…、村は…です。」
 */
export function kindFacts(kinds: KindRanking[], words: { more: string; less: string }, label: (e: KindEntry) => string,
  text: (e: KindEntry) => string): string[] {
  const main = kinds.filter((k) => k.kind !== "東京23区");
  if (main.length < 2) return [];
  const side = (pick: (k: KindRanking) => KindEntry[]) => main.map((k) => {
    const list = pick(k);
    const first = list.filter((e) => e.rank === 1);
    return `${k.kind}は${names(first.map(label))}（${text(first[0])}）`;
  });
  const ascending = (k: KindRanking) => k.bottom.length ? k.bottom : rankBy(k.top, -1);
  const [moreFirst, ...moreRest] = side((k) => k.top);
  const [lessFirst, ...lessRest] = side(ascending);
  const join = (first: string, rest: string[], w: string) => `いちばん${w}${first}${rest.length ? `、${rest.join("、")}` : ""}`;
  return [
    `市・町・村に分けると、${join(moreFirst, moreRest, words.more)}です。`,
    `${join(lessFirst, lessRest, words.less)}です。`,
  ];
}
