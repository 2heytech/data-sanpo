import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ARTICLES, articlesAsOf, formatDate, publishedArticles } from "../src/lib/articles";

describe("寄り道の一覧", () => {
  it("slug が重ならず、それぞれの本文がある", () => {
    expect(new Set(ARTICLES.map((a) => a.slug)).size).toBe(ARTICLES.length);
    for (const a of ARTICLES) {
      expect(existsSync(join(__dirname, "../src/articles", `${a.slug}.astro`)), a.slug).toBe(true);
    }
  });

  it("日付は YYYY-MM-DD で、説明文は検索結果で切れにくい長さ", () => {
    for (const a of ARTICLES) {
      expect(a.published).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(a.description.length, a.slug).toBeLessThanOrEqual(120);
    }
  });

  it("公開日が来た記事だけを出す（日付は日本時間で判断する）", () => {
    const first = [...ARTICLES].sort((a, b) => a.published.localeCompare(b.published))[0];
    expect(publishedArticles("2000-01-01")).toEqual([]);
    expect(publishedArticles(first.published).map((a) => a.slug)).toContain(first.slug);
    expect(publishedArticles("2999-12-31")).toEqual(ARTICLES);
    // 2026-10-22 22:30 UTC は日本時間で 2026-10-23 7:30
    const prev = process.env.ARTICLES_AS_OF;
    delete process.env.ARTICLES_AS_OF;
    expect(articlesAsOf(new Date("2026-10-22T22:30:00Z"))).toBe("2026-10-23");
    expect(articlesAsOf(new Date("2026-10-22T14:59:00Z"))).toBe("2026-10-22");
    process.env.ARTICLES_AS_OF = "2026-10-30";
    expect(articlesAsOf(new Date("2026-10-22T14:59:00Z"))).toBe("2026-10-30");
    if (prev === undefined) delete process.env.ARTICLES_AS_OF; else process.env.ARTICLES_AS_OF = prev;
  });

  it("日付を日本語で書く", () => {
    expect(formatDate("2026-10-06")).toBe("2026年10月6日");
  });
});
