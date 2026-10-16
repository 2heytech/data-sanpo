import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ARTICLES, formatDate } from "../src/lib/articles";

describe("寄り道の一覧", () => {
  it("slug が重ならず、それぞれのページがある", () => {
    expect(new Set(ARTICLES.map((a) => a.slug)).size).toBe(ARTICLES.length);
    for (const a of ARTICLES) {
      expect(existsSync(join(__dirname, "../src/pages/articles", `${a.slug}.astro`)), a.slug).toBe(true);
    }
  });

  it("日付は YYYY-MM-DD で、説明文は検索結果で切れにくい長さ", () => {
    for (const a of ARTICLES) {
      expect(a.published).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(a.description.length, a.slug).toBeLessThanOrEqual(120);
    }
  });

  it("日付を日本語で書く", () => {
    expect(formatDate("2026-10-06")).toBe("2026年10月6日");
  });
});
