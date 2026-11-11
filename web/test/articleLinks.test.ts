import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  articlesForArea, articlesForPrefecture, captionLabel, collectTable, municipalitiesOf, neighborsOf, relatedArticles,
  type Mentions, type TableMention,
} from "../src/lib/articleLinks";
import { ArticleSearch, articleSearchData, hitLabel, matchedAreas } from "../src/lib/articleSearch";
import { ARTICLES, ARTICLE_THEMES, newestFirst, themeCounts, themeHref, themeName, type Article, type ArticleThemeId } from "../src/lib/articles";

// 寄り道を探しやすくする仕組み（設計変更記録 #232〜#235）: テーマ、あわせて読みたい、地域のページの「登場する寄り道」、一覧の検索
const article = (slug: string, theme: ArticleThemeId, published: string, extra: Partial<Article> = {}): Article => ({
  slug, title: `${slug} の題名`, description: `${slug} の説明`, published, theme, indicators: [], ...extra,
});
const row = (id: string, rank: number | null, caption: string, via?: string): TableMention => ({ id, rank, caption, ...(via ? { via } : {}) });

describe("寄り道のテーマ（#232）", () => {
  it("どの記事にも、決めたテーマが1つ付いている", () => {
    const ids = new Set<string>(ARTICLE_THEMES.map((t) => t.id));
    for (const a of ARTICLES) expect(ids.has(a.theme), a.slug).toBe(true);
  });

  it("テーマごとの本数は、記事のあるテーマだけを決めた並びで返す", () => {
    const list = [article("a", "land", "2026-10-01"), article("b", "population", "2026-10-02"), article("c", "land", "2026-10-03")];
    expect(themeCounts(list)).toEqual([{ id: "population", name: "人口", count: 1 }, { id: "land", name: "地形と自然", count: 2 }]);
    expect(themeCounts(ARTICLES).reduce((sum, t) => sum + t.count, 0)).toBe(ARTICLES.length);
  });

  it("テーマの札は、絞り込んだ一覧を開く", () => {
    expect(themeHref("travel")).toBe("/articles/?theme=travel");
    expect(themeName("money")).toBe("お金と仕事");
  });

  it("新しい順は公開日で並べ、本文を直した日では並べ替えない", () => {
    const list = [article("old", "land", "2026-10-01", { updated: "2026-11-30" }), article("new", "land", "2026-11-01")];
    expect(newestFirst(list).map((a) => a.slug)).toEqual(["new", "old"]);
  });
});

describe("記事の表に出てくる地域（#234）", () => {
  it("本文から集めているときだけ、表の行を書き足す", () => {
    const locals: { articleTables?: TableMention[] } = {};
    collectTable(locals, "表", [{ id: "muni-01100", rank: 1 }]);
    expect(locals.articleTables).toBeUndefined();
    locals.articleTables = [];
    collectTable(locals, "乗降客数が増えた駅（2019→2024年度）", [
      { id: "muni-12227", rank: 1, via: "舞浜" }, { id: null, rank: 2, via: "場所の分からない駅" }, { id: "pref-13", rank: 3 },
    ]);
    expect(locals.articleTables).toEqual([
      { id: "muni-12227", rank: 1, caption: "乗降客数が増えた駅（2019→2024年度）", via: "舞浜" },
      { id: "pref-13", rank: 3, caption: "乗降客数が増えた駅（2019→2024年度）" },
    ]);
  });

  it("順位の表の部品は、どれも表の行を知らせる", () => {
    // 表を出す部品を足したときに入れ忘れると、その表の地域が検索や地域のページに出ない
    const dir = join(__dirname, "../src/components");
    const tables = readdirSync(dir).filter((f) => /^Article(Ranking|GrowthRanking|Compare|Stations|Weather)\.astro$/.test(f));
    expect(tables).toHaveLength(5);
    for (const f of tables) expect(readFileSync(join(dir, f), "utf-8"), f).toContain("collectTable(Astro.locals, caption,");
  });

  it("記事の枠は、本文から集めているときは本文だけを出し、集めた結果を待たない", () => {
    const layout = readFileSync(join(__dirname, "../src/layouts/Article.astro"), "utf-8");
    expect(layout).toContain("const collecting = Boolean(Astro.locals.articleTables);");
    expect(layout).toContain("collecting ? new Map() : await articleMentions()");
    expect(layout).toContain("{collecting ? <slot /> : (");
  });

  it("表の題名から、末尾のかっこ書きだけを外す", () => {
    expect(captionLabel("旅館・ホテルの数が多い市区町村（2021年）")).toBe("旅館・ホテルの数が多い市区町村");
    expect(captionLabel("人口（国勢調査）が増えた市区町村（2020→2025年）")).toBe("人口（国勢調査）が増えた市区町村");
    expect(captionLabel("かっこのない題名")).toBe("かっこのない題名");
  });
});

