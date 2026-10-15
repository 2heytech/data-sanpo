import { describe, expect, it } from "vitest";
import { areaInsights, type InsightData } from "../src/lib/areaInsights";
import { RANK_TEMPLATES } from "../src/lib/rankInsights";
import type { Indicator, ValueRow } from "../src/lib/types";

const ind = (id: string, unit: string, digits: number, periods: string[], kind: Indicator["kind"] = "ratio") => ({
  id, name: id, unit, digits, kind, default_period: periods[periods.length - 1],
  periods: periods.map((p) => ({ period: p, label: `${p.slice(0, 4)}年${Number(p.slice(5, 7))}月1日現在` })),
}) as unknown as Indicator;

// 2つの都道府県の市区町村 20 個。対象は muni-01001
function makeData(values: Record<string, Record<string, (number | null)[]>>): InsightData {
  const inds = new Map<string, Indicator>([
    ["foreign_resident_share", ind("foreign_resident_share", "%", 1, ["2025-10-01"])],
    ["foreign_residents_share", ind("foreign_residents_share", "%", 1, ["2026-01-01"])],
    ["census_foreign_population", ind("census_foreign_population", "人", 0, ["2025-10-01"], "count")],
    ["foreign_residents", ind("foreign_residents", "人", 0, ["2026-01-01"], "count")],
    ["daytime_night_ratio", ind("daytime_night_ratio", "%", 1, ["2020-10-01"])],
    ["population_change_rate", ind("population_change_rate", "%", 1, ["2020-10-01"], "change")],
    ["commute_bicycle_share", ind("commute_bicycle_share", "%", 1, ["2020-10-01"])],
    ["census_foreign_nepal_share", { ...ind("census_foreign_nepal_share", "%", 1, ["2020-10-01"]), name: "国勢調査の外国人の割合（ネパール）" } as Indicator],
    ["census_foreign_nepal", ind("census_foreign_nepal", "人", 0, ["2020-10-01"], "count")],
    ["street_crime_total_per_100_residents", ind("street_crime_total_per_100_residents", "件/100人", 2, ["2020-10-01"])],
  ]);
  const ids = Array.from({ length: 200 }, (_, i) => `muni-${i < 10 ? "01" : "02"}${String(i + 1).padStart(3, "0")}`);
  return {
    indicator: (id) => inds.get(id),
    indicators: () => [...inds.values()],
    rows: (id, period) => {
      const v = values[id]?.[period ?? inds.get(id)!.default_period];
      return v ? ids.map((e, i): ValueRow => ({ entity_id: e, value: v[i] ?? null, status: v[i] === null ? "missing" : "observed" })) : [];
    },
  };
}
const fill = (first: number | null, rest = 10) => [first, ...Array(199).fill(rest)];

describe("areaInsights", () => {
  it("住民基本台帳（1月）の外国人の割合が国勢調査（10月）よりかなり大きいと、季節的に働く人が多いと考えられると書く", () => {
    const lines = areaInsights("muni-01001", makeData({
      foreign_resident_share: { "2025-10-01": fill(21.6, 2) },
      foreign_residents_share: { "2026-01-01": fill(35.5, 2) },
      census_foreign_population: { "2025-10-01": fill(321) },
      foreign_residents: { "2026-01-01": fill(541) },
    }));
    expect(lines[0]).toContain("住民基本台帳（2026年1月1日現在）では35.5%、国勢調査（2025年10月1日現在）では21.6%");
    expect(lines[0]).toContain("考えられます");
  });
  it("外国人が少ない地域や差が小さい地域では書かない", () => {
    const few = makeData({
      foreign_resident_share: { "2025-10-01": fill(10) }, foreign_residents_share: { "2026-01-01": fill(30) },
      census_foreign_population: { "2025-10-01": fill(5) }, foreign_residents: { "2026-01-01": fill(15) },
    });
    expect(areaInsights("muni-01001", few)).toEqual([]);
    const close = makeData({
      foreign_resident_share: { "2025-10-01": fill(10, 10) }, foreign_residents_share: { "2026-01-01": fill(11, 11) },
      census_foreign_population: { "2025-10-01": fill(300) }, foreign_residents: { "2026-01-01": fill(330) },
    });
    expect(areaInsights("muni-01001", close)).toEqual([]);
  });
  it("昼夜間人口比率と人口の増減は、決まった条件のときだけ推測の文にする", () => {
    const lines = areaInsights("muni-01001", makeData({
      daytime_night_ratio: { "2020-10-01": fill(150, 100) },
      population_change_rate: { "2020-10-01": fill(-12, -2) },
    }));
    expect(lines).toEqual([
      "昼間の人口は住んでいる人の1.5倍です（2020年10月1日現在）。周りから通勤・通学で人が集まる、職場や学校の多いまちと思われます。",
      "人口は5年前から12.0%減っていて（2020年10月1日現在）、全国の市区町村の中でも減り方が大きい方です。若い世代の転出や高齢化が進んでいると思われます。",
    ]);
  });
  it("全国順位が特に高い指標に、指標ごとの考察を付ける（人数が少ない国籍は除く）", () => {
    const lines = areaInsights("muni-01001", makeData({
      commute_bicycle_share: { "2020-10-01": fill(40, 10) },
      census_foreign_nepal_share: { "2020-10-01": fill(3, 0.1) },
      census_foreign_nepal: { "2020-10-01": fill(10, 1) },
    }));
    expect(lines).toEqual([
      "commute_bicycle_shareは40.0%で、全国200市区町村のうち1位です（2020年10月1日現在）。平らな土地が多く、自転車で通勤・通学しやすいまちと考えられます。",
    ]);
  });
  it("課題に当たる文だけのときは、良いところを1つ足す（言い過ぎないよう順位だけ）", () => {
    // 犯罪の件数が少ない方から 61 番目（下位約3割）
    const crime = [5, ...Array.from({ length: 199 }, (_, i) => (i < 60 ? 1 : 10))];
    const lines = areaInsights("muni-01001", makeData({
      population_change_rate: { "2020-10-01": fill(-12, -2) },
      street_crime_total_per_100_residents: { "2020-10-01": crime },
    }));
    expect(lines).toEqual([
      "人口は5年前から12.0%減っていて（2020年10月1日現在）、全国の市区町村の中でも減り方が大きい方です。若い世代の転出や高齢化が進んでいると思われます。",
      "street_crime_total_per_100_residentsは5.00 件/100人で、全国200市区町村の中で低い方から61番目です（2020年10月1日現在）。全国の中では小さい方の半分に入ります。",
    ]);
  });
  it("地域や住む人を悪く言うように読める考察は作らない", () => {
    for (const [id, t] of Object.entries(RANK_TEMPLATES)) {
      if (id.startsWith("street_crime_")) expect(t.high, id).toBeUndefined();
    }
    for (const id of ["taxable_income_per_taxpayer", "income_levy_taxpayer_share", "university_graduate_share", "life_expectancy_male", "life_expectancy_female"]) {
      expect(RANK_TEMPLATES[id].low, id).toBeUndefined();
    }
  });
  it("「かもしれません」は使わない", () => {
    const src = areaInsights.toString();
    expect(src).not.toContain("かもしれません");
  });
  it("値がない指標は使わない（0 として扱わない）", () => {
    expect(areaInsights("muni-01001", makeData({ daytime_night_ratio: { "2020-10-01": fill(null, 100) } }))).toEqual([]);
  });
});
