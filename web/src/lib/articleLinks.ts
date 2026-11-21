// 寄り道どうし、寄り道と地域のつながり（設計変更記録 #233・#234）。
// 記事の順位の表に出てくる地域（lib/articleMentions.ts がビルドのときに本文から集める）をもとに、
// 記事の末尾の「あわせて読みたい」、地域のページの「登場する寄り道」、一覧ページの検索に使う。
// このファイルは計算だけ（Astro に頼らない）なので、テストから直接使える
import type { Article } from "./articles";

/** 記事の表の1行: どの地域が、どの表の何位に出てくるか */
export interface TableMention {
  /** muni-xxxxx・pref-xx */
  id: string;
  rank: number | null;
  /** 表の題名（「旅館・ホテルの数が多い市区町村（2021年）」） */
  caption: string;
  /** 駅・観測所の表のとき、その駅・観測所の名前（地域は、その駅・観測所のある市区町村） */
  via?: string;
}
/** 記事（slug）ごとの、表に出てくる地域 */
export type Mentions = Map<string, TableMention[]>;

/**
 * 表を出す部品（ArticleRanking など）から呼ぶ。本文から地域を集めているとき（Astro.locals.articleTables があるとき）だけ、
 * 表の行を書き足す。ふだんのページの組み立てでは何もしない
 */
export function collectTable(locals: { articleTables?: TableMention[] }, caption: string,
  rows: { id: string | null | undefined; rank: number | null; via?: string }[]): void {
  if (!locals.articleTables) return;
  for (const r of rows) {
    if (r.id) locals.articleTables.push({ id: r.id, rank: r.rank, caption, ...(r.via ? { via: r.via } : {}) });
  }
}

/** 表の題名から、末尾の時点などのかっこ書きを外す（「…が多い市区町村（2021年）」→「…が多い市区町村」） */
export const captionLabel = (caption: string): string => caption.replace(/（[^（）]*）$/, "");

const isMunicipality = (id: string) => id.startsWith("muni-");
const bestRank = (list: TableMention[]) => Math.min(...list.map((m) => m.rank ?? Infinity));
const newer = (a: Article, b: Article) => b.published.localeCompare(a.published);

/** 記事の表に出てくる市区町村（重なりなし） */
export function municipalitiesOf(mentions: Mentions, slug: string): Set<string> {
  return new Set((mentions.get(slug) ?? []).filter((m) => isMunicipality(m.id)).map((m) => m.id));
}

export interface RelatedArticle {
  article: Article;
  /** 両方の記事の表に出てくる市区町村（読んでいる記事で順位の高い順） */
  shared: string[];
  sameTheme: boolean;
}

/**
 * 記事の末尾の「あわせて読みたい」: 同じテーマの記事と、同じ市区町村が表に出てくる記事を先にして n 本。
 * どの記事にも出てくる市区町村（都心の区など）は、つながりとして軽く数える（出てくる記事が少ない市区町村ほど重い）。
 * どれにも当てはまらないときは新しい順
 */
export function relatedArticles(article: Article, all: Article[], mentions: Mentions, n = 3): RelatedArticle[] {
  const appearances = new Map<string, number>();
  for (const a of all) {
    for (const id of municipalitiesOf(mentions, a.slug)) appearances.set(id, (appearances.get(id) ?? 0) + 1);
  }
  const mine = mentions.get(article.slug) ?? [];
  const rankHere = (id: string) => bestRank(mine.filter((m) => m.id === id));
  const mineIds = municipalitiesOf(mentions, article.slug);
  return all.filter((a) => a.slug !== article.slug).map((a) => {
    const shared = [...municipalitiesOf(mentions, a.slug)].filter((id) => mineIds.has(id))
      .sort((x, y) => rankHere(x) - rankHere(y) || appearances.get(x)! - appearances.get(y)! || x.localeCompare(y));
    const weight = shared.reduce((sum, id) => sum + 1 / Math.max(1, appearances.get(id)! - 1), 0);
    const sameTheme = a.theme === article.theme;
    return { article: a, shared, sameTheme, score: (sameTheme ? 2 : 0) + Math.min(3, weight) };
  }).sort((x, y) => y.score - x.score || newer(x.article, y.article))
    .slice(0, n)
    .map(({ article: a, shared, sameTheme }) => ({ article: a, shared, sameTheme }));
}

/** 公開の古い順に並べたときの前後の記事 */
export function neighborsOf(article: Article, all: Article[]): { prev: Article | null; next: Article | null } {
  // 同じ日に公開した記事は、一覧（ARTICLES）で下にあるものを先に公開したものとする
  const ordered = [...all].reverse().sort((a, b) => a.published.localeCompare(b.published));
  const i = ordered.findIndex((a) => a.slug === article.slug);
  return { prev: i > 0 ? ordered[i - 1] : null, next: i >= 0 && i < ordered.length - 1 ? ordered[i + 1] : null };
}

export interface AreaArticle {
  article: Article;
  /** その地域が出てくる表（順位の高い順。同じ表は1回だけ） */
  tables: TableMention[];
}

const uniqueTables = (list: TableMention[]) => {
  const seen = new Set<string>();
  return [...list].sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity)).filter((m) => {
    const key = `${m.caption}\u0000${m.via ?? ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
};

/** 地域（市区町村・都道府県）のページに出す「この地域が登場する寄り道」。順位の高い記事を先に、同じなら新しい順 */
export function articlesForArea(areaId: string, all: Article[], mentions: Mentions): AreaArticle[] {
  return all.flatMap((article) => {
    const tables = uniqueTables((mentions.get(article.slug) ?? []).filter((m) => m.id === areaId));
    return tables.length ? [{ article, tables }] : [];
  }).sort((a, b) => bestRank(a.tables) - bestRank(b.tables) || newer(a.article, b.article));
}

export interface PrefectureArticle {
  article: Article;
  /** その都道府県が出てくる都道府県の表 */
  tables: TableMention[];
  /** その都道府県の市区町村のうち、記事の表に出てくるもの（順位の高い順） */
  municipalities: { id: string; rank: number | null }[];
}

/**
 * 都道府県のページに出す寄り道: その都道府県が都道府県の表に出てくる記事と、その都道府県の市区町村が表に出てくる記事。
 * 順位の高い記事を先に、同じなら新しい順
 */
export function articlesForPrefecture(prefCode: string, all: Article[], mentions: Mentions): PrefectureArticle[] {
  return all.flatMap((article) => {
    const list = mentions.get(article.slug) ?? [];
    const tables = uniqueTables(list.filter((m) => m.id === `pref-${prefCode}`));
    const best = new Map<string, number | null>();
    for (const m of list) {
      if (!m.id.startsWith(`muni-${prefCode}`)) continue;
      const cur = best.get(m.id);
      if (cur === undefined || (m.rank ?? Infinity) < (cur ?? Infinity)) best.set(m.id, m.rank);
    }
    const municipalities = [...best].map(([id, rank]) => ({ id, rank }))
      .sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity) || a.id.localeCompare(b.id));
    return tables.length || municipalities.length ? [{ article, tables, municipalities }] : [];
  }).sort((a, b) => best(a) - best(b) || newer(a.article, b.article));
}
const best = (p: PrefectureArticle) => Math.min(bestRank(p.tables), ...p.municipalities.map((m) => m.rank ?? Infinity));
