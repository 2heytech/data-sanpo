import { describe, expect, it } from "vitest";
import {
  PREF_INDICATOR_PAGES, hasPrefIndicatorPage, prefIndicatorDescription, prefIndicatorFacts, prefIndicatorName, prefIndicatorPath,
  prefIndicatorRanking, prefIndicatorTitle, topPhrase,
} from "../src/lib/prefectureRanking";
import { DESCRIPTION_MAX } from "../src/lib/areaSummary";
import { designatedCities } from "../src/lib/designatedCities";
import type { Indicator, Municipality, ValueRow } from "../src/lib/types";

const muni = (code: string, name: string, region: string | null = null) =>
  ({ id: `muni-${code}`, name, prefecture: code.slice(0, 2), region }) as Municipality;
const period = (p: string, label: string, levels: string[] = ["municipality", "prefecture"]) =>
  ({ period: p, period_end: p, period_kind: "point", label, levels, boundary_version: "", source_ids: ["census_2020"] });
const ind = (id: string, extra: Partial<Indicator> = {}) =>
  ({ id, name: "65歳以上の割合", category: "人口", unit: "%", kind: "ratio", digits: 1, default_period: "2020-10-01",
    description: "人口に占める65歳以上の割合です。", method: "", caveats: [], periods: [period("2020-10-01", "2020年")],
    legend: { method: "quantile", classes: 7, scheme: "blues" }, ...extra }) as unknown as Indicator;
const row = (id: string, value: number | null): ValueRow => ({ entity_id: id, value, status: value === null ? "missing" : "observed" });

const munis = ["010", "020", "030", "040", "050", "060", "070"].map((c, i) => muni(`28${c}`, `町${i + 1}`));
const national = [
  row("muni-28010", 40), row("muni-28020", 45), row("muni-28030", 45), row("muni-28040", 30), row("muni-28050", 20),
  row("muni-28060", 25), row("muni-28070", null),
  row("muni-13010", 50), row("muni-13020", 10),
];
const values: Record<string, ValueRow[]> = {
  municipalities: national,
  prefectures: [row("pref-28", 30.5), row("pref-13", 23.1), row("pref-01", 33.0)],
};
const rows = (_id: string, _p: string, chunk: "municipalities" | "prefectures") => values[chunk];
const page = PREF_INDICATOR_PAGES.find((p) => p.id === "aged_65_plus_share")!;

describe("prefIndicatorRanking", () => {
  it("県内のすべての市区町村を値の大きい順に並べ、同じ値は同じ順位、全国の中の順位を添える", () => {
    const r = prefIndicatorRanking(ind("aged_65_plus_share"), "28", munis, rows)!;
    expect(r.rows.map((x) => [x.muni.name, x.rank, x.national?.rank])).toEqual([
      ["町2", 1, 2], ["町3", 1, 2], ["町1", 3, 4], ["町4", 4, 5], ["町6", 5, 6], ["町5", 6, 7],
    ]);
    expect(r.rows[0].national?.total).toBe(8);
  });
  it("値のない市区町村は順位に入れず、0 にせずに別に並べる。行がない市区町村も同じ", () => {
    const extra = [...munis, muni("28080", "町8")];
    const r = prefIndicatorRanking(ind("aged_65_plus_share"), "28", extra, rows)!;
    expect(r.missing.map((x) => [x.muni.name, x.value, x.rank])).toEqual([["町7", null, null], ["町8", null, null]]);
  });
  it("都道府県全体の値と、その全国の順位を出す", () => {
    const r = prefIndicatorRanking(ind("aged_65_plus_share"), "28", munis, rows)!;
    expect(r.prefRow?.value).toBe(30.5);
    expect(r.prefRank).toEqual({ rank: 2, total: 3 });
  });
  it("都道府県の値がない時点では、都道府県全体の値を出さない", () => {
    const i = ind("aged_65_plus_share", { periods: [period("2020-10-01", "2020年", ["municipality"])] } as Partial<Indicator>);
    const r = prefIndicatorRanking(i, "28", munis, rows)!;
    expect(r.prefRow).toBeNull();
    expect(r.prefRank).toBeNull();
  });
  it("県内で値のある市区町村が5つより少ないとき・値がすべて同じときは作らない", () => {
    const few = (_id: string, _p: string, chunk: "municipalities" | "prefectures") => chunk === "municipalities" ? national.slice(0, 4) : [];
    expect(prefIndicatorRanking(ind("aged_65_plus_share"), "28", munis, few)).toBeNull();
    const same = (_id: string, _p: string, chunk: "municipalities" | "prefectures") =>
      chunk === "municipalities" ? munis.map((m) => row(m.id, 7)) : [];
    expect(prefIndicatorRanking(ind("aged_65_plus_share"), "28", munis, same)).toBeNull();
  });
  it("国勢調査の新しい回（2025年）に市区町村の値があれば、そちらで並べる", () => {
    const i = ind("aged_65_plus_share", { periods: [period("2020-10-01", "2020年"), period("2025-10-01", "2025年")] } as Partial<Indicator>);
    const seen: string[] = [];
    const r = prefIndicatorRanking(i, "28", munis, (_id, p, chunk) => { seen.push(p); return values[chunk]; })!;
    expect(r.period.label).toBe("2025年");
    expect(seen[0]).toBe("2025-10-01");
  });
});

