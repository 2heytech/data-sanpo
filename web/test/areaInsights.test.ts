import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { areaInsights, areaProfile, type InsightData } from "../src/lib/areaInsights";
import type { PlacePoints } from "../src/lib/placeStats";
import { RANK_TEMPLATES } from "../src/lib/rankInsights";
import type { Indicator, ValueRow } from "../src/lib/types";

const ind = (id: string, unit: string, digits: number, periods: string[], kind: Indicator["kind"] = "ratio") => ({
  id, name: id, unit, digits, kind, default_period: periods[periods.length - 1],
  periods: periods.map((p) => ({ period: p, label: `${p.slice(0, 4)}年${Number(p.slice(5, 7))}月1日現在` })),
}) as unknown as Indicator;

// 2つの都道府県の市区町村 20 個。対象は muni-01001
function makeData(values: Record<string, Record<string, (number | null)[]>>, places?: PlacePoints): InsightData {
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
    ["vacant_house_rate", ind("vacant_house_rate", "%", 1, ["2023-10-01"])],
    ["vote_share_sdp", { ...ind("vote_share_sdp", "%", 1, ["2020-10-01"]), category: "選挙", family: "vote_share" } as Indicator],
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
    places: () => places ?? null,
  };
}
// 点のデータ（駅・空港・港・地価公示・天気）。指定しないものは空
const places = (over: Partial<PlacePoints>): PlacePoints => ({
  stations: [], stationPeriods: [], land: [], landPeriods: [], airports: [], airportPeriods: [], ports: [], portPeriods: [],
  weather: [], weatherLabel: "1991〜2020年の平年値", centers: new Map(), ...over,
});
const others = (n: number) => Array.from({ length: n }, (_, i) => `muni-02${String(i + 1).padStart(3, "0")}`);
const fill = (first: number | null, rest = 10) => [first, ...Array(199).fill(rest)];

