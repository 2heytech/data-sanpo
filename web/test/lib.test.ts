import { describe, expect, it } from "vitest";
import { BLANK_COLOR, classIndex, colorsFor, fillColorExpression, NO_DATA_COLOR } from "../src/lib/classify";
import { compactNumber, formatBasis, formatFraction, formatValue, rankIfVaried, rankOf, ranked, splitRanking } from "../src/lib/format";
import { municipalityPeriods } from "../src/lib/periods";
import { AreaSearch, normalize } from "../src/lib/search";
import type { Indicator, SearchIndex } from "../src/lib/types";
import { municipalityCodeOf, parseState, serializeState } from "../src/lib/urlstate";

const pct = { unit: "%", digits: 1, kind: "ratio" } as Indicator;
const people = { unit: "人", digits: 0, kind: "count" } as Indicator;

describe("formatValue", () => {
  it("単位と桁区切りを付ける", () => {
    expect(formatValue({ value: 12345, status: "observed" }, people)).toBe("12,345 人");
    expect(formatValue({ value: 23.456, status: "derived" }, pct)).toBe("23.5%");
  });
  it("文章の中では単位を詰める（表は間をあける）", () => {
    expect(formatValue({ value: 12345, status: "observed" }, people, { inText: true })).toBe("12,345人");
    expect(formatValue({ value: 23.456, status: "derived" }, pct, { inText: true })).toBe("23.5%");
  });
  it("表示の桁で0になる値に符号を付けない（-0.0% と出さない）", () => {
    const change = { unit: "%", digits: 1, kind: "change" } as Indicator;
    expect(formatValue({ value: -0.036, status: "derived" }, change)).toBe("0.0%");
    expect(formatValue({ value: 0.04, status: "derived" }, change)).toBe("0.0%");
    expect(formatValue({ value: -0.05, status: "derived" }, change)).toBe("-0.1%");
    expect(formatValue({ value: 0.05, status: "derived" }, change)).toBe("+0.1%");
  });
  it("区分で公表された値は区分の名前で書く（就学援助率、値は区分の上の端）", () => {
    const band = { unit: "%", digits: 0, kind: "ratio", legend: { method: "bands", classes: 12, scheme: "oranges", band: 5 } } as Indicator;
    expect(formatValue({ value: 15, status: "observed" }, band)).toBe("10%以上15%未満");
    expect(formatValue({ value: 5, status: "observed" }, band)).toBe("5%未満");
    expect(formatValue({ value: 0, status: "observed" }, band)).toBe("0%");
  });
  it("値がない理由を示し、0にしない", () => {
    expect(formatValue({ value: null, status: "suppressed" }, people)).toContain("秘匿");
    expect(formatValue({ value: null, status: "withheld" }, pct)).toContain("非表示");
    expect(formatValue(undefined, people)).toBe("データなし");
  });
  it("率の内訳を示す", () => {
    const row = { entity_id: "a", value: 25, status: "derived", numerator: 250, denominator: 1000 } as const;
    expect(formatFraction(row, pct)).toBe("250 人 ÷ 1,000 人");
    // 「〜の割合」は全体のうちの数として書く
    expect(formatFraction(row, { ...pct, name: "65歳以上の割合" })).toBe("1,000 人のうち 250 人");
    expect(formatFraction(row, { ...pct, name: "1世帯あたり人数", unit: "人", fraction_units: ["人", "世帯"] })).toBe("250 人 ÷ 1,000 世帯");
  });
  it("値の求め方を短く書く", () => {
    expect(formatBasis({ value: 1, status: "derived", note: "市区町村の分子・分母を合計して計算" }, true))
      .toEqual({ text: "市区町村の数を合計して計算", note: null });
    expect(formatBasis({ value: 1, status: "derived" }, true)).toEqual({ text: null, note: null });
    expect(formatBasis({ value: 1, status: "derived" }, false).text).toBe("公表された数から計算");
    expect(formatBasis({ value: 1, status: "estimated", note: "ほかの注記" }, false)).toEqual({ text: "推計値", note: "ほかの注記" });
  });
});

