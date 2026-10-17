import { describe, expect, it } from "vitest";
import { prefRanking, prefectureLead, wardCitiesOf } from "../src/lib/prefecturePage";
import { areaDescription } from "../src/lib/areaSummary";
import { breadcrumbList, indicatorDataset } from "../src/lib/structured";
import type { Indicator, Municipality, Source, ValueRow } from "../src/lib/types";

const muni = (code: string, name: string, region: string | null = null) =>
  ({ id: `muni-${code}`, name, prefecture: code.slice(0, 2), region }) as Municipality;
const period = (p: string, label: string, levels: string[] = ["municipality", "prefecture"]) =>
  ({ period: p, period_end: p, period_kind: "point", label, levels, boundary_version: "", source_ids: ["census_2020"] });
const ind = (id: string, periods = [period("2020-10-01", "2020年")]) =>
  ({ id, name: "人口密度", category: "人口", unit: "人/km²", kind: "density", digits: 1, default_period: "2020-10-01",
    description: "1平方キロメートルあたりの人口です。", method: "人口 ÷ 面積", caveats: [], periods,
    legend: { method: "quantile", classes: 7, scheme: "blues" } }) as unknown as Indicator;
const row = (id: string, value: number | null): ValueRow => ({ entity_id: id, value, status: value === null ? "missing" : "observed" });

describe("prefRanking", () => {
  const munis = ["01", "02", "03", "04", "05", "06"].map((c) => muni(`13${c}0`, `市${c}`));
  const values: Record<string, ValueRow[]> = {
    "municipalities": [row("muni-13010", 10), row("muni-13020", 30), row("muni-13030", 30), row("muni-13040", null),
      row("muni-13050", 5), row("muni-13060", 1), row("muni-13070", 2), row("muni-27100", 999)],
    "prefectures": [row("pref-13", 12.5), row("pref-27", 50)],
  };
  const rows = (_id: string, _p: string, chunk: "municipalities" | "prefectures") => values[chunk];

  it("県内の値の大きい順に5位まで並べ、値のない市区町村は除き、同じ値は同じ順位にする", () => {
    const r = prefRanking(ind("population_density"), "13", munis, rows)!;
    expect(r.items.map((i) => [i.muni.name, i.rank])).toEqual([["市02", 1], ["市03", 1], ["市01", 3], ["市05", 4], ["市06", 5]]);
    expect(r.prefText).toBe("12.5 人/km²");
  });
  it("県内に値のある市区町村が5つより少ないとき・値がすべて同じときは出さない", () => {
    const few = (_id: string, _p: string, chunk: "municipalities" | "prefectures") =>
      chunk === "municipalities" ? values.municipalities.slice(0, 4) : [];
    expect(prefRanking(ind("population_density"), "13", munis, few)).toBeNull();
    const same = (_id: string, _p: string, chunk: "municipalities" | "prefectures") =>
      chunk === "municipalities" ? munis.map((m) => row(m.id, 7)) : [];
    expect(prefRanking(ind("population_density"), "13", munis, same)).toBeNull();
  });
  it("国勢調査の新しい回（2025年）に市区町村の値があれば、そちらで並べる", () => {
    const i = ind("population_density", [period("2020-10-01", "2020年"), period("2025-10-01", "2025年")]);
    const seen: string[] = [];
    const r = prefRanking(i, "13", munis, (_id, p, chunk) => { seen.push(p); return values[chunk]; })!;
    expect(r.period.label).toBe("2025年");
    expect(seen[0]).toBe("2025-10-01");
  });
});

describe("prefectureLead", () => {
  it("人口・全国の順位・5年間の増減と、市区町村の数を書く", () => {
    const lines = prefectureLead("東京都", { text: "14,000,000 人", label: "2025年", rank: 1, total: 47 },
      { value: 3.25, label: "2025年" }, 62, []);
    expect(lines[0]).toBe("東京都の人口は14,000,000 人（2025年）で、全国47都道府県のうち最も多い都道府県です。5年前と比べて3.3%増えています。");
    expect(lines[1]).toMatch(/^東京都には62の市区町村があります。/);
  });
  it("減っているときは事実だけを書き、ほぼ0なら変わっていないと書く。政令指定都市の区の数え方を添える", () => {
    expect(prefectureLead("秋田県", { text: "900,000 人", label: "2025年", rank: 38, total: 47 }, { value: -6.21, label: "2025年" }, 25, [])[0])
      .toBe("秋田県の人口は900,000 人（2025年）で、全国47都道府県のうち少ない方から10番目の都道府県です。5年前と比べて6.2%減っています。");
    expect(prefectureLead("A県", { text: "1 人", label: "2025年", rank: 2, total: 47 }, { value: -0.02, label: "2025年" }, 3, [])[0])
      .toMatch(/5年前からほとんど変わっていません。$/);
    expect(prefectureLead("北海道", null, null, 188, ["札幌市"])).toEqual([
      "北海道には188の市区町村があります（札幌市は区ごとに数えています）。下の表では、それぞれの人口と、データから見た特徴の一言を並べています。市区町村名から、くわしいデータと順位のページを開けます。",
    ]);
  });
});