describe("areaInsights", () => {
  it("住民基本台帳（1月）の外国人の割合が国勢調査（10月）よりかなり大きいと、雪の多い地域では冬に働きに来る人が多いと考えられると書く", () => {
    const values = {
      foreign_resident_share: { "2025-10-01": fill(21.6, 2) },
      foreign_residents_share: { "2026-01-01": fill(35.5, 2) },
      census_foreign_population: { "2025-10-01": fill(321) },
      foreign_residents: { "2026-01-01": fill(541) },
    };
    const snowy = places({ weather: [{ name: "占冠", municipality_id: "muni-01001", coord: [142.4, 43.0], values: { snowfall_normal: 600 } }] });
    const lines = areaInsights("muni-01001", makeData(values, snowy));
    expect(lines[0]).toContain("住民基本台帳（2026年1月1日現在）では35.5%、国勢調査（2025年10月1日現在）では21.6%");
    expect(lines[0]).toContain("冬の観光や農作業など、季節的に働きに来る外国人が多いと考えられます");
    // 雪の少ない地域では冬と結びつけない
    const other = areaProfile("muni-01001", makeData(values));
    expect(other.lines[0]).not.toContain("冬");
    expect(other.title).toBeNull();
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
  it("課題に当たる文だけのときは、良いところを1つ足し、先に読めるようにする（言い過ぎないよう順位だけ）", () => {
    // 犯罪の件数が少ない方から 61 番目（下位約3割）
    const crime = [5, ...Array.from({ length: 199 }, (_, i) => (i < 60 ? 1 : 10))];
    const lines = areaInsights("muni-01001", makeData({
      population_change_rate: { "2020-10-01": fill(-12, -2) },
      street_crime_total_per_100_residents: { "2020-10-01": crime },
    }));
    expect(lines).toEqual([
      "street_crime_total_per_100_residentsは5.00 件/100人で、全国200市区町村の中で低い方から61番目です（2020年10月1日現在）。全国の中では小さい方の半分に入ります。",
      "人口は5年前から12.0%減っていて（2020年10月1日現在）、全国の市区町村の中でも減り方が大きい方です。若い世代の転出や高齢化が進んでいると思われます。",
    ]);
  });
  it("空き家率が高くても人口が減っていない地域は、別荘や賃貸用の住宅が多いと書く（空き家には別荘も含むため）", () => {
    const lines = areaInsights("muni-01001", makeData({
      vacant_house_rate: { "2023-10-01": fill(70, 10) },
      population_change_rate: { "2020-10-01": fill(3, -2) },
    }));
    expect(lines.find((l) => l.startsWith("空き家率"))).toBe(
      "空き家率が70.0%と全国でも高い方です（2023年10月1日現在）。人口は減っていないので、別荘や入居者を募集中の賃貸住宅など、ふだん人が住んでいない住宅が多いと考えられます。");
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
    for (const f of ["areaInsights.ts", "rankInsights.ts", "placeStats.ts"]) {
      expect(readFileSync(new URL(`../src/lib/${f}`, import.meta.url), "utf-8"), f).not.toContain("かもしれません");
    }
  });
  it("値がない指標は使わない（0 として扱わない）", () => {
    expect(areaInsights("muni-01001", makeData({ daytime_night_ratio: { "2020-10-01": fill(null, 100) } }))).toEqual([]);
  });
});

describe("点のデータ（空港・天気・地価公示）の考察", () => {
  it("空港の利用者数と国際線の割合から書く", () => {
    const pts = places({
      airportPeriods: ["2024年", "2025年"],
      airports: [
        { name: "新千歳", municipality_id: "muni-01001", values: [2_000_000, 2_500_000], international: [0, 600_000] },
        ...others(9).map((m) => ({ name: m, municipality_id: m, values: [10_000, 10_000] })),
      ],
    });
    expect(areaInsights("muni-01001", makeData({}, pts))).toEqual([
      "まちには新千歳空港があり、2025年は約250万人が飛行機に乗り降りしました。国際線の利用も多く、海外との行き来の玄関口にもなっているようです。",
    ]);
  });
  it("値のない空港は使わない（0 人として扱わない）", () => {
    const pts = places({ airportPeriods: ["2024年", "2025年"], airports: [{ name: "どこか", municipality_id: "muni-01001", values: [null, null] }] });
    expect(areaInsights("muni-01001", makeData({}, pts))).toEqual([]);
  });
  it("天気は市区町村の代表点に近い観測所の平年値で、全国の観測所の中で目立つときに書く", () => {
    const pts = places({
      centers: new Map([["muni-01001", [141, 43]]]),
      weather: [
        { name: "遠い", municipality_id: "muni-01001", coord: [141.5, 43.5], altitude_m: 10, values: { snowfall_normal: 800 } },
        { name: "近い", municipality_id: "muni-01001", coord: [141.01, 43.01], altitude_m: 650, values: { snowfall_normal: 600 } },
        ...others(8).map((m, i) => ({ name: m, municipality_id: m, coord: [130 + i, 33] as [number, number], altitude_m: 10, values: { snowfall_normal: 50 } })),
      ],
    });
    const p = areaProfile("muni-01001", makeData({}, pts));
    expect(p.lines).toEqual([
      "気象庁の観測所「近い」は標高650mにあり、高原や山あいのまちと考えられます。夏も比較的すずしい気候と思われます。",
      "年間の降雪量は600cm（気象庁の観測所「近い」、1991〜2020年の平年値）と、全国の観測所の中でも多い方です。冬は雪とともに暮らす、雪国のまちと考えられます。",
    ]);
    // 題名は、全国の中で目立つ考察から2つ選んでつなぐ（元になった考察を先頭に並べる）
    expect(p.title).toBe("標高が高く、雪の多いまち");
  });
  it("地価公示は住宅地の同じ地点の変化率の中央値で、上がり方が全国でも大きいときに書く", () => {
    const landPeriods = Array.from({ length: 6 }, (_, i) => `${2021 + i}年1月1日現在`);
    const pt = (m: string, from: number, to: number, use = "000") => ({ municipality_id: m, use, values: [from, 0, 0, 0, 0, to] });
    const pts = places({
      landPeriods,
      land: [pt("muni-01001", 100_000, 140_000), pt("muni-01001", 200_000, 260_000), pt("muni-01001", 50_000, 10_000, "005"),
        ...others(30).flatMap((m) => [pt(m, 100_000, 101_000), pt(m, 100_000, 102_000)])],
    });
    const p = areaProfile("muni-01001", makeData({}, pts));
    expect(p.lines).toEqual([
      "住宅地の地価公示の価格は、同じ地点で比べると2021年1月1日から35.0%上がっていて（2地点の中央値）、全国の市区町村の中でも上がり方が大きい方です。" +
        "住宅の開発や交通の便の向上などで、住まいとしての人気が高まっていると考えられます。",
    ]);
    expect(p.title).toBe("地価が上がっているまち");
  });
  it("地価公示の住宅地の地点がない市区町村は、都道府県地価調査の値を事実だけ書く（順位は付けない）", () => {
    const periods = Array.from({ length: 6 }, (_, i) => `${2020 + i}年7月1日現在`);
    const pts = places({
      landSurveyPeriods: periods,
      landSurvey: [{ municipality_id: "muni-01001", use: "000", values: [10_000, 0, 0, 0, 0, 9_000] },
        { municipality_id: "muni-01001", use: "000", values: [5_000, 0, 0, 0, 0, 4_000] }],
    });
    expect(areaInsights("muni-01001", makeData({}, pts))).toEqual([
      "住宅地の都道府県地価調査の価格は、まちの2地点の中央値で1㎡あたり6,500円です（2025年7月1日現在）。同じ地点で比べた2020年7月1日からの変化は-15.0%です。",
    ]);
  });
});

describe("考察の並び", () => {
  it("テーマごとにまとめ、題名の元になった考察のテーマを先に、選挙と課題に当たる文は後ろにする", () => {
    const p = areaProfile("muni-01001", makeData({
      vote_share_sdp: { "2020-10-01": fill(30, 1) },
      population_change_rate: { "2020-10-01": fill(-12, -2) },
      daytime_night_ratio: { "2020-10-01": fill(150, 100) },
    }, places({
      airportPeriods: ["2025年"],
      airports: [{ name: "どこか", municipality_id: "muni-01001", values: [50_000] }, ...others(9).map((m) => ({ name: m, municipality_id: m, values: [1_000_000] }))],
    })));
    expect(p.title).toBe("空港があり、周りから人が集まるまち");
    expect(p.groups.map((g) => g.theme)).toEqual(["交通", "仕事と産業", "住む人", "選挙"]);
    expect(p.lines).toEqual(p.groups.flatMap((g) => g.lines));
  });
  it("ほかの考察が少ないときは、どの地域にも出やすい考察（昼と夜の人口がほぼ同じなど）も出す", () => {
    const few = areaProfile("muni-01001", makeData({ daytime_night_ratio: { "2020-10-01": fill(100, 100) } }));
    expect(few.lines.join("")).toContain("昼と夜の人口がほぼ同じ");
  });
});

describe("題名（特徴を一言で表す文）", () => {
  it("全国順位が特に高い指標の言い回しから作る", () => {
    const p = areaProfile("muni-01001", makeData({ commute_bicycle_share: { "2020-10-01": fill(40, 10) } }));
    expect(p.title).toBe("自転車で暮らしやすいまち");
  });
  it("課題に当たる考察からは作らない", () => {
    const p = areaProfile("muni-01001", makeData({ population_change_rate: { "2020-10-01": fill(-12, -2) } }));
    expect(p.title).toBeNull();
  });
  it("住む人の国籍や外国人の割合は題名に使わない", () => {
    const p = areaProfile("muni-01001", makeData({
      foreign_residents_share: { "2026-01-01": fill(20, 1) }, foreign_residents: { "2026-01-01": fill(500, 10) },
      census_foreign_nepal_share: { "2020-10-01": fill(3, 0.1) }, census_foreign_nepal: { "2020-10-01": fill(100, 1) },
    }));
    expect(p.lines.length).toBe(2);
    expect(p.title).toBeNull();
  });
  it("題名の言い回しは課題に当たる向きには付けない", () => {
    for (const [id, t] of Object.entries(RANK_TEMPLATES)) {
      if (t.highTag) expect(t.highTone, id).not.toBe("neg");
      if (t.lowTag) expect(t.lowTone, id).not.toBe("neg");
    }
  });
});
