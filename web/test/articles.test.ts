import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { about, man } from "../src/lib/articleData";
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

describe("寄り道の本文の決まり（設計変更記録 #236）", () => {
  const source = (slug: string) => readFileSync(join(__dirname, "../src/articles", `${slug}.astro`), "utf8");

  it("大きな数は「万」「億」で区切って書く", () => {
    expect(man(4575)).toBe("4,575");
    expect(man(66680)).toBe("6万6,680");
    expect(man(1170000)).toBe("117万");
    expect(man(122972528)).toBe("1億2,297万2,528");
    expect(man(null)).toBe("—");
    expect(about(1172345)).toBe("約117万");
    expect(about(19876)).toBe("約1万9,900");
    expect(about(189234, 1000)).toBe("約18万9,000");
    expect(about(null)).toBe("—");
  });

  it("「読むときの注意」は本文のいちばん後ろの見出しにする", () => {
    for (const a of ARTICLES) {
      const headings = [...source(a.slug).matchAll(/<h2[^>]*>(.*?)<\/h2>/g)].map((m) => m[1]);
      const notes = headings.indexOf("読むときの注意");
      if (notes < 0) continue;
      // 後ろに置いてよいのは、広告のリンクの見出しだけ（設計変更記録 #189）
      expect(headings.slice(notes + 1).filter((h) => h !== "返礼品を探す"), a.slug).toEqual([]);
      // 注意の前に、結びの見出しがある
      expect(notes, a.slug).toBeGreaterThanOrEqual(2);
    }
  });

  it("考察の語尾に「かもしれません」を使わない", () => {
    for (const a of ARTICLES) expect(source(a.slug).includes("かもしれません"), a.slug).toBe(false);
  });

  it("ほかの寄り道への案内は、ある記事を指し、自分自身を指さない", () => {
    const slugs = new Set(ARTICLES.map((a) => a.slug));
    for (const a of ARTICLES) {
      for (const m of source(a.slug).matchAll(/<ArticleLink slug="([^"]+)"/g)) {
        expect(slugs.has(m[1]), `${a.slug} → ${m[1]}`).toBe(true);
        expect(m[1], a.slug).not.toBe(a.slug);
      }
    }
  });
});
