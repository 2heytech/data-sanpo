import { describe, expect, it } from "vitest";
import { indicatorPageText } from "../src/lib/indicatorPage";
import type { Indicator } from "../src/lib/types";

const period = (p: string, label: string) => ({ period: p, label, aggregate: undefined }) as unknown as Indicator["periods"][number];
const elections = [
  period("2024-10-27", "2024年10月 衆院選（比例）"),
  period("2025-07-20", "2025年7月 参院選（比例）"),
  period("2026-02-08", "2026年2月 衆院選（比例）"),
];
const vote = (party: string) => ({
  id: "vote_share_x", name: `比例代表の得票率（${party}）`, unit: "%",
  description: "有効投票のうちその政党が得た票の割合。", periods: elections,
}) as unknown as Indicator;
const national = { muniCount: 1700, hasMuniValues: true, hasPrefRows: true, nationwide: true, partial: false };

describe("indicatorPageText", () => {
  it("比例代表の得票率は政党名から始まる題名にする", () => {
    const t = indicatorPageText(vote("れいわ新選組"), national);
    expect(t.title).toBe("れいわ新選組の得票率 都道府県別・市区町村別ランキング（比例代表）");
    expect(t.description).toBe(
      "れいわ新選組の比例代表の得票率を、都道府県別と全国の市区町村別のランキングで紹介"
      + "（2024年10月 衆院選・2025年7月 参院選・2026年2月 衆院選）。意味・計算方法・出典つき。有効投票のうちその政党が得た票の割合。",
    );
  });
  it("正式名に略称を含まない政党は、題名に略称を使い、説明文に両方を書く", () => {
    const t = indicatorPageText(vote("自由民主党"), national);
    expect(t.title).toBe("自民党の得票率 都道府県別・市区町村別ランキング（比例代表）");
    expect(t.description.startsWith("自由民主党（自民党）の比例代表の得票率を、")).toBe(true);
    expect(indicatorPageText(vote("社会民主党"), national).title.startsWith("社民党の得票率")).toBe(true);
    expect(indicatorPageText(vote("日本共産党"), national).title.startsWith("日本共産党の得票率")).toBe(true);
  });
  it("市区町村の値がない得票率は都道府県別の題名にする", () => {
    const t = indicatorPageText(vote("参政党"), { ...national, muniCount: 0, hasMuniValues: false });
    expect(t.title).toBe("参政党の得票率 都道府県別（比例代表）");
    expect(t.description).toContain("を、都道府県別の値で紹介");
  });
  it("選挙以外の指標は今までどおり", () => {
    const pop = { id: "population_total", name: "人口", unit: "人", description: "常住人口。", periods: [] } as unknown as Indicator;
    expect(indicatorPageText(pop, national)).toEqual({
      title: "人口の市区町村ランキング（全国）",
      description: "人口（人）の全国の市区町村ランキングと都道府県別の値。意味・計算方法・出典つき。常住人口。",
    });
    expect(indicatorPageText(pop, { ...national, partial: true, hasPrefRows: false }).title).toBe("人口の市区町村ランキング");
    expect(indicatorPageText(pop, { ...national, muniCount: 0, hasMuniValues: false }).title).toBe("人口");
  });
});
