import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { areaInsights, areaProfile, type InsightData } from "../src/lib/areaInsights";
import type { PlacePoints } from "../src/lib/placeStats";
import { RANK_TEMPLATES } from "../src/lib/rankInsights";
import type { Indicator, ValueRow } from "../src/lib/types";

const ind = (id: string, unit: string, digits: number, periods: string[], kind: Indicator["kind"] = "ratio", label?: (p: string) => string) => ({
  id, name: id, unit, digits, kind, default_period: periods[periods.length - 1],
  periods: periods.map((p) => ({ period: p, label: label ? label(p) : `${p.slice(0, 4)}年${Number(p.slice(5, 7))}月1日現在` })),
}) as unknown as Indicator;
const fiscalYear = (p: string) => `${p.slice(0, 4)}年度`;

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
    // 土地・財政（設計変更記録 #129）
    ["population_total", ind("population_total", "人", 0, ["2010-10-01", "2025-10-01"], "count")],
    ["area", ind("area", "km²", 2, ["2025-10-01"], "count")],
    ["elevation_mean", ind("elevation_mean", "m", 1, ["2026-10-01"])],
    ["elevation_range", ind("elevation_range", "m", 1, ["2026-10-01"])],
    ["land_use_forest_share", ind("land_use_forest_share", "%", 1, ["2021-04-01"], "ratio", fiscalYear)],
    ["land_use_paddy_share", ind("land_use_paddy_share", "%", 1, ["2021-04-01"], "ratio", fiscalYear)],
    ["land_use_field_share", ind("land_use_field_share", "%", 1, ["2021-04-01"], "ratio", fiscalYear)],
    ["land_use_building_share", ind("land_use_building_share", "%", 1, ["1976-04-01", "1991-04-01", "2006-04-01", "2021-04-01"], "ratio", fiscalYear)],
    ["vegetation_natural_forest_share", ind("vegetation_natural_forest_share", "%", 1, ["2024-04-01"], "ratio", () => "現存植生図2024")],
    ["farmland_parcel_area", ind("farmland_parcel_area", "㎡", 0, ["2026-04-01"], "ratio", () => "2026年度公開")],
    ["farmland_paddy_share", ind("farmland_paddy_share", "%", 1, ["2026-04-01"], "ratio", () => "2026年度公開")],
    ["farmland_field_share", ind("farmland_field_share", "%", 1, ["2026-04-01"], "ratio", () => "2026年度公開")],
    ["fiscal_strength_index", ind("fiscal_strength_index", "", 2, ["2024-04-01"], "ratio", fiscalYear)],
    ["manufacturing_shipments", ind("manufacturing_shipments", "億円", 1, ["2024-01-01"], "count")],
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
  it("国勢調査の2025年の値があればそれを使い、その市区町村に値がなければ既定の2020年の値を使う", () => {
    const base = makeData({});
    const change = {
      ...ind("population_change_rate", "%", 1, ["2020-10-01", "2025-10-01"], "change"), default_period: "2020-10-01",
      periods: [
        { period: "2020-10-01", label: "2020年10月1日現在", levels: ["municipality", "small_area"], source_ids: ["census2020_small_area_population@x"] },
        { period: "2025-10-01", label: "2025年10月1日現在", levels: ["municipality"], source_ids: ["census2020_small_area_population@x", "census2025_municipal_population@x"] },
      ],
    } as unknown as Indicator;
    const data = (v2025: (number | null)[]): InsightData => ({
      ...base,
      indicator: (id) => (id === "population_change_rate" ? change : base.indicator(id)),
      indicators: () => [change],
      rows: (id, period) => {
        if (id !== "population_change_rate") return [];
        const v = period === "2025-10-01" ? v2025 : fill(-12, -2);
        return v.map((x, i): ValueRow => ({ entity_id: `muni-${i < 10 ? "01" : "02"}${String(i + 1).padStart(3, "0")}`, value: x ?? null, status: x === null ? "missing" : "observed" }));
      },
    });
    expect(areaInsights("muni-01001", data(fill(3, -2)))).toEqual([
      "人口は5年前から3.0%増えていて（2025年10月1日現在）、全国の市区町村の中でも増え方が大きい方です。住宅の開発などで移り住む人が多いと考えられます。",
    ]);
    // 2025年の値がない市区町村（区を再編した浜松市の旧区など）は2020年で書く
    expect(areaInsights("muni-01001", data(fill(null, -2)))[0]).toContain("12.0%減っていて（2020年10月1日現在）");
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
      vacant_house_rate: { "2023-10-01": fill(30, 10) },
      population_change_rate: { "2020-10-01": fill(3, -2) },
    }));
    expect(lines.find((l) => l.startsWith("空き家率"))).toBe(
      "空き家率が30.0%と全国でも高い方です（2023年10月1日現在）。人口は減っていないので、別荘や入居者を募集中の賃貸住宅など、ふだん人が住んでいない住宅が多いと考えられます。");
  });
  it("空き家率が4割を超える地域（別荘地）は、人口が減っていても使われなくなった家とは書かない", () => {
    const lines = areaInsights("muni-01001", makeData({
      vacant_house_rate: { "2023-10-01": fill(70, 10) },
      population_change_rate: { "2020-10-01": fill(-12, -2) },
    }));
    expect(lines.find((l) => l.startsWith("空き家率"))).toBe(
      "空き家率が70.0%と全国でも高い方です（2023年10月1日現在）。別荘やリゾートマンションなど、ふだん人が住んでいない住宅が多い地域と考えられます。");
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

describe("土地と財政（面積・地形・土地利用・農地・財政力指数）", () => {
  it("面積が全国でも特に広い・小さいときに書き、広い方は題名にも使う", () => {
    const wide = areaProfile("muni-01001", makeData({ area: { "2025-10-01": fill(2177.61, 100) } }));
    expect(wide.lines).toEqual([
      "面積は2,177.61 km²で、全国の市区町村の中で最も広い市区町村です（2025年10月1日現在）。広い市域に、まちの中心から山や農村まで、いろいろな土地を抱えていると考えられます。",
    ]);
    expect(wide.title).toBe("広い市域を持つまち");
    const small = areaInsights("muni-01001", makeData({ area: { "2025-10-01": fill(3, 100) } }));
    expect(small).toEqual(["面積は3.00 km²で、全国の市区町村の中でも小さい方です（2025年10月1日現在）。まちの範囲がコンパクトにまとまっているようです。"]);
  });
  it("平均標高と高低差から地形を書き、観測所が高いときだけ夏のすずしさにふれる（観測所の標高だけの文は重ねない）", () => {
    const pts = places({
      centers: new Map([["muni-01001", [138, 36]]]),
      weather: [{ name: "高原", municipality_id: "muni-01001", coord: [138, 36], altitude_m: 999, values: { snowfall_normal: 50 } }],
    });
    const mountain = areaProfile("muni-01001", makeData({
      elevation_mean: { "2026-10-01": fill(1206, 100) }, elevation_range: { "2026-10-01": fill(2723, 300) },
    }, pts));
    expect(mountain.lines).toEqual([
      "まちの中の高低差（いちばん低い所と高い所の差）は2,723mと、全国の市区町村の中でも大きい方です（平均標高は1,206m）。" +
        "平地から高い山々まで、変化に富んだ地形のまちと考えられます。気象庁の観測所「高原」も標高999mにあり、夏も比較的すずしい気候と思われます。",
    ]);
    expect(mountain.title).toBe("高い山々を抱えるまち");
    // 平均標高が高いだけのとき。まちの中心は低い盆地にあることも多いので、題名は平均が700m以上のときだけ
    const plateau = (mean: number) => areaProfile("muni-01001", makeData({
      elevation_mean: { "2026-10-01": fill(mean, 100) }, elevation_range: { "2026-10-01": fill(500, 1000) },
    }));
    expect(plateau(800).lines).toEqual(["まちの土地の平均標高は800mで、全国の市区町村の中で最も高くなっています。土地の多くが高原や山地にあるまちのようです。"]);
    expect(plateau(800).title).toBe("高原や山地の広がるまち");
    expect(plateau(600).title).toBeNull();
    const low = areaProfile("muni-01001", makeData({
      elevation_mean: { "2026-10-01": fill(-2, 100) }, elevation_range: { "2026-10-01": fill(10, 100) },
    }));
    expect(low.lines).toEqual(["まちの土地の平均標高は-2.0mと海面より低く、高低差も10mほどの平らな土地です。低い平野に広がるまちのようです。"]);
    expect(low.title).toBe("平らな低地に広がるまち");
  });
  it("土地利用は森林・田・畑のうち全国で特に割合の高いものを1つ書く（畑には牧草地も含む）", () => {
    const field = areaProfile("muni-01001", makeData({
      land_use_field_share: { "2021-04-01": fill(60, 10) }, land_use_forest_share: { "2021-04-01": fill(30, 50) },
    }));
    expect(field.lines).toEqual([
      "まちの土地の60.0%が畑や果樹園、牧草地などで（2021年度）、全国の市区町村の中でも割合が高い方です。畑作や酪農など、田んぼ以外の農業が盛んな地域と考えられます。",
    ]);
    expect(field.title).toBe("畑や牧草地の広がるまち");
    const forest = areaInsights("muni-01001", makeData({
      land_use_forest_share: { "2021-04-01": fill(90, 50) }, vegetation_natural_forest_share: { "2024-04-01": fill(50, 5) },
    }));
    expect(forest).toEqual([
      "まちの土地の90.0%が森林で（2021年度）、全国の市区町村の中でも森林の多い方です。植生図では土地の50.0%が自然林で（現存植生図2024）、昔からの森が多く残っている地域と考えられます。",
    ]);
  });
  it("農地の区画の広さは、農地がまちの面積の1割以上あるときだけ書く（都市部の少ない農地では書かない）", () => {
    const farm = (fieldShare: number) => areaInsights("muni-01001", makeData({
      farmland_parcel_area: { "2026-04-01": fill(40_000, 3_000) },
      farmland_paddy_share: { "2026-04-01": fill(2, 2) }, farmland_field_share: { "2026-04-01": fill(fieldShare, 5) },
    }));
    expect(farm(5)).toEqual([]);
    expect(farm(30)).toEqual([
      "農地の1区画の平均面積は約4.0haと、全国の市区町村の中でも広い方です（2026年度公開の筆ポリゴン）。大きな区画で機械を使う、規模の大きな農業が行われていると考えられます。",
    ]);
  });
  it("建物用地の割合の30年の増加は、途中の年度も増え続け、人口も増えているときだけ書く（年度で判読の方法が違うため）", () => {
    const grow = (building: number[], pop2025: number) => areaInsights("muni-01001", makeData({
      land_use_building_share: Object.fromEntries(["1991-04-01", "2006-04-01", "2021-04-01"].map((p, i) => [p, fill(building[i], 10)])),
      population_total: { "2010-10-01": fill(1000, 1000), "2025-10-01": fill(pop2025, 1000) },
    }));
    expect(grow([20, 35, 50], 1200)).toEqual([
      "建物の建つ土地（建物用地）の割合は、1991年度の20.0%から2021年度は50.0%に増えました。" +
        "この30年で田畑や林が住宅地などに変わり、まちが広がってきたと考えられます（年度によって判読の方法が違うため、数字には判読の違いも含まれます）。",
    ]);
    expect(grow([20, 60, 50], 1200)).toEqual([]);
    expect(grow([20, 35, 50], 1000)).toEqual([]);
  });
  it("人口が増えている市区町村は、2010年からの長い期間の増え方も書く", () => {
    const lines = areaInsights("muni-01001", makeData({
      population_change_rate: { "2020-10-01": fill(3, -2) },
      population_total: { "2010-10-01": fill(1000, 1000), "2025-10-01": fill(1100, 1000) },
    }));
    expect(lines).toEqual([
      "人口は5年前から3.0%増えていて（2020年10月1日現在）、全国の市区町村の中でも増え方が大きい方です。2010年からの15年では10.0%増えています。住宅の開発などで移り住む人が多いと考えられます。",
    ]);
  });
  it("財政力指数は1以上のときだけ、指標の意味と、ほかの指標で裏付けられる理由を書く（低い方は書かない）", () => {
    const fiscal = (v: number) => areaProfile("muni-01001", makeData({
      fiscal_strength_index: { "2024-04-01": fill(v, 0.5) }, manufacturing_shipments: { "2024-01-01": fill(5_000, 10) },
    }));
    const p = fiscal(1.5);
    expect(p.lines.at(-1)).toBe(
      "財政力指数は1.50で（2024年度、3年度の平均）、全国の市区町村のうち1位です。1以上は、標準的な行政サービスの費用を自前の収入でまかなえる水準とされ、" +
        "国から普通交付税を受けないことが多くなります。工場など企業からの税収が多いことが表れていると考えられます。");
    // 自治体の評価として読まれないよう、まちの特徴（産業など）の後に置き、題名にはしない
    expect(p.groups.map((g) => g.theme).at(-1)).toBe("まちの財政");
    expect(p.title).not.toContain("財政");
    expect(fiscal(0.3).lines.join("")).not.toContain("財政");
  });
});
