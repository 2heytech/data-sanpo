import { describe, expect, it } from "vitest";
import { descriptionLeaders, indicatorSummary, shortPeriodLabel, summaryPolicy, type SummaryArea } from "../src/lib/indicatorSummary";
import { cityValues, designatedCities } from "../src/lib/designatedCities";
import { latestPeriod, newerPeriod } from "../src/lib/periods";
import type { Indicator, Municipality, ValueRow } from "../src/lib/types";

const ind = (extra: Partial<Indicator> = {}) => ({
  id: "x", name: "人口", category: "人口・世帯", unit: "人", kind: "count", digits: 0,
  legend: { method: "quantile", classes: 7, scheme: "Blues" }, periods: [], default_period: "2020", ...extra,
}) as unknown as Indicator;
const area = (id: string, value: number | null, prefecture = "東京都", label = `${prefecture}${id}`): SummaryArea =>
  ({ id, label, prefecture, value });
// 値が n, n-1, …, 1 の市区町村（都道府県は prefOf で決める）
const series = (n: number, prefOf: (i: number) => string = () => "東京都") =>
  Array.from({ length: n }, (_, i) => area(`m${i}`, n - i, prefOf(i)));

describe("summaryPolicy", () => {
  it("地域を悪く言うように読める分類・指標は出さない", () => {
    expect(summaryPolicy(ind({ category: "犯罪" }))).toBe("none");
    expect(summaryPolicy(ind({ category: "財政" }))).toBe("none");
    expect(summaryPolicy(ind({ id: "school_aid_rate", category: "教育" }))).toBe("none");
    expect(summaryPolicy(ind({ legend: { method: "q", classes: 5, scheme: "Blues", band: 10 } }))).toBe("none");
    expect(summaryPolicy(ind({ category: "外国人住民", name: "外国人住民の数（中国）" }))).toBe("none");
  });
  it("所得・学歴・寿命などは大きい方だけ書く", () => {
    expect(summaryPolicy(ind({ category: "所得・税" }))).toBe("top");
    expect(summaryPolicy(ind({ category: "外国人住民", name: "外国人住民の割合" }))).toBe("top");
    expect(summaryPolicy(ind({ id: "life_expectancy_female", category: "健康" }))).toBe("top");
    expect(summaryPolicy(ind())).toBe("both");
  });
});

describe("descriptionLeaders", () => {
  const prefs = Array.from({ length: 47 }, (_, i) => area(`p${i}`, 100 - i, `県${i}`, `県${i}`));
  it("都道府県と市区町村の1位（値つき）と、続く2つの名前を返す", () => {
    expect(descriptionLeaders({ ind: ind(), municipalities: series(30), prefectures: prefs })).toEqual({
      prefecture: { top: "県0（100人）", next: ["県1", "県2"] },
      municipality: { top: "東京都m0（30人）", next: ["東京都m1", "東京都m2"] },
    });
  });
  it("1位が並ぶ単位は書かず、要約を出さない指標は null", () => {
    const tied = [area("a", 50), area("b", 50), ...series(10)];
    expect(descriptionLeaders({ ind: ind(), municipalities: tied, prefectures: prefs })?.municipality).toBeNull();
    expect(descriptionLeaders({ ind: ind(), municipalities: tied, prefectures: [] })).toBeNull();
    expect(descriptionLeaders({ ind: ind({ category: "犯罪" }), municipalities: series(30), prefectures: prefs })).toBeNull();
    // 都道府県が10未満（一部の都道府県だけの指標）のときは都道府県を書かない
    expect(descriptionLeaders({ ind: ind(), municipalities: series(30), prefectures: prefs.slice(0, 3) })?.prefecture).toBeNull();
  });
});

describe("shortPeriodLabel", () => {
  it("文の中で使う短い時点の名前にする", () => {
    expect(shortPeriodLabel("2020年10月1日現在")).toBe("2020年");
    expect(shortPeriodLabel("2023年度")).toBe("2023年度");
    expect(shortPeriodLabel("2019〜2023年の合計")).toBe("2019〜2023年");
    expect(shortPeriodLabel("2026年2月 衆院選（比例）")).toBe("2026年2月の衆院選");
    expect(shortPeriodLabel("現存植生図2024")).toBe("現存植生図2024");
  });
});