describe("wardCitiesOf", () => {
  it("政令指定都市の区だけを拾い、東京都の区部・多摩は含めない", () => {
    expect(wardCitiesOf([muni("01101", "札幌市中央区", "札幌市"), muni("01102", "札幌市北区", "札幌市"), muni("01202", "函館市"),
      muni("13101", "千代田区", "区部"), muni("13201", "八王子市", "多摩")])).toEqual(["札幌市"]);
  });
});

describe("areaDescription", () => {
  const base = { name: "飛島村", place: "愛知県", pref: "愛知県", population: "4,000 人（2025年）", statCount: 120 };
  it("特徴の一言と、いちばん目立つ考察から始める", () => {
    expect(areaDescription({ ...base, title: "財政の豊かなまち", firstInsight: "財政力指数は全国1位です。" }))
      .toBe("飛島村（愛知県）をデータで見ると「財政の豊かなまち」。財政力指数は全国1位です。人口は4,000 人（2025年）。愛知県内・全国の順位など120の指標を、となりの市区町村との比較と出典つきで紹介。");
  });
  it("考察が長いときは最初の文だけにし、特徴の一言がないときは名前から始める", () => {
    const long = `財政力指数は全国1位です。${"あ".repeat(120)}と考えられます。`;
    expect(areaDescription({ ...base, title: null, firstInsight: long }))
      .toBe("飛島村（愛知県）のデータ。財政力指数は全国1位です。人口は4,000 人（2025年）。愛知県内・全国の順位など120の指標を、となりの市区町村との比較と出典つきで紹介。");
  });
});

describe("structured data", () => {
  const site = new URL("https://data-sanpo.com");
  it("パンくずは最後の項目（今のページ）に URL を付けない", () => {
    const b = breadcrumbList(site, [{ name: "データさんぽ", path: "/" }, { name: "東京都", path: "/prefectures/13/" }, { name: "新宿区" }]);
    expect(b.itemListElement).toEqual([
      { "@type": "ListItem", position: 1, name: "データさんぽ", item: "https://data-sanpo.com/" },
      { "@type": "ListItem", position: 2, name: "東京都", item: "https://data-sanpo.com/prefectures/13/" },
      { "@type": "ListItem", position: 3, name: "新宿区" },
    ]);
  });
  it("指標の Dataset に、ライセンス・期間・出典・データのファイルを入れる", () => {
    const i = ind("population_density", [period("2015-10-01", "2015年"), period("2020-10-01", "2020年")]);
    const src = { source_id: "census_2020", title: "令和2年国勢調査", provider: "総務省統計局", url: "https://www.e-stat.go.jp/" } as Source;
    const d = indicatorDataset(site, i, "/indicators/population_density/", [src], "/data/r1/values/population_density/2020-10-01/municipalities.json", ["都道府県", "市区町村"]);
    expect(d).toMatchObject({
      "@type": "Dataset", name: "人口密度", url: "https://data-sanpo.com/indicators/population_density/",
      license: "https://creativecommons.org/licenses/by/4.0/", temporalCoverage: "2015/2020",
      isBasedOn: [{ "@type": "CreativeWork", name: "令和2年国勢調査", url: "https://www.e-stat.go.jp/", publisher: { "@type": "Organization", name: "総務省統計局" } }],
      distribution: [{ "@type": "DataDownload", encodingFormat: "application/json",
        contentUrl: "https://data-sanpo.com/data/r1/values/population_density/2020-10-01/municipalities.json" }],
    });
    // Google は説明に50字以上を求める
    expect((d.description as string).length).toBeGreaterThanOrEqual(50);
  });
});
