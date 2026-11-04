// 指標の一覧（ジャンル → カテゴリ → 指標名のボタン）を組み立てる。指標の一覧のページ（/indicators/）と、
// トップページの「指標から探す」（ジャンルごとに代表の指標だけ）で使う（設計変更記録 #47・#173・#196）
import { loadAreas, loadIndicators, loadPlace } from "./data";
import { GENRES } from "./genres";
import { listItems, listTags, type ListItem, type ListTag } from "./indicatorList";
import type { WeatherElement } from "./types";

export interface Entry { item: ListItem; tags: ListTag[] }
export interface Genre { title: string; categories: string[]; count: number; anchor: string }

// 地図の点で見るデータ（地域の塗り分けではなく、駅・学校・地点ごとの値）。地図で点の表示をオンにして開く。
// 地価は地価公示と都道府県地価調査を地図で1つの「地価」の表示にまとめている（#134）ので、1つの項目にする
interface PointRow { files: string[]; category: string; show: string; name?: string; description?: string }
const POINT_ROWS: PointRow[] = [
  { files: ["station_passengers"], category: "交通", show: "stations" },
  { files: ["airport_passengers"], category: "交通", show: "airports" },
  { files: ["port_passengers"], category: "交通", show: "ports" },
  { files: ["school_enrollment"], category: "教育", show: "schools" },
  { files: ["land_price", "land_survey_price"], category: "地価", show: "land", name: "地価（地価公示・都道府県地価調査）",
    description: "国が毎年1月1日時点で判定する地価公示の標準地と、都道府県が毎年7月1日時点で判定する都道府県地価調査の基準地の、1㎡あたりの価格。地点ごとの値です。" },
  { files: ["nursery_capacity"], category: "子育て", show: "nurseries" },
  { files: ["michi_no_eki"], category: "観光", show: "michi" },
  { files: ["cultural_properties"], category: "観光", show: "bunka" },
];

/** ジャンルごとに、カテゴリを順に1つずつ回って先頭の項目から選ぶ（どのカテゴリからも代表が出るように）。max 個まで */
export function pickRepresentatives<T>(lists: T[][], max: number): T[] {
  const out: T[] = [];
  for (let k = 0; out.length < max && lists.some((l) => l.length > k); k++) {
    for (const l of lists) {
      if (k < l.length && out.length < max) out.push(l[k]);
    }
  }
  return out;
}

export function indicatorCatalog() {
  const indicators = loadIndicators();
  const areas = loadAreas();
  const points = POINT_ROWS.flatMap(({ files, ...p }) => {
    const ds = files.flatMap((f) => loadPlace(f) ?? []);
    if (!ds.length) return [];
    // まとめた項目でも、片方しかない公開版ではその指標の名前・説明にする
    const merged = ds.length > 1;
    return [{ ...p, name: (merged && p.name) || ds[0].name, description: (merged && p.description) || ds[0].description }];
  }).concat(weatherPoints());

  const hasCategory = (c: string) => indicators.some((i) => i.category === c) || points.some((p) => p.category === c);
  const known = new Set(GENRES.flatMap((g) => g.categories));
  const rest = [...new Set(indicators.map((i) => i.category))].filter((c) => !known.has(c));
  const genres: Genre[] = [...structuredClone(GENRES), ...(rest.length ? [{ title: "その他", categories: rest }] : [])]
    .filter((g) => g.categories.some(hasCategory))
    .map((g, k) => {
      const categories = g.categories.filter(hasCategory);
      const count = indicators.filter((i) => categories.includes(i.category)).length
        + points.filter((p) => categories.includes(p.category)).length;
      return { title: g.title, categories, count, anchor: `genre-${k}` };
    });

  // 一覧の項目（指標名のボタン）と範囲の札（東京都だけ・都道府県別だけ・地図の点）
  const byId = new Map(indicators.map((i) => [i.id, i]));
  const prefName = new Map(areas.prefectures.map((p) => [p.code, p.name]));
  const cache = new Map<string, Entry[]>();
  function entriesOf(category: string): Entry[] {
    if (cache.has(category)) return cache.get(category)!;
    const items = listItems(indicators, category).map((item) => ({
      item, tags: listTags(item, byId, areas.prefectures.length, (code) => prefName.get(code) ?? code),
    }));
    const pts = points.filter((p) => p.category === category).map((p) => {
      const href = `/map/?show=${p.show}`;
      return { item: { title: p.name, href, description: p.description, members: [{ label: p.name, href, extras: [] }], ids: [] },
        tags: [{ kind: "point", text: "点" } as ListTag] };
    });
    const list = [...items, ...pts];
    cache.set(category, list);
    return list;
  }
  const allTags = genres.flatMap((g) => g.categories.flatMap((c) => entriesOf(c).flatMap((e) => e.tags)));
  return {
    /** 色分けの指標の数（地図の点で見るデータは数えない） */
    total: indicators.length,
    pointCount: points.length,
    genres,
    entriesOf,
    /** トップページに出す代表の指標（ジャンルごとに max 個まで） */
    representatives: (g: Genre, max: number) => pickRepresentatives(g.categories.map(entriesOf), max),
    areaExample: allTags.find((t) => t.kind === "area")?.text,
    tagKinds: new Set(allTags.map((t) => t.kind)),
  };
}

// 天気（気象庁の平年値）は1ファイルに日照時間・降水量などをまとめているので、指標ごとに1つの項目にする（#94）
function weatherPoints() {
  const d = loadPlace("weather_normals") as (ReturnType<typeof loadPlace> & { elements?: WeatherElement[] }) | null;
  return (d?.elements ?? []).map((e) => ({ category: "天気", show: `weather&wx=${e.id}`, name: e.name, description: e.description }));
}
