import { describe, expect, it } from "vitest";
import { BLANK_COLOR, classIndex, colorsFor, fillColorExpression, NO_DATA_COLOR } from "../src/lib/classify";
import { formatFraction, formatValue, rankOf } from "../src/lib/format";
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
  it("値がない理由を示し、0にしない", () => {
    expect(formatValue({ value: null, status: "suppressed" }, people)).toContain("秘匿");
    expect(formatValue({ value: null, status: "withheld" }, pct)).toContain("非表示");
    expect(formatValue(undefined, people)).toBe("データなし");
  });
  it("率の内訳を示す", () => {
    expect(formatFraction({ entity_id: "a", value: 25, status: "derived", numerator: 250, denominator: 1000 }, pct))
      .toBe("250 人 ÷ 1,000 人");
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

describe("地価公示の凡例", () => {
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
