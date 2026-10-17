import { describe, expect, it } from "vitest";
import { breakText, layoutTitle, textWidth } from "../src/lib/mapImage";
import { MIN_SMALL_AREAS, topSmallAreas } from "../src/lib/smallAreaRanking";
import type { ValueRow } from "../src/lib/types";

describe("地図の画像の題名", () => {
  it("「：」で改行し、収まる中でいちばん大きな文字にする", () => {
    const t = layoutTitle("東京都の市区町村別：人口増加率（2020→2025年）");
    expect(t.lines).toEqual(["東京都の市区町村別", "人口増加率（2020→2025年）"]);
    expect(t.size).toBeGreaterThanOrEqual(36);
    for (const l of t.lines) expect(textWidth(l, t.size)).toBeLessThanOrEqual(536);
  });
  it("長い題名は「、」「・」「（」などの区切りで折り返し、言葉の途中では切らない", () => {
    const t = layoutTitle("人口が増えた市区町村・減った市区町村（2025年国勢調査）");
    expect(t.lines.join("")).toBe("人口が増えた市区町村・減った市区町村（2025年国勢調査）");
    expect(t.lines.length).toBeLessThanOrEqual(3);
    for (const l of t.lines) expect(["人口が増えた市区町村・", "減った市区町村", "（2025年国勢調査）", "減った市区町村（2025年国勢調査）", "人口が増えた市区町村・減った市区町村"]).toContain(l);
  });
  it("区切りで収まらない文は文字で折り返し、行が多すぎるときは「…」で切る", () => {
    expect(breakText("あ".repeat(30), 20, 200, 2)).toEqual(["あ".repeat(10), `${"あ".repeat(9)}…`]);
    expect(breakText("全国の市区町村別の人口（2020年）", 22, 536, 2)).toEqual(["全国の市区町村別の人口（2020年）"]);
  });
});

describe("町丁目別ランキング", () => {
  const rows = (values: (number | null)[]): ValueRow[] =>
    values.map((v, i) => ({ entity_id: `area-131120${String(i).padStart(5, "0")}`, value: v, status: v === null ? "missing" : "observed" }));
  it("値のある町丁目が少ない市区町村では出さない", () => {
    expect(topSmallAreas(rows(Array.from({ length: MIN_SMALL_AREAS - 1 }, (_, i) => i)))).toEqual([]);
    expect(topSmallAreas(rows([...Array.from({ length: MIN_SMALL_AREAS - 1 }, (_, i) => i), null, null]))).toEqual([]);
  });
  it("20以上なら10位まで、それより少なければ5位まで。同じ値は同じ順位", () => {
    expect(topSmallAreas(rows(Array.from({ length: 25 }, (_, i) => i))).map((r) => r.rank)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    const few = topSmallAreas(rows([5, 9, 9, 1, 2, 3, 4, 8, 7]));
    expect(few.map((r) => [r.value, r.rank])).toEqual([[9, 1], [9, 1], [8, 3], [7, 4], [5, 5]]);
  });
  it("増えた町丁目の表は0より大きい値だけで、3つ未満なら出さない", () => {
    const r = topSmallAreas(rows([-5, -3, 2, 0, -1, 4, -2, -8, 1]), true);
    expect(r.map((x) => x.value)).toEqual([4, 2, 1]);
    expect(topSmallAreas(rows([-5, -3, 2, 0, -1, 4, -2, -8, -1]), true)).toEqual([]);
  });
});