describe("indicatorSummary", () => {
  it("市区町村の1位と続く2つ、最も小さい市区町村、真ん中のまちを書く", () => {
    const lines = indicatorSummary({ ind: ind(), municipalities: series(21), prefectures: [] });
    expect(lines[0]).toBe("市区町村で見ると、人口の1位は東京都m0（21人）で、東京都m1（20人）、東京都m2（19人）が続きます。");
    expect(lines).toContain("最も小さいのは東京都m20（1人）です。");
    expect(lines).toContain("全国の市区町村を値の順に並べると、ちょうど真ん中に来るまちは11人です。");
    const big = [area("top", 50), ...series(21).slice(1)];
    expect(indicatorSummary({ ind: ind(), municipalities: big, prefectures: [] }))
      .toContain("全国の市区町村を値の順に並べると、ちょうど真ん中に来るまちは11人で、1位はその約4.5倍です。");
  });
  it("大きい方だけ書く指標は、最も小さい市区町村を書かない", () => {
    const lines = indicatorSummary({ ind: ind({ category: "所得・税" }), municipalities: series(21), prefectures: [] });
    expect(lines.some((l) => l.startsWith("最も小さい"))).toBe(false);
  });
  it("出さない指標は空", () => {
    expect(indicatorSummary({ ind: ind({ category: "犯罪" }), municipalities: series(21), prefectures: [] })).toEqual([]);
  });
  it("同じ値が並ぶ1位と、0が並ぶ下位は数で書く", () => {
    const munis = [area("a", 5), area("b", 5), area("c", 3), area("d", 0), area("e", 0), area("f", null)];
    const lines = indicatorSummary({ ind: ind(), municipalities: munis, prefectures: [] });
    expect(lines[0]).toBe("市区町村で見ると、人口が最も大きい5人の市区町村が2あります（東京都a・東京都b）。");
    expect(lines).toContain("値が0の市区町村が2あります。");
  });
  it("上位20に同じ都道府県が6以上あれば書く（100以上の値があるとき）", () => {
    const lines = indicatorSummary({ ind: ind(), municipalities: series(120, (i) => (i < 20 && i % 2 === 0 ? "大阪府" : "東京都")), prefectures: [] });
    expect(lines).toContain("上位20のうち10が大阪府の市区町村です。");
  });
  it("前の時点と比べて増えた・減った数を書く（多い方を先に）", () => {
    const now = series(25);
    const before = new Map(now.map((a, i) => [a.id, i < 5 ? a.value! + 1 : a.value! - 1] as [string, number]));
    const lines = indicatorSummary({ ind: ind(), municipalities: now, prefectures: [], previous: { label: "2020年", values: before } });
    expect(lines.at(-1)).toBe("2020年と比べると、両方の時点に値のある25市区町村のうち20で増え、5で減っています。");
    const ratio = indicatorSummary({ ind: ind({ unit: "%", kind: "ratio", digits: 1 }), municipalities: now, prefectures: [], previous: { label: "2020年", values: before } });
    expect(ratio.at(-1)).toBe("2020年と比べると、両方の時点に値のある25市区町村のうち20で上がり、5で下がっています。");
  });
  it("政令指定都市の市全体が区の1位を上回るときは書き添える", () => {
    const lines = indicatorSummary({ ind: ind(), municipalities: series(21), prefectures: [], cities: [area("横浜市", 100, "神奈川県", "横浜市")] });
    expect(lines[1]).toBe("政令指定都市は区ごとに並べています。市全体で見ると横浜市（100人）が最も大きくなります。");
  });
  it("市区町村の値がない指標は都道府県で書く", () => {
    const prefs = ["北海道", "青森県", "岩手県", "宮城県", "秋田県"].map((n, i) => area(`pref-0${i + 1}`, 10 - i, n, n));
    const lines = indicatorSummary({ ind: ind(), municipalities: [], prefectures: prefs });
    expect(lines[0]).toBe("都道府県で見ると、人口の1位は北海道（10人）で、青森県（9人）、岩手県（8人）が続きます。");
    expect(lines).toContain("最も小さいのは秋田県（6人）です。");
  });
});

describe("designatedCities / cityValues", () => {
  const muni = (id: string, name: string, region: string | null, prefecture = "14") => ({ id, name, region, prefecture }) as Municipality;
  const munis = [
    muni("muni-14101", "横浜市鶴見区", "横浜市"), muni("muni-14102", "横浜市神奈川区", "横浜市"),
    muni("muni-14201", "横須賀市", null), muni("muni-14301", "葉山町", "三浦郡"),
  ];
  const row = (id: string, value: number | null, numerator?: number, denominator?: number) =>
    ({ entity_id: id, value, status: value === null ? "missing" : "observed", numerator, denominator }) as ValueRow;
  it("区の region（市の名前）から政令指定都市をまとめる（郡の町村は入れない）", () => {
    expect(designatedCities(munis)).toEqual([{ name: "横浜市", prefecture: "14", wards: ["muni-14101", "muni-14102"] }]);
  });
  it("分子・分母を合計してから割る。人数・件数は値を足す", () => {
    const cities = designatedCities(munis);
    const ratio = ind({ kind: "ratio", unit: "%", scale: 100 });
    expect(cityValues(ratio, cities, [row("muni-14101", 50, 1, 2), row("muni-14102", 10, 1, 10)])?.[0].value).toBeCloseTo((2 / 12) * 100);
    expect(cityValues(ind(), cities, [row("muni-14101", 3), row("muni-14102", 4)])?.[0].value).toBe(7);
  });
  it("値のない区があれば値なし、分子・分母のない平均は計算しない", () => {
    const cities = designatedCities(munis);
    expect(cityValues(ind(), cities, [row("muni-14101", 3), row("muni-14102", null)])?.[0]).toMatchObject({ value: null, note: "値のない区があるため出していません" });
    expect(cityValues(ind(), cities, [])?.[0]).toMatchObject({ value: null, note: "この時点の区の値がありません" });
    expect(cityValues(ind({ kind: "ratio", unit: "歳" }), cities, [row("muni-14101", 40), row("muni-14102", 45)])).toBeNull();
  });
});

describe("newerPeriod / latestPeriod", () => {
  const p = (period: string, levels: string[], source = "census_2025") => ({ period, label: period, levels, source_ids: [source] });
  it("町丁目に合わせた既定の時点より新しい国勢調査の回（市区町村の値あり）を使う", () => {
    const census = ind({ default_period: "2020", periods: [p("2015", ["municipality", "small_area"]), p("2020", ["municipality", "small_area"]), p("2025", ["prefecture", "municipality"])] as unknown as Indicator["periods"] });
    expect(newerPeriod(census)).toBe("2025");
    expect(latestPeriod(census)).toBe("2025");
  });
  it("国勢調査以外の新しい時点には切り替えない", () => {
    const other = ind({ default_period: "2020", periods: [p("2020", ["municipality"], "x"), p("2024", ["municipality"], "x")] as unknown as Indicator["periods"] });
    expect(newerPeriod(other)).toBeNull();
    expect(latestPeriod(other)).toBe("2020");
  });
});
