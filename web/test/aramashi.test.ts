import { describe, expect, it } from "vitest";
import { allAramashi, checkedLabel } from "../src/lib/aramashi";

describe("あらまし（設計変更記録 #164）", () => {
  const all = allAramashi();

  it("地域の id・確かめた日・出典がそろっている", () => {
    expect(all.length).toBeGreaterThan(0);
    for (const [id, a] of all) {
      expect(id).toMatch(/^(muni-\d{5}|pref-\d{2})$/);
      expect(a.checked).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(a.sources.length).toBeGreaterThan(0);
      for (const s of a.sources) {
        expect(s.url).toMatch(/^https:\/\//);
        expect(s.publisher).not.toBe("");
        expect(s.title).not.toBe("");
      }
    }
  });

  it("3〜5文の事実だけを書き、推測の言い方を使わない", () => {
    for (const [id, a] of all) {
      const sentences = a.text.join("").split("。").filter(Boolean).length;
      expect(sentences, id).toBeGreaterThanOrEqual(3);
      expect(sentences, id).toBeLessThanOrEqual(5);
      for (const t of a.text) {
        expect(t, id).toMatch(/。$/);
        expect(t, id).not.toMatch(/思われます|考えられます|ようです|かもしれません/);
      }
      expect(a.text.join("").length, id).toBeLessThanOrEqual(320);
    }
  });

  it("確かめた日を年月日で書く", () => {
    expect(checkedLabel("2026-10-24")).toBe("2026年10月24日");
  });
});
