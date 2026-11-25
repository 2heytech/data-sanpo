import { afterEach, describe, expect, it } from "vitest";
import { clip, track } from "../src/lib/track";

// 画面の操作を Google アナリティクスのイベントとして送る（設計変更記録 #255）
describe("Google アナリティクスのイベント", () => {
  const g = globalThis as unknown as { window?: { gtag?: (...args: unknown[]) => void } };
  afterEach(() => {
    delete g.window;
  });

  it("gtag があればイベントとして渡す", () => {
    const calls: unknown[][] = [];
    g.window = { gtag: (...args) => void calls.push(args) };
    track("select_indicator", { indicator_id: "population_total", method: "switch" });
    expect(calls).toEqual([["event", "select_indicator", { indicator_id: "population_total", method: "switch" }]]);
  });

  it("gtag がない（測定 ID のない版・公開サイト以外）ときや、gtag が失敗したときは何もしない", () => {
    expect(() => track("share", { method: "link_copy" })).not.toThrow();
    g.window = {};
    expect(() => track("share", { method: "link_copy" })).not.toThrow();
    g.window = { gtag: () => { throw new Error("blocked"); } };
    expect(() => track("share", { method: "link_copy" })).not.toThrow();
  });

  it("値は空白をまとめ、100文字までにする", () => {
    expect(clip("  楽天ふるさと納税で\n  返礼品を見る ")).toBe("楽天ふるさと納税で 返礼品を見る");
    expect(clip("あ".repeat(150))).toHaveLength(100);
  });
});
