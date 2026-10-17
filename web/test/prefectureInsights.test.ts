import { describe, expect, it } from "vitest";
import { prefectureProfile, type PrefInsightData } from "../src/lib/prefectureInsights";
import type { Indicator, ValueRow } from "../src/lib/types";

const ind = (id: string, unit: string, digits: number, period: string, over: Partial<Indicator> = {}) => ({
  id, name: id, unit, digits, kind: "ratio", category: "", default_period: period,
  periods: [{ period, label: `${period.slice(0, 4)}年`, levels: ["municipality", "prefecture"], source_ids: ["census_2020"] }], ...over,
}) as unknown as Indicator;

// 47都道府県（pref-01〜pref-47）の値。値の並びは都道府県コードの順で、null は値なし
const codes = Array.from({ length: 47 }, (_, i) => String(i + 1).padStart(2, "0"));
const spread = (over: Record<number, number | null> = {}, base = (i: number) => 10 + i) => codes.map((_, i) => (i + 1 in over ? over[i + 1] : base(i)));

function makeData(values: Record<string, (number | null)[]>, extra: Indicator[] = []): PrefInsightData {
  const inds = new Map<string, Indicator>([
    ["area", ind("area", "km²", 2, "2025-10-01", { kind: "count" })],
    ["population_change_rate", ind("population_change_rate", "%", 1, "2025-10-01", { kind: "change" })],
    ["crime_npa_total_per_100_residents", ind("crime_npa_total_per_100_residents", "件/100人", 2, "2025-01-01", { name: "全国の犯罪の認知件数（住民100人当たり）", category: "犯罪" })],
    ["vote_share_sdp", ind("vote_share_sdp", "%", 1, "2026-02-08", { name: "比例代表の得票率（社会民主党）", category: "選挙", family: "vote_share" })],
    ["census_foreign_nepal_share", ind("census_foreign_nepal_share", "%", 2, "2025-10-01", { name: "国勢調査の外国人の割合（ネパール）", category: "外国人住民" })],
    ["life_expectancy_female", ind("life_expectancy_female", "年", 1, "2020-01-01", { name: "平均寿命（女性）" })],
    ...extra.map((i) => [i.id, i] as [string, Indicator]),
  ]);
  return {
    indicator: (id) => inds.get(id),
    indicators: () => [...inds.values()],
    rows: (id) => (values[id] ?? []).map((v, i): ValueRow => ({ entity_id: `pref-${codes[i]}`, value: v, status: v === null ? "missing" : "observed" })),
  };
}

describe("prefectureProfile", () => {
  it("全国で最も広い都道府県は、日本の面積に占める割合とともに書き、題名に使う", () => {
    const p = prefectureProfile("01", "北海道", makeData({ area: spread({ 1: 1000 }) }));
    expect(p.lines[0]).toMatch(/^面積は1,000\.00 km²で、全国の都道府県で最も広く、日本の面積の約\d+%を占めます（2025年）。$/);
    expect(p.title).toBe("面積の広い北海道");
  });

  it("人口が増えたのが1つだけなら、そのことを書く", () => {
    const p = prefectureProfile("13", "東京都", makeData({ population_change_rate: spread({ 13: 1.4 }, (i) => -1 - i / 10) }));
    expect(p.lines.join("")).toContain("全国の都道府県で人口が増えたのは東京都だけです。");
  });

  it("犯罪が少ない方は、指標の名前を言い換えて書く。多い方は書かない", () => {
    const few = prefectureProfile("05", "秋田県", makeData({ crime_npa_total_per_100_residents: spread({ 5: 0.1 }, (i) => 0.5 + i / 100) }));
    expect(few.lines.join("")).toContain("住民100人当たりの犯罪の認知件数は0.10 件/100人で、全国47都道府県の中で最も低い値です");
    expect(few.title).toBe("落ち着いた秋田県");
    const many = prefectureProfile("13", "東京都", makeData({ crime_npa_total_per_100_residents: spread({ 13: 2 }, (i) => 0.5 + i / 100) }));
    expect(many.lines.join("")).not.toContain("犯罪");
  });

  it("値のない都道府県があるときは、値のある数で数えたことを書く", () => {
    const p = prefectureProfile("05", "秋田県", makeData({ crime_npa_total_per_100_residents: spread({ 5: 0.1, 22: null }, (i) => 0.5 + i / 100) }));
    expect(p.lines.join("")).toContain("値のある全国46都道府県の中で最も低い値です");
  });

  it("同じ値の都道府県が3つまでなら順位を書き、その数を添える", () => {
    const p = prefectureProfile("33", "岡山県", makeData({ life_expectancy_female: spread({ 25: 88.3, 26: 88.3, 33: 88.3 }, (i) => 86 + i / 100) }));
    expect(p.lines.join("")).toContain("全国47都道府県のうち1位です（2020年、3都道府県が同じ値）");
  });

  it("選挙の文は最後に置き、題名にしない。国籍の文は割合がごく小さければ書かない", () => {
    const p = prefectureProfile("47", "沖縄県", makeData({
      area: spread({ 47: 1 }), vote_share_sdp: spread({ 47: 99 }), census_foreign_nepal_share: spread({ 47: 0.05 }, () => 0.01),
    }));
    expect(p.groups.at(-1)?.theme).toBe("選挙");
    expect(p.groups[0].theme).not.toBe("選挙");
    expect(p.title).not.toContain("支持");
    expect(p.lines.join("")).not.toContain("ネパール");
  });

  it("考察がないときは題名も出さない", () => {
    const p = prefectureProfile("20", "長野県", makeData({ area: spread() }));
    expect(p.lines).toEqual([]);
    expect(p.title).toBeNull();
  });
});
