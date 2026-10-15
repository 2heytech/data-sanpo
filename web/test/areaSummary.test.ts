import { describe, expect, it } from "vitest";
import { areaSummary, type SummaryStat } from "../src/lib/areaSummary";
import type { Indicator } from "../src/lib/types";

const ind = (id: string, name: string, kind: Indicator["kind"], unit = "%", family: string | null = null) =>
  ({ id, name, kind, unit, digits: kind === "count" ? 0 : 1, family, legend: { method: "quantile", classes: 7, scheme: "blues" } }) as Indicator;
const stat = (i: Indicator, value: number | null, prefRank: [number, number] | null, natRank: [number, number] | null): SummaryStat => ({
  ind: i, periodLabel: "2020年", row: { entity_id: "muni-13101", value, status: value === null ? "missing" : "observed" },
  ranks: [prefRank && { rank: prefRank[0], total: prefRank[1] }, natRank && { rank: natRank[0], total: natRank[1] }],
});

describe("areaSummary", () => {
  it("人口と都道府県内の順位を文章にする", () => {
    const lines = areaSummary("サンプル市", "東京都", [
      stat(ind("population_total", "人口", "count", "人"), 12345, [3, 62], [100, 1900]),
      stat(ind("population_change_rate", "人口増加率", "change"), -2.5, null, null),
      stat(ind("a", "Aの割合", "ratio"), 40, null, [2, 1900]),
      stat(ind("b", "得票率（甲党）", "ratio", "%", "vote"), 30, null, [1, 1900]),
      stat(ind("c", "得票率（乙党）", "ratio", "%", "vote"), 30, null, [3, 1900]),
      stat(ind("d", "Dの割合", "ratio"), 1, null, [1890, 1900]),
      stat(ind("e", "Eの件数", "count", "件"), 999, null, [1, 1900]),
    ]);
    expect(lines[0]).toBe("サンプル市の人口は12,345 人（2020年）で、東京都の62市区町村のうち3番目に多い市区町村です。");
    // 増減・全国順位で目立つ指標は areaInsights で書く
    expect(lines).toHaveLength(1);
  });
  it("値がない指標は文章にしない（0 として扱わない）", () => {
    expect(areaSummary("サンプル市", "東京都", [stat(ind("population_total", "人口", "count", "人"), null, null, null)])).toEqual([]);
  });
});