describe("あわせて読みたい（#233）", () => {
  const all = [
    article("self", "travel", "2026-10-10"),
    article("same-theme", "travel", "2026-10-01"),
    article("shared-rare", "money", "2026-10-02"),
    article("shared-common", "life", "2026-10-03"),
    article("newest", "land", "2026-11-01"),
    article("older", "land", "2026-09-01"),
  ];
  const mentions: Mentions = new Map([
    ["self", [row("muni-20485", 1, "表A"), row("muni-13101", 2, "表A"), row("pref-20", 1, "表B")]],
    ["shared-rare", [row("muni-20485", 5, "表C")]],
    ["shared-common", [row("muni-13101", 1, "表D")]],
    ["newest", [row("muni-13101", 3, "表E")]],
    ["older", [row("muni-13101", 9, "表F"), row("pref-20", 2, "表G")]],
  ]);

  it("同じテーマの記事と、同じ市区町村が出てくる記事を先にする（自分は入れない）", () => {
    const result = relatedArticles(all[0], all, mentions);
    expect(result.map((r) => r.article.slug)).toEqual(["same-theme", "shared-rare", "newest"]);
    expect(result[0]).toMatchObject({ sameTheme: true, shared: [] });
    expect(result[1]).toMatchObject({ sameTheme: false, shared: ["muni-20485"] });
  });

  it("多くの記事に出てくる市区町村は軽く数える（同じ重みなら新しい順）", () => {
    // 13101 は4本、20485 は2本の記事に出てくる。都道府県（pref-20）はつながりに数えない
    const result = relatedArticles(all[0], all, mentions, 5);
    expect(result.map((r) => r.article.slug)).toEqual(["same-theme", "shared-rare", "newest", "shared-common", "older"]);
    expect(municipalitiesOf(mentions, "older")).toEqual(new Set(["muni-13101"]));
  });

  it("つながりがないときは新しい順", () => {
    const result = relatedArticles(all[0], all, new Map(), 2);
    expect(result.map((r) => r.article.slug)).toEqual(["same-theme", "newest"]);
  });

  it("共通の市区町村は、読んでいる記事で順位の高い順に並べる", () => {
    const both: Mentions = new Map([
      ["self", [row("muni-00002", 7, "表"), row("muni-00001", 3, "表")]],
      ["newest", [row("muni-00002", 1, "表"), row("muni-00001", 1, "表")]],
    ]);
    expect(relatedArticles(all[0], all, both, 1)[0].shared).toEqual(["muni-00001", "muni-00002"]);
  });

  it("前後の記事は公開の順（同じ日は、一覧で下にある記事が先）", () => {
    const list = [article("c", "land", "2026-10-05"), article("b2", "land", "2026-10-03"), article("b1", "land", "2026-10-03"), article("a", "land", "2026-10-01")];
    expect(neighborsOf(list[2], list)).toMatchObject({ prev: { slug: "a" }, next: { slug: "b2" } });
    expect(neighborsOf(list[1], list)).toMatchObject({ prev: { slug: "b1" }, next: { slug: "c" } });
    expect(neighborsOf(list[3], list).prev).toBeNull();
    expect(neighborsOf(list[0], list).next).toBeNull();
  });
});

describe("地域のページの「登場する寄り道」（#234）", () => {
  const all = [article("hotels", "travel", "2026-10-20"), article("stations", "travel", "2026-10-10"), article("snow", "land", "2026-11-01")];
  const mentions: Mentions = new Map([
    ["hotels", [row("muni-20485", 1, "旅館・ホテルの数が多い市区町村（2021年）"), row("muni-20485", 4, "宿泊業で働く人の割合（2021年）"),
      row("muni-20485", 1, "旅館・ホテルの数が多い市区町村（2021年）"), row("pref-20", 2, "旅館・ホテルの数が多い都道府県（2021年）")]],
    ["stations", [row("muni-20485", 6, "乗降客数が増えた駅", "白馬"), row("muni-20485", 9, "乗降客数が増えた駅", "信濃森上"), row("muni-13101", 2, "乗降客数が増えた駅", "東京")]],
    ["snow", [row("muni-20485", 3, "雪の深い観測所", "白馬"), row("muni-15222", 1, "雪の深い観測所", "高田")]],
  ]);

  it("市区町村: 出てくる記事を、順位の高い順に（同じ表は1回だけ、駅・観測所は別々に）", () => {
    const result = articlesForArea("muni-20485", all, mentions);
    expect(result.map((r) => r.article.slug)).toEqual(["hotels", "snow", "stations"]);
    expect(result[0].tables.map((t) => [captionLabel(t.caption), t.rank])).toEqual([["旅館・ホテルの数が多い市区町村", 1], ["宿泊業で働く人の割合", 4]]);
    expect(result[2].tables.map((t) => t.via)).toEqual(["白馬", "信濃森上"]);
    expect(articlesForArea("muni-99999", all, mentions)).toEqual([]);
  });

  it("都道府県: 都道府県の表と、その都道府県の市区町村が出てくる記事", () => {
    const result = articlesForPrefecture("20", all, mentions);
    expect(result.map((r) => r.article.slug)).toEqual(["hotels", "snow", "stations"]);
    expect(result[0].tables.map((t) => t.id)).toEqual(["pref-20"]);
    expect(result[0].municipalities).toEqual([{ id: "muni-20485", rank: 1 }]);
    expect(result[2].municipalities).toEqual([{ id: "muni-20485", rank: 6 }]);
    expect(articlesForPrefecture("13", all, mentions).map((r) => r.article.slug)).toEqual(["stations"]);
    expect(articlesForPrefecture("47", all, mentions)).toEqual([]);
  });
});

