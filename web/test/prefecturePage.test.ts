import { describe, expect, it } from "vitest";
import {
  prefRanking, prefectureDescription, prefectureFocus, prefectureGrowth, prefectureHistory, prefectureLead, prefectureNeighbors, wardCitiesOf,
} from "../src/lib/prefecturePage";
import { DESCRIPTION_MAX, areaDescription, formerWard } from "../src/lib/areaSummary";
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
      "北海道には188の市区町村があります（札幌市は区ごとに数えています）。",
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
  const base = { name: "飛島村", pref: "愛知県", population: { text: "4,000人", label: "2025年10月1日現在" }, statCount: 120 };
  const tail = "人口・暮らし・産業など120の指標の全国順位を、となりのまちと比べられます。";
  it("特徴の一言と、いちばん目立つ考察の数字から始め、人口と締めを付ける", () => {
    expect(areaDescription({ ...base, title: "財政の豊かなまち", insights: ["財政力指数は2.10で、全国1,700市区町村のうち1位です（2023年度、3市区町村が同じ値）。豊かなまちと考えられます。"] }))
      .toBe(`飛島村（愛知県）をデータで見ると「財政の豊かなまち」。財政力指数は2.10で、全国1位です（2023年度）。人口4,000人（2025年）。${tail}`);
  });
  it("特徴の一言がないときは名前から始め、日付は年だけにする", () => {
    expect(areaDescription({ ...base, title: null, insights: ["大学・大学院卒の割合は67.1%で、全国1,895市区町村の中で低い方から3番目です（2020年10月1日現在）。"] }))
      .toBe(`飛島村（愛知県）のデータ。大学・大学院卒の割合は67.1%で、全国で低い方から3番目です（2020年）。人口4,000人（2025年）。${tail}`);
  });
  it("同じ値が10以上ある順位の考察は使わず、次の考察から始める", () => {
    const tie = "交通事故の件数は0.00件/100人で、全国1,895市区町村の中で最も低い値です（2025年、70市区町村が同じ値）。";
    expect(areaDescription({ ...base, title: null, insights: [tie, "面積は全国で最も小さい方です。"] }))
      .toBe(`飛島村（愛知県）のデータ。面積は全国で最も小さい方です。人口4,000人（2025年）。${tail}`);
  });
  it("締めは120字に収まるものを選び、どれも収まらなければ付けない。今はない区は注記を入れる", () => {
    const d = areaDescription({ ...base, title: "財政の豊かなまち", insights: [`${"あ".repeat(48)}です。`] });
    expect(d.endsWith("人口4,000人（2025年）。120の指標の全国順位を紹介。")).toBe(true);
    expect(d.length).toBeLessThanOrEqual(DESCRIPTION_MAX);
    const long = areaDescription({ ...base, title: "財政の豊かなまち", insights: [`${"あ".repeat(80)}です。`] });
    expect(long.endsWith("人口4,000人（2025年）。")).toBe(true);
    expect(areaDescription({ ...base, name: "浜松市中区", pref: "静岡県", title: null, insights: [], note: formerWard("muni-22131")!.note }))
      .toBe(`浜松市中区（静岡県）のデータ。2024年1月の区の再編の前の区です。人口4,000人（2025年）。${tail}`);
    expect(formerWard("muni-22138")).toBeNull();
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

describe("prefectureNeighbors", () => {
  const m = (id: string, neighbors: string[]) => ({ id, prefecture: id.slice(5, 7), neighbors }) as unknown as Municipality;
  it("市区町村の隣からほかの都道府県を拾い、海をへだてた組を加える", () => {
    const munis = [m("muni-01100", []), m("muni-02201", ["muni-03201"]), m("muni-03201", ["muni-02201"]), m("muni-04100", [])];
    const n = prefectureNeighbors(munis);
    expect(n.get("01")).toEqual([{ code: "02", sea: true }]);
    expect(n.get("02")).toEqual([{ code: "01", sea: true }, { code: "03", sea: false }]);
    expect(n.get("04")).toEqual([]);
  });
  it("公開版にない都道府県は加えない", () => {
    expect(prefectureNeighbors([m("muni-01100", [])]).get("01")).toEqual([]);
  });
});

describe("prefectureDescription", () => {
  it("特徴の一言と、いちばん目立つ考察から始め、県内の市区町村と指標の数で締める", () => {
    expect(prefectureDescription({ name: "北海道", title: "面積の広い北海道", insights: ["面積は83,422.27km²で、全国の都道府県で最も広くなっています（2025年10月1日現在）。広い土地です。"], muniCount: 188, top3: "札幌市中央区・旭川市", statCount: 150 }))
      .toBe("北海道をデータで見ると「面積の広い北海道」。面積は83,422.27km²で、全国の都道府県で最も広くなっています（2025年）。道内188市区町村（札幌市中央区・旭川市など）の人口ランキングと、150の指標の全国順位が分かります。");
  });
  it("120字を超えるときは市区町村の名前を入れない", () => {
    const d = prefectureDescription({ name: "東京都", title: "働く世代の多い東京都", insights: [`${"あ".repeat(50)}です。`], muniCount: 62, top3: "世田谷区・練馬区・大田区", statCount: 150 });
    expect(d.endsWith("都内62市区町村の人口ランキングと、150の指標の全国順位が分かります。")).toBe(true);
  });
});

describe("都道府県ページの概要に足す文（設計変更記録 #163）", () => {
  const munis = [muni("99101", "大市北区", "大市"), muni("99102", "大市南区", "大市"), muni("99201", "小市"), muni("99202", "東町"), muni("99203", "西村")];
  const rows = (values: (number | null)[]) => values.map((v, i) => row(munis[i].id, v));
  it("いちばん人口の多い市（政令指定都市は区を合わせる）に住む割合と、卸売業の販売額でも中心なら、その割合を書く", () => {
    expect(prefectureFocus("テスト県", munis, { rows: rows([300, 200, 100, 100, 100]), label: "2025年10月1日現在" },
      { rows: rows([700, 100, 100, 50, 50]), label: "2020年" }))
      .toBe("いちばん人口の多い大市に、県の人口の63%が住んでいます（2025年10月1日現在）。卸売業の販売額では、県内の合計の80%を大市が占めています（2020年）。");
    // 卸売業の販売額に値のない市区町村があるとき（秘匿など）は、県全体が分からないので書かない（0 として扱わない）
    expect(prefectureFocus("テスト県", munis, { rows: rows([300, 200, 100, 100, 100]), label: "2025年10月1日現在" },
      { rows: rows([700, 100, 100, null, 50]), label: "2020年" }))
      .toBe("いちばん人口の多い大市に、県の人口の63%が住んでいます（2025年10月1日現在）。");
    // 人口が分散している県（いちばん多い市区町村でも15%未満）と、市区町村が3つより少ない県は書かない
    const many = Array.from({ length: 10 }, (_, i) => muni(`99${300 + i}`, `町${i}`));
    expect(prefectureFocus("テスト県", many, { rows: many.map((m, i) => row(m.id, 100 + i)), label: "" }, null)).toBeNull();
    expect(prefectureFocus("テスト県", munis.slice(0, 3), { rows: rows([300, 200, 100]), label: "" }, null)).toBeNull();
  });
  it("5年前より人口が増えた市区町村を、増え方の大きい順に5つまで挙げる（1つもないときは書かない）", () => {
    expect(prefectureGrowth(munis, { rows: rows([1.2, -1, -2, -3, -4]) })).toBe("5年前より人口が増えたのは大市北区だけです。");
    expect(prefectureGrowth(munis, { rows: rows([1.2, 3.4, -2, null, 0.1]) })).toBe("5年前より人口が増えたのは、大市南区・大市北区・西村の3市区町村です。");
    expect(prefectureGrowth(munis, { rows: rows([-1, -1, -2, -3, -4]) })).toBeNull();
  });
  it("1920年からの100年の人口と、いちばん多かった年を書く（考察に同じ移り変わりの文があるときは書かない）", () => {
    const series = [{ year: 1920, value: 100, text: "100人" }, { year: 1955, value: 150, text: "150人" }, { year: 2020, value: 120, text: "120人" }];
    expect(prefectureHistory(series, 2.3)).toBe("国勢調査が始まった1920年の人口は100人で、2020年は120人です（全国は100年で約2.3倍）。いちばん多かったのは1955年の150人です。");
    expect(prefectureHistory(series, 2.3, true)).toBeNull();
  });
});