describe("hasPrefIndicatorPage", () => {
  it("全国の公開版で、対象の指標のうち順位が作れるものだけページがある", () => {
    expect(hasPrefIndicatorPage(ind("aged_65_plus_share"), "28", munis, rows, 47)).toBe(true);
    expect(hasPrefIndicatorPage(ind("aged_65_plus_share"), "29", munis, rows, 1)).toBe(false);
    expect(hasPrefIndicatorPage(ind("taxable_income_per_taxpayer"), "28", munis, rows, 47)).toBe(false);
    expect(hasPrefIndicatorPage(ind("area"), "30", [], rows, 47)).toBe(false);
  });
  it("所得・犯罪・財政・学力の指標は入れない", () => {
    const ids = PREF_INDICATOR_PAGES.map((p) => p.id);
    expect(ids).toHaveLength(15);
    for (const bad of ["taxable_income_per_taxpayer", "financial_strength_index", "crime_rate", "household_income"]) expect(ids).not.toContain(bad);
  });
});

describe("文章", () => {
  const r = prefIndicatorRanking(ind("aged_65_plus_share"), "28", munis, rows)!;
  it("指標名はよく探される呼び名を前に置き、正式な名前を括弧で添える", () => {
    expect(prefIndicatorName(ind("aged_65_plus_share"), page)).toBe("高齢化率（65歳以上の割合）");
    expect(prefIndicatorName(ind("area", { name: "面積" } as Partial<Indicator>), { id: "area" })).toBe("面積");
    expect(prefIndicatorPath("28", "area")).toBe("/prefectures/28/area/");
    expect(prefIndicatorTitle("兵庫県", ind("aged_65_plus_share"), page, "2025年")).toBe("兵庫県の高齢化率（65歳以上の割合） 市区町村ランキング（2025年）");
    const pop = PREF_INDICATOR_PAGES.find((p) => p.id === "population_total");
    expect(prefIndicatorTitle("兵庫県", ind("population_total", { name: "人口" } as Partial<Indicator>), pop, "2025年")).toBe("兵庫県の人口 市区町村ランキング（2025年）");
  });
  it("1〜3位は同じ値を同じ順位にまとめて書く", () => {
    expect(topPhrase(r.rows, ind("aged_65_plus_share"))).toBe("1位は町2・町3（45.0%）、3位は町1（40.0%）");
  });
  it("データから分かること: 上位・いちばん低い市区町村・県全体の値と順位・政令指定都市を書く", () => {
    const lines = prefIndicatorFacts({ pref: "兵庫県", ind: ind("aged_65_plus_share"), page, ranking: r,
      cities: [{ name: "神戸市", text: "29.0%" }, { name: "姫路市", text: null }] });
    expect(lines).toEqual([
      "兵庫県の6市区町村のうち、1位は町2・町3（45.0%）、3位は町1（40.0%）です。",
      "いちばん低いのは町5で、20.0%です。",
      "兵庫県全体では30.5%で、全国3都道府県のうち2位です。",
      "政令指定都市の神戸市は、区ごとに並べています（神戸市全体では29.0%）。",
      "政令指定都市の姫路市は、区ごとに並べています。",
    ]);
  });
  it("小さい側を書かない指標では、いちばん低い市区町村を書かない", () => {
    const lines = prefIndicatorFacts({ pref: "兵庫県", ind: ind("population_change_rate"), page: { id: "population_change_rate" }, ranking: r, cities: [] });
    expect(lines.some((l) => l.includes("いちばん"))).toBe(false);
  });
  it("全国の上位100位に入る市区町村は、全国の市区町村が200より多いときだけ書く", () => {
    const many = Array.from({ length: 300 }, (_, i) => row(`muni-99${String(i).padStart(3, "0")}`, 5 - i / 100));
    const big = (_id: string, _p: string, chunk: "municipalities" | "prefectures") => chunk === "municipalities" ? [...national, ...many] : [];
    const rr = prefIndicatorRanking(ind("aged_65_plus_share"), "28", munis, big)!;
    const lines = prefIndicatorFacts({ pref: "兵庫県", ind: ind("aged_65_plus_share"), page, ranking: rr, cities: [] });
    expect(lines.at(-1)).toMatch(/^全国308市区町村の中で上位100位に入るのは、/);
    expect(prefIndicatorFacts({ pref: "兵庫県", ind: ind("aged_65_plus_share"), page, ranking: r, cities: [] }).join(""))
      .not.toContain("上位100位");
  });
  it("説明文は県内の1〜3位の名前から始め、120字に収める", () => {
    const d = prefIndicatorDescription({ pref: "兵庫県", ind: ind("aged_65_plus_share"), page, ranking: r, cities: [], year: "2025年" });
    expect(d).toMatch(/^兵庫県の高齢化率（65歳以上の割合）の市区町村ランキング（2025年）。1位は町2・町3（45.0%）、3位は町1。/);
    expect(d).toContain("県内6市区町村の全順位");
    expect(d.length).toBeLessThanOrEqual(DESCRIPTION_MAX);
  });
});