describe("一覧の検索（#232）", () => {
  const all = [
    article("hotels", "travel", "2026-10-20", { title: "旅館・ホテルが最も多い村", description: "宿の数を比べます。", indicators: ["lodging"] }),
    article("pop", "population", "2026-10-10", { title: "人口が増え続けるまちはどこ？", description: "国勢調査の人口の伸びを見ます。", indicators: ["population_total"] }),
    article("snow", "land", "2026-11-01", { title: "雪が1年に17m降る場所", description: "長野県の話も少し出ます。" }),
  ];
  const mentions: Mentions = new Map([
    ["hotels", [row("muni-20485", 1, "表"), row("muni-14382", 2, "表"), row("pref-01", 1, "都道府県の表")]],
    ["pop", [row("muni-12220", 1, "表"), row("muni-20321", 8, "表")]],
    ["snow", [row("muni-02201", 1, "表", "酸ケ湯")]],
  ]);
  const data = articleSearchData(all, mentions, {
    indicators: [{ id: "lodging", name: "旅館・ホテルの数" }, { id: "population_total", name: "人口" }],
    municipalities: [
      { id: "muni-20485", name: "白馬村", prefecture: "20" }, { id: "muni-14382", name: "箱根町", prefecture: "14" },
      { id: "muni-12220", name: "流山市", prefecture: "12" }, { id: "muni-20321", name: "軽井沢町", prefecture: "20" },
      { id: "muni-02201", name: "青森市", prefecture: "02" },
    ],
    prefectures: [{ code: "01", name: "北海道" }, { code: "02", name: "青森県" }, { code: "12", name: "千葉県" }, { code: "14", name: "神奈川県" }, { code: "20", name: "長野県" }],
  });
  const themes: Record<string, string> = { travel: "観光と交通", population: "人口", land: "地形と自然" };
  const search = new ArticleSearch(all.map((a) => ({ slug: a.slug, title: a.title, description: a.description, theme: themes[a.theme] })), data);
  const slugs = (q: string) => search.search(q).map((h) => h.slug);

  it("記事ごとに、指標の名前と表に出てくる地域をまとめる", () => {
    expect(data.hotels).toEqual({ indicators: ["旅館・ホテルの数"], areas: [["白馬村", "長野県"], ["箱根町", "神奈川県"]], prefectures: ["北海道"] });
    expect(data.snow.areas).toEqual([["青森市", "青森県"]]);
  });

  it("題名・指標の名前・読み・テーマで探せる", () => {
    expect(slugs("ホテル")).toEqual(["hotels"]);
    expect(slugs("じんこう")).toEqual(["pop"]);
    expect(slugs("観光")).toEqual(["hotels"]);
    expect(slugs("雪")).toEqual(["snow"]);
  });

  it("表に出てくる市区町村・都道府県の名前で探せる（説明文だけに出てくる記事は出さない）", () => {
    expect(search.search("白馬")).toEqual([{ slug: "hotels", areas: ["白馬村"] }]);
    expect(search.search("長野県")).toEqual([{ slug: "hotels", areas: ["白馬村"] }, { slug: "pop", areas: ["軽井沢町"] }]);
    expect(search.search("北海道")).toEqual([{ slug: "hotels", areas: ["北海道"] }]);
    expect(slugs("どこにもない言葉")).toEqual([]);
  });

  it("当たった地域の名前を、カードに出す一言にする", () => {
    expect(matchedAreas(data.hotels, "箱根 白馬")).toEqual(["白馬村", "箱根町"]);
    expect(matchedAreas(data.hotels, "村")).toEqual([]);
    expect(hitLabel(["白馬村", "小谷村"])).toBe("登場: 白馬村・小谷村");
    expect(hitLabel(["a", "b", "c", "d", "e"])).toBe("登場: a・b・c ほか2");
    expect(hitLabel([])).toBe("");
  });
});
