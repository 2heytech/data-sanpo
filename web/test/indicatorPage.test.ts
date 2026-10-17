import { describe, expect, it } from "vitest";
import { indicatorPageText, rankingYear } from "../src/lib/indicatorPage";
import type { Indicator } from "../src/lib/types";

const period = (p: string, label: string, aggregate?: boolean) =>
  ({ period: p, label, aggregate }) as unknown as Indicator["periods"][number];
const elections = [
  period("2024-10-27", "2024年10月 衆院選（比例）"),
  period("2025-07-20", "2025年7月 参院選（比例）"),
  period("2026-02-08", "2026年2月 衆院選（比例）"),
];
const vote = (party: string) => ({
  id: "vote_share_x", name: `比例代表の得票率（${party}）`, unit: "%",
  description: "有効投票のうちその政党が得た票の割合。", periods: elections, default_period: "2026-02-08",
}) as unknown as Indicator;
const national = { muniCount: 1700, hasMuniValues: true, hasPrefRows: true, nationwide: true, partial: false };
const withPeriod = (label: string, extra: Partial<Indicator> = {}) => ({
  id: "x", name: "人口", unit: "人", description: "常住人口。", periods: [period("p", label)], default_period: "p", ...extra,
}) as unknown as Indicator;

describe("rankingYear", () => {
  it("ランキングの時点の年を取り出す", () => {
    expect(rankingYear(withPeriod("2020年10月1日現在"))).toBe("2020年");
    expect(rankingYear(withPeriod("2023年度"))).toBe("2023年度");
    expect(rankingYear(withPeriod("2024年度（9月実施）"))).toBe("2024年度");
    expect(rankingYear(withPeriod("2019〜2023年の合計"))).toBe("2019〜2023年");
    expect(rankingYear(withPeriod("2026年2月 衆院選（比例）"))).toBe("2026年衆院選");
    expect(rankingYear(withPeriod("2025年7月 参院選（比例）"))).toBe("2025年参院選");
  });
  it("年で始まらない時点と、公開の年度は入れない", () => {
    expect(rankingYear(withPeriod("現存植生図2024"))).toBeNull();
    expect(rankingYear(withPeriod("2024年度公開"))).toBeNull();
  });
});

describe("indicatorPageText", () => {
  it("比例代表の得票率は政党名から始まる題名にし、ランキングの選挙を添える", () => {
    const t = indicatorPageText(vote("れいわ新選組"), national);
    expect(t.title).toBe("れいわ新選組の得票率 都道府県別・市区町村別ランキング（2026年衆院選・比例代表）");
    expect(t.description).toBe(
      "れいわ新選組の比例代表の得票率を、都道府県別と全国の市区町村別のランキングで紹介"
      + "（2024年10月 衆院選・2025年7月 参院選・2026年2月 衆院選）。意味・計算方法・出典つき。有効投票のうちその政党が得た票の割合。",
    );
  });
  it("正式名に略称を含まない政党は、題名に略称を使い、説明文に両方を書く", () => {
    const t = indicatorPageText(vote("自由民主党"), national);
    expect(t.title.startsWith("自民党の得票率 都道府県別・市区町村別ランキング")).toBe(true);
    expect(t.description.startsWith("自由民主党（自民党）の比例代表の得票率を、")).toBe(true);
    expect(indicatorPageText(vote("社会民主党"), national).title.startsWith("社民党の得票率")).toBe(true);
    expect(indicatorPageText(vote("日本共産党"), national).title.startsWith("日本共産党の得票率")).toBe(true);
  });
  it("市区町村の値がない得票率は都道府県別の題名にする", () => {
    const t = indicatorPageText(vote("参政党"), { ...national, muniCount: 0, hasMuniValues: false });
    expect(t.title).toBe("参政党の得票率 都道府県別（2026年衆院選・比例代表）");
    expect(t.description).toContain("を、都道府県別の値で紹介");
  });
  it("ほかの指標は、都道府県別の表があればそう書き、ランキングの年を添える", () => {
    const pop = withPeriod("2020年10月1日現在");
    expect(indicatorPageText(pop, national)).toEqual({
      title: "人口 都道府県別・市区町村別ランキング（2020年）",
      description: "人口の全国の市区町村ランキングと都道府県別の値（2020年10月1日現在、単位: 人）。意味・計算方法・出典つき。常住人口。",
    });
    expect(indicatorPageText(pop, { ...national, hasPrefRows: false }).title).toBe("人口の市区町村ランキング（全国・2020年）");
    expect(indicatorPageText(pop, { ...national, partial: true, hasPrefRows: false }).title).toBe("人口の市区町村ランキング（2020年）");
    expect(indicatorPageText(pop, { ...national, muniCount: 0, hasMuniValues: false }).title).toBe("人口 都道府県別ランキング（2020年）");
    expect(indicatorPageText(pop, { ...national, muniCount: 0, hasMuniValues: false, hasPrefRows: false }).title).toBe("人口");
    const plain = withPeriod("現存植生図2024");
    expect(indicatorPageText(plain, { ...national, hasPrefRows: false }).title).toBe("人口の市区町村ランキング（全国）");
  });

  it("説明文で括弧を重ねない（単位は時点の括弧に入れ、時点の中の括弧は「・」にする）", () => {
    const crime = withPeriod("2025年度（4月実施）", { name: "認知件数（住民100人当たり）", unit: "件/100人" });
    expect(indicatorPageText(crime, { ...national, muniCount: 0, hasMuniValues: false }).description)
      .toBe("認知件数（住民100人当たり）の都道府県別の値（2025年度・4月実施、単位: 件/100人）。意味・計算方法・出典つき。常住人口。");
    expect(indicatorPageText(withPeriod("2020年", { unit: "" }), national).description)
      .toBe("人口の全国の市区町村ランキングと都道府県別の値（2020年）。意味・計算方法・出典つき。常住人口。");
  });
});