describe("rankOf", () => {
  const rows = [
    { entity_id: "a", value: 10, status: "observed" as const },
    { entity_id: "b", value: 30, status: "observed" as const },
    { entity_id: "c", value: 30, status: "observed" as const },
    { entity_id: "d", value: null, status: "suppressed" as const },
  ];
  it("同値は同順位、値なしは除外", () => {
    expect(rankOf(rows, "b")).toEqual({ rank: 1, total: 3 });
    expect(rankOf(rows, "a")).toEqual({ rank: 3, total: 3 });
    expect(rankOf(rows, "d")).toBeNull();
  });
  it("すべて同じ値なら順位を出さない", () => {
    expect(rankIfVaried(rows, "a")).toEqual({ rank: 3, total: 3 });
    expect(rankIfVaried(rows.slice(1), "b")).toBeNull();
  });
});

describe("classify", () => {
  it("区切りの数に応じて色数を決める", () => {
    expect(colorsFor("blues", [1, 2, 3, 4])).toHaveLength(5);
    expect(colorsFor("blues", [1, 2])).toHaveLength(3);
    expect(colorsFor("blues", [])).toHaveLength(1);
  });
  it("10段階でも配色の両端を保ち、色が重ならない", () => {
    const c = colorsFor("blues", [1, 2, 3, 4, 5, 6, 7, 8, 9]);
    expect(c).toHaveLength(10);
    expect(c[0]).toBe("#f7fbff");
    expect(c[9]).toBe("#08306b");
    expect(new Set(c).size).toBe(10);
  });
  it("増減の配色は0を境に減少側・増加側の色に分かれる", () => {
    const c = colorsFor("puor", [-4, -2, 0, 2, 4, 6]);
    expect(c).toHaveLength(7);
    // 0未満の2階級は橙系（前半）、0以上の5階級は紫系（後半）
    expect(c[0]).toBe("#7f3b08");
    expect(c[1]).toBe("#fee0b6");
    expect(c[2]).toBe("#d8daeb");
    expect(c[6]).toBe("#2d004b");
  });
  it("区切り値ちょうどは上の階級", () => {
    expect(classIndex(5, [5, 10])).toBe(1);
    expect(classIndex(4.9, [5, 10])).toBe(0);
    expect(classIndex(99, [5, 10])).toBe(2);
  });
  it("値なしは中立色", () => {
    expect(JSON.stringify(fillColorExpression("blues", [1]))).toContain(NO_DATA_COLOR);
  });
  it("12区分でも色が重ならない", () => {
    const c = colorsFor("reds", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
    expect(c).toHaveLength(12);
    expect(new Set(c).size).toBe(12);
  });
  it("0を塗らない指標は、0を透明にし、ほぼ白の色を使わない", () => {
    const expr = JSON.stringify(fillColorExpression("reds", [1, 2], true));
    expect(expr).toContain(BLANK_COLOR);
    expect(expr).not.toContain("#fff5f0");
    expect(colorsFor("reds", [1, 2], true)[0]).toBe("#fee0d2");
    expect(JSON.stringify(fillColorExpression("reds", [1, 2]))).not.toContain(BLANK_COLOR);
  });
  it("都道府県ごとの区切りがあれば、都道府県コードで区切りを切り替える", () => {
    const key = ["slice", ["get", "id"], 5, 7];
    const expr = fillColorExpression("blues", [100], false, { key, breaks: { "13": [10, 20], "19": [1] } }) as unknown[];
    const match = expr[expr.length - 1] as unknown[];
    expect(match[0]).toBe("match");
    expect(match[1]).toEqual(key);
    expect(match[2]).toBe("13");
    expect((match[3] as unknown[])[0]).toBe("step");
    expect((match[3] as unknown[]).filter((x) => typeof x === "number")).toEqual([10, 20]);
    expect(match[4]).toBe("19");
    // どの都道府県でもないとき（区切りのない県）は全国の区切り
    expect((match[6] as unknown[]).filter((x) => typeof x === "number")).toEqual([100]);
  });
  it("県内がすべて0の都道府県は、0を塗らない（ほかの県の0は塗る）", () => {
    const key = ["slice", ["get", "id"], 5, 7];
    const expr = fillColorExpression("blues", [10], false, { key, breaks: { "13": [10] }, zero: ["36"] }) as unknown[];
    expect(JSON.stringify(expr[3])).toBe(JSON.stringify(["all", ["==", ["feature-state", "v"], 0], ["in", key, ["literal", ["36"]]]]));
    expect(expr[4]).toBe(BLANK_COLOR);
    expect(JSON.stringify(fillColorExpression("blues", [10], false, { key, breaks: { "13": [10] } }))).not.toContain(BLANK_COLOR);
  });
});

describe("search", () => {
  it("表記ゆれを吸収する", () => {
    expect(normalize("本町１丁目")).toBe(normalize("本町一丁目"));
    expect(normalize("霞ヶ関")).toBe(normalize("霞が関"));
    expect(normalize("カタカナ")).toBe(normalize("かたかな"));
    expect(normalize("二十三丁目")).toBe("23丁目");
  });
  const index: SearchIndex = {
    fields: ["id", "name", "context", "level"],
    entries: [
      ["muni-13104", "新宿区", "区部", "municipality"],
      ["area-1", "西新宿一丁目", "新宿区", "small_area"],
      ["area-2", "新宿一丁目", "新宿区", "small_area"],
    ],
  };
  it("市区町村・前方一致を優先する", () => {
    const hits = new AreaSearch(index).search("新宿");
    expect(hits.map((h) => h.id)).toEqual(["muni-13104", "area-2", "area-1"]);
    expect(new AreaSearch(index).search("新宿1丁目")[0].id).toBe("area-2");
  });
  it("市区町村の前方一致を、ほかの市区町村にある同じ名前の町丁・字等より先に出す", () => {
    const withTown: SearchIndex = { ...index, entries: [...index.entries, ["area-3", "新宿", "魚津市", "small_area"]] };
    expect(new AreaSearch(withTown).search("新宿").map((h) => h.id)).toEqual(["muni-13104", "area-3", "area-2", "area-1"]);
  });
});

describe("urlstate", () => {
  it("往復できる", () => {
    const s = { indicator: "population_total", period: "2020-10-01", area: "area-13101001001" };
    expect(parseState(serializeState(s))).toEqual(s);
  });
  it("座標や不正な値を受け付けない", () => {
    expect(parseState("?i=<script>&lat=35.6&lng=139.7")).toEqual({});
  });
  it("地域IDから団体コードを得る", () => {
    expect(municipalityCodeOf("area-13101001001")).toBe("13101");
    expect(municipalityCodeOf("muni-13101")).toBe("13101");
  });
});

describe("地価の凡例", () => {
  it("切りのよい価格で区切り、区分の数と色の数が合う", async () => {
    const { landBins, yenLabel, LAND_BREAKS, LAND_COLORS } = await import("../src/map/landprices");
    expect(LAND_COLORS.length).toBe(LAND_BREAKS.length + 1);
    expect(yenLabel(10_000_000)).toBe("1,000万円");
    const bins = landBins();
    expect(bins[0]).toBe("10万円未満");
    expect(bins[1]).toBe("10万〜20万円");
    expect(bins[bins.length - 1]).toBe("1,000万円以上");
    expect(bins.length).toBe(LAND_COLORS.length);
  });
});

describe("地価公示と地価調査の共通地点", () => {
  const point = (id: string, coord: [number, number], address: string) => ({
    id, name: id, municipality_id: "muni-13101", coord, use: "000", use_label: "住宅地", address,
    residential_address: null, area_m2: null, current_use: null, station: null, station_distance_m: null,
    zoning: null, change_rate: null, values: [],
  });
  it("所在地の丁目の書き方（漢数字・全角数字）と空白の違いをそろえる", async () => {
    const { normalizeLandAddress } = await import("../src/map/landprices");
    expect(normalizeLandAddress("東京都 中央区新富一丁目５番１")).toBe(normalizeLandAddress("東京都 中央区新富１丁目５番１"));
    expect(normalizeLandAddress("東京都 港区芝二十三丁目１番")).toBe("東京都港区芝23丁目1番");
    expect(normalizeLandAddress(null)).toBe("");
  });
  it("位置が同じか、所在地が同じで100m以内の地点を組にし、1つの標準地は1つの基準地とだけ組む", async () => {
    const { pairLandPoints } = await import("../src/map/landprices");
    const publics = [
      point("land-a", [139.7, 35.6], "東京都 千代田区三番町６番２５"),
      point("land-b", [139.71, 35.61], "東京都 中央区新富１丁目５番１"),
      point("land-c", [139.72, 35.62], "東京都 中央区銀座１丁目１番"),
    ];
    const surveys = [
      point("landsv-a", [139.7, 35.6], "東京都 千代田区三番町６番２５外"),          // 位置が同じ
      point("landsv-b", [139.7101, 35.6101], "東京都 中央区新富一丁目５番１"),     // 所在地が同じで約14m
      point("landsv-c", [139.73, 35.62], "東京都 中央区銀座１丁目１番"),           // 所在地は同じだが約900m離れている
      point("landsv-a2", [139.7, 35.6], "東京都 千代田区三番町６番２５"),          // land-a はもう組んでいる
    ];
    const pairs = pairLandPoints(publics, surveys);
    expect(Object.fromEntries(pairs)).toEqual({ "landsv-a": "land-a", "landsv-b": "land-b" });
  });
  it("推移の変化率は1つ前の行から求め、1年より前の行とは比べない", async () => {
    const { withChanges } = await import("../src/map/landprices");
    const rows = withChanges([
      { period: "2020-01-01", kind: "land_price", value: 100 },
      { period: "2022-01-01", kind: "land_price", value: 120 },      // 2021年は値なし
      { period: "2022-07-01", kind: "land_survey_price", value: 126 }, // 半年後（共通地点）
      { period: "2023-01-01", kind: "land_price", value: 130 },
    ]);
    expect(rows.map((r) => r.change === null ? null : Math.round(r.change * 10) / 10)).toEqual([null, null, 5, 3.2]);
  });
});

describe("compactNumber（凡例の目盛り）", () => {
  it("1万以上は万・億で短く書き、1万未満はそのまま", () => {
    expect(compactNumber(2000, 0)).toBe("2,000");
    expect(compactNumber(0.35, 2)).toBe("0.35");
    expect(compactNumber(12000, 0)).toBe("1.2万");
    expect(compactNumber(10000, 0)).toBe("1万");
    expect(compactNumber(3500000, 0)).toBe("350万");
    expect(compactNumber(150000000, 0)).toBe("1.5億");
  });
});

describe("天気の凡例", () => {
  it("区切りから区分の文言を作り、区分の数と色の数が合う", async () => {
    const { weatherBins, weatherColors } = await import("../src/map/weather");
    const e = { breaks: [1000, 1500, 2000], unit: "mm", digits: 0, scheme: "blues" };
    expect(weatherBins(e)).toEqual(["1,000mm未満", "1,000〜1,500mm", "1,500〜2,000mm", "2,000mm以上"]);
    const colors = weatherColors(e);
    expect(colors.length).toBe(4);
    expect(colors[0]).not.toBe("#f7fbff");   // ほぼ白の色は地図の上で見えにくいので使わない
  });
});

describe("空港・港の点", () => {
  it("最新の値のある年と、前の年からの増減", async () => {
    const { latestIndex, changeText } = await import("../src/map/transport");
    expect(latestIndex({ values: [100, 120, null] })).toBe(1);
    expect(latestIndex({ values: [null, null] })).toBe(1);
    expect(changeText(100, 120)).toBe("+20.0%");
    expect(changeText(200, 100)).toBe("−50.0%");
    expect(changeText(null, 100)).toBe("");
    expect(changeText(0, 100)).toBe("");   // 前の年が0なら増減率は出さない
  });
  it("名前に「空港」「港」を付ける", async () => {
    const { displayName } = await import("../src/map/transport");
    expect(displayName("airport", "東京国際")).toBe("東京国際空港");
    expect(displayName("airport", "調布飛行場")).toBe("調布飛行場");
    expect(displayName("port", "東京")).toBe("東京港");
    expect(displayName("port", "竹生島港")).toBe("竹生島港");
  });
});

describe("labels", () => {
  it("広い地域ほど、長い名前ほど小さく収まる大きさになる", async () => {
    const { labelFit } = await import("../src/lib/labels");
    const box: [number, number, number, number] = [139.7, 35.6, 139.8, 35.7];
    const wide = labelFit({ name: "千代田区", bbox: box }, null);
    expect(labelFit({ name: "千代田区", bbox: [139.7, 35.6, 139.9, 35.8] }, null)).toBeGreaterThan(wide);
    expect(labelFit({ name: "千代田区千代田", bbox: box }, null)).toBeLessThan(wide);
    expect(labelFit({ name: "千代田区", bbox: box }, "12,345 人")).toBeLessThan(wide);   // 2行分の高さ
    // 値を出すときは、値のない地域も2行分で計算する
    const flat: [number, number, number, number] = [139, 35.6, 141, 35.7];
    expect(labelFit({ name: "千代田区", bbox: flat }, "")).toBeLessThan(labelFit({ name: "千代田区", bbox: flat }, null));
    expect(labelFit({ name: "x" }, null)).toBe(0);
  });

  it("balancedFits / mainPartBbox", async () => {
    const { balancedFits, mainPartBbox } = await import("../src/lib/labels");
    // 中央値に半分寄せる（幾何平均）
    expect(balancedFits([1, 4, 16])).toEqual([2, 4, 8]);
    expect(balancedFits([0, 4])).toEqual([0, 4]);
    // 離れた小さい島は範囲に入れない
    const sq = (x: number, y: number, d: number) => [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]];
    expect(mainPartBbox({ type: "MultiPolygon", coordinates: [sq(142, 26, 0.1), sq(139, 35.5, 1)] })).toEqual([139, 35.5, 140, 36.5]);
    expect(mainPartBbox({ type: "Polygon", coordinates: sq(1, 2, 3) })).toEqual([1, 2, 4, 5]);
    expect(mainPartBbox(null)).toBeUndefined();
  });
  it("文字の大きさは最小〜最大の間で、1ズームごとに区切る", async () => {
    const { growingTextSize } = await import("../src/lib/labels");
    const expr = growingTextSize([[8, 10, 13], [10, 12, 21]], "fit") as unknown[];
    expect(expr.slice(0, 3)).toEqual(["interpolate", ["linear"], ["zoom"]]);
    expect(expr.filter((x) => typeof x === "number")).toEqual([8, 9, 10]);
    expect(JSON.stringify(expr[6])).toBe(JSON.stringify(["max", 11, ["min", 17, ["*", ["get", "fit"], 512]]]));
  });
});

