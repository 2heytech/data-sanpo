// 寄り道の本文の表に、どの地域が出てくるかを集める（ビルド時だけ。設計変更記録 #234）。
// 表の中身は本文の部品（ArticleRanking など）が公開データから作るので、記事の一覧（lib/articles.ts）には書かれていない。
// そこで、公開日が来た記事の本文を画面には出さずに1回だけ組み立て、部品が Astro.locals.articleTables に書き足した行を集める
// （lib/articleLinks.ts の collectTable）。記事の枠（layouts/Article.astro）は、このときは本文だけを組み立てる。
// 結果はビルドの間とっておき、記事・一覧・地域のページで使い回す
import type { AstroComponentFactory } from "astro/runtime/server/index.js";
import { experimental_AstroContainer as AstroContainer } from "astro/container";
import { publishedArticles } from "./articles";
import type { Mentions, TableMention } from "./articleLinks";

const bodies = import.meta.glob<{ default: AstroComponentFactory }>("../articles/*.astro");

let cache: Promise<Mentions> | null = null;

async function collect(): Promise<Mentions> {
  const container = await AstroContainer.create();
  const mentions: Mentions = new Map();
  for (const article of publishedArticles()) {
    const load = bodies[`../articles/${article.slug}.astro`];
    if (!load) continue;
    const articleTables: TableMention[] = [];
    await container.renderToString((await load()).default, { locals: { articleTables } });
    mentions.set(article.slug, articleTables);
  }
  return mentions;
}

/** 公開日が来た記事ごとの、表に出てくる地域 */
export function articleMentions(): Promise<Mentions> {
  return cache ??= collect();
}
