// 寄り道の一覧ページの検索（設計変更記録 #232）。題名・説明文・テーマに加えて、記事で使った指標の名前と、
// 記事の順位の表に出てくる市区町村・都道府県の名前でも探せるようにする。
// 言葉のそろえ方・読み・近い意味の言葉は、指標の検索（lib/indicatorSearch.ts、#201）と同じものを使う。
// このファイルは計算だけ（Astro に頼らない）。一覧ページのスクリプトが、検索欄を初めて使うときに読む
import type { Article } from "./articles";
import type { Mentions } from "./articleLinks";
import { IndicatorSearch, normalizeText, type SearchDoc } from "./indicatorSearch";

/** 一覧ページに埋め込む、記事ごとの検索用の情報（題名・説明文・テーマはカードから読む） */
export interface ArticleSearchEntry {
  /** 記事で使った指標の名前 */
  indicators: string[];
  /** 表に出てくる市区町村 [名前, 都道府県名]（順位の高い順） */
  areas: [string, string][];
  /** 都道府県の表に出てくる都道府県の名前（順位の高い順） */
  prefectures: string[];
}
/** 記事（slug）ごと */
export type ArticleSearchData = Record<string, ArticleSearchEntry>;

interface Names {
  indicators: { id: string; name: string }[];
  municipalities: { id: string; name: string; prefecture: string }[];
  prefectures: { code: string; name: string }[];
}

/** ビルドのときに、記事ごとの検索用の情報を作る */
export function articleSearchData(articles: Article[], mentions: Mentions, names: Names): ArticleSearchData {
  const indicatorName = new Map(names.indicators.map((i) => [i.id, i.name]));
  const muni = new Map(names.municipalities.map((m) => [m.id, m]));
  const prefName = new Map(names.prefectures.map((p) => [p.code, p.name]));
  const byRank = (a: { rank: number | null }, b: { rank: number | null }) => (a.rank ?? Infinity) - (b.rank ?? Infinity);
  const data: ArticleSearchData = {};
  for (const article of articles) {
    const list = [...(mentions.get(article.slug) ?? [])].sort(byRank);
    const ids = [...new Set(list.map((m) => m.id))];
    data[article.slug] = {
      indicators: article.indicators.flatMap((id) => indicatorName.get(id) ?? []),
      areas: ids.flatMap((id): [string, string][] => {
        const m = muni.get(id);
        return m ? [[m.name, prefName.get(m.prefecture) ?? ""]] : [];
      }),
      prefectures: ids.flatMap((id) => (id.startsWith("pref-") ? prefName.get(id.slice(5)) ?? [] : [])),
    };
  }
  return data;
}

/** カードに書いてある記事の情報 */
export interface ArticleCardText {
  slug: string;
  title: string;
  description: string;
  /** テーマの名前 */
  theme: string;
}
export interface ArticleHit {
  slug: string;
  /** 入れた言葉が名前に当たった、記事の表に出てくる地域（順位の高い順） */
  areas: string[];
}

interface Doc extends SearchDoc { slug: string }

const unique = (list: string[]) => [...new Set(list.filter(Boolean))];

/** 入れた言葉が名前に当たる地域（市区町村は名前か都道府県名、都道府県は名前） */
export function matchedAreas(entry: ArticleSearchEntry, query: string): string[] {
  const chunks = query.normalize("NFKC").split(/[\s、,・/]+/).map(normalizeText).filter((c) => c.length >= 2);
  if (!chunks.length) return [];
  const hit = (name: string) => {
    const n = normalizeText(name);
    return n.length > 0 && chunks.some((c) => n.includes(c) || (n.length >= 3 && c.includes(n)));
  };
  return unique([
    ...entry.areas.filter(([name, pref]) => hit(name) || hit(pref)).map(([name]) => name),
    ...entry.prefectures.filter(hit),
  ]);
}

/** 「登場: 白馬村・野沢温泉村 ほか2」 */
export function hitLabel(areas: string[], max = 3): string {
  if (!areas.length) return "";
  return `登場: ${areas.slice(0, max).join("・")}${areas.length > max ? ` ほか${areas.length - max}` : ""}`;
}

export class ArticleSearch {
  private searcher: IndicatorSearch<Doc>;

  constructor(cards: ArticleCardText[], private data: ArticleSearchData) {
    this.searcher = new IndicatorSearch(cards.map((c): Doc => {
      const entry = data[c.slug];
      return {
        slug: c.slug,
        name: c.title,
        // 指標・地域の名前は、題名に次いで重く見る（説明文だけに当たる記事より上にする）
        alt: unique([
          c.theme,
          ...(entry?.indicators ?? []),
          ...(entry?.areas.map(([name]) => name) ?? []),
          ...(entry?.areas.map(([, pref]) => pref) ?? []),
          ...(entry?.prefectures ?? []),
        ]),
        description: c.description,
      };
    }));
  }

  /** 当たった記事（当たりの強い順。同じなら一覧の並びのまま） */
  search(query: string): ArticleHit[] {
    return this.searcher.search(query).map(({ doc }) => {
      const entry = this.data[doc.slug];
      return { slug: doc.slug, areas: entry ? matchedAreas(entry, query) : [] };
    });
  }
}