describe("ranked・splitRanking", () => {
  it("値の大きい順に並べ、同値は同順位、値なしは除く", () => {
    const rows = [
      { entity_id: "a", value: 10, status: "observed" as const },
      { entity_id: "b", value: 30, status: "observed" as const },
      { entity_id: "c", value: 30, status: "observed" as const },
      { entity_id: "d", value: null, status: "suppressed" as const },
    ];
    expect(ranked(rows).map((r) => [r.entity_id, r.rank])).toEqual([["b", 1], ["c", 1], ["a", 3]]);
  });
  it("上位・下位に分け、少なければ全部を上位に入れる", () => {
    const xs = Array.from({ length: 250 }, (_, i) => i);
    const { top, middle, bottom } = splitRanking(xs, 100);
    expect([top.length, middle.length, bottom.length]).toEqual([100, 50, 100]);
    expect(bottom[0]).toBe(150);
    expect(splitRanking(xs.slice(0, 200), 100)).toEqual({ top: xs.slice(0, 200), middle: [], bottom: [] });
  });
});

describe("municipalityPeriods（市区町村ページで使う時点）", () => {
  const period = (p: string, source: string, levels: string[], aggregate = false) =>
    ({ period: p, label: p, levels, source_ids: [`${source}@x`], aggregate });
  it("国勢調査の新しい回が市区町村の値で出ていれば、既定の時点より先に使う", () => {
    const pop = { default_period: "2020-10-01", periods: [
      period("2015-10-01", "census2015_small_area_population", ["municipality", "small_area"]),
      period("2020-10-01", "census2020_small_area_population", ["municipality", "small_area"]),
      period("2025-10-01", "census2025_municipal_population", ["municipality", "prefecture"]),
    ] } as unknown as Indicator;
    expect(municipalityPeriods(pop)).toEqual(["2025-10-01", "2020-10-01"]);
  });
  it("国勢調査以外の新しい時点（犯罪の年ごとの値など）や、市区町村の値がない時点には切り替えない", () => {
    const crime = { default_period: "2021-2025", periods: [
      period("2021-2025", "police_crime_od_13", ["municipality"], true),
      period("2025-01-01", "police_crime_od_13", ["municipality"]),
    ] } as unknown as Indicator;
    expect(municipalityPeriods(crime)).toEqual(["2021-2025"]);
    const prefOnly = { default_period: "2020-10-01", periods: [
      period("2020-10-01", "census2020_small_area_population", ["municipality"]),
      period("2025-10-01", "census2025_prefecture", ["prefecture"]),
    ] } as unknown as Indicator;
    expect(municipalityPeriods(prefOnly)).toEqual(["2020-10-01"]);
  });
  it("既定の時点に市区町村の値がなければ、市区町村の値がある最も新しい時点を最後に置く（投票率）", () => {
    const turnout = { default_period: "2026-02-08", periods: [
      period("2025-06-22", "tokyo_election_2025", ["municipality", "prefecture"]),
      period("2025-07-20", "soumu_election_2025", ["municipality", "prefecture"]),
      period("2026-02-08", "soumu_election_2026", ["prefecture"]),
    ] } as unknown as Indicator;
    expect(municipalityPeriods(turnout)).toEqual(["2026-02-08", "2025-07-20"]);
  });
});