describe("政令指定都市を1つの市として数える（人口、#246）", () => {
  const pop = ind("population_total", { name: "人口", unit: "人", kind: "count", digits: 0 } as Partial<Indicator>);
  const popPage = PREF_INDICATOR_PAGES.find((p) => p.id === "population_total")!;
  const kanagawa = [
    muni("14101", "横浜市鶴見区", "横浜市"), muni("14102", "横浜市神奈川区", "横浜市"),
    muni("14131", "川崎市川崎区", "川崎市"), muni("14132", "川崎市幸区", "川崎市"),
    muni("14205", "藤沢市"), muni("14201", "横須賀市"), muni("14204", "鎌倉市"), muni("14206", "小田原市"), muni("14382", "箱根町"),
  ];
  const all = [...kanagawa, muni("27127", "大阪市北区", "大阪市"), muni("27128", "大阪市都島区", "大阪市"), muni("13101", "千代田区", "区部")];
  const vals: Record<string, ValueRow[]> = {
    municipalities: [
      row("muni-14101", 300), row("muni-14102", 250), row("muni-14131", 230), row("muni-14132", 170),
      row("muni-14205", 440), row("muni-14201", 380), row("muni-14204", 170), row("muni-14206", 180), row("muni-14382", 10),
      row("muni-27127", 150), row("muni-27128", 110), row("muni-13101", 70),
    ],
    prefectures: [],
  };
  const popRows = (_id: string, _p: string, chunk: "municipalities" | "prefectures") => vals[chunk];
  const cities = designatedCities(all);

  it("区を合計した市を県内・全国の順位に入れ、区は別に値の大きい順に並べる", () => {
    const r = prefIndicatorRanking(pop, "14", kanagawa, popRows, cities)!;
    expect(r.rows.map((x) => [x.muni.name, x.value, x.rank, x.national?.rank])).toEqual([
      ["横浜市", 550, 1, 1], ["藤沢市", 440, 2, 2], ["川崎市", 400, 3, 3], ["横須賀市", 380, 4, 4],
      ["小田原市", 180, 5, 6], ["鎌倉市", 170, 6, 7], ["箱根町", 10, 7, 9],
    ]);
    expect(r.rows[0].national?.total).toBe(9);
    expect(r.rows[0].city?.wards).toEqual(["muni-14101", "muni-14102"]);
    expect(r.wards.map((x) => x.muni.name)).toEqual(["横浜市鶴見区", "横浜市神奈川区", "川崎市川崎区", "川崎市幸区"]);
    const lines = prefIndicatorFacts({ pref: "神奈川県", ind: pop, page: popPage, ranking: r, cities: [] });
    expect(lines[0]).toBe("神奈川県の7市区町村のうち、1位は横浜市（550人）、2位は藤沢市（440人）、3位は川崎市（400人）です。");
    expect(lines.at(-1)).toBe("政令指定都市の横浜市・川崎市は、区の合計を1つの市として数えています。");
  });
  it("値のない区が1つでもある市は値なしにし（0 にしない）、区の行がひとつもない市も値のない市区町村に並べる", () => {
    const gap = (_id: string, _p: string, chunk: "municipalities" | "prefectures") => chunk === "prefectures" ? [] :
      vals.municipalities.map((x) => x.entity_id === "muni-14102" ? row("muni-14102", null) : x).filter((x) => !x.entity_id.startsWith("muni-1413"));
    const r = prefIndicatorRanking(pop, "14", kanagawa, gap, cities)!;
    expect(r.rows.some((x) => x.city)).toBe(false);
    expect(r.missing.map((x) => [x.muni.name, x.value])).toEqual([["横浜市", null], ["川崎市", null]]);
  });
  it("cities を渡さない指標は、これまでどおり区ごとに並べる", () => {
    const r = prefIndicatorRanking(pop, "14", kanagawa, popRows)!;
    expect(r.rows[0].muni.name).toBe("藤沢市");
    expect(r.wards).toEqual([]);
  });
});
