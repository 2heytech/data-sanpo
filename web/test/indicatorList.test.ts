import { describe, expect, it } from "vitest";
import { listItems, listTags } from "../src/lib/indicatorList";
import type { Indicator } from "../src/lib/types";

const period = (levels: string[]) => ({ period: "2020", label: "2020年", levels }) as unknown as Indicator["periods"][number];
const ind = (id: string, name: string, category: string, extra: Partial<Indicator> = {}) => ({
  id, name, category, description: `${name}の説明。`, periods: [period(["prefecture", "municipality"])], prefectures: [], ...extra,
}) as unknown as Indicator;
const fam = (family: string, type: string, basis: string) => ({ family, facets: { type, basis } });

describe("listItems", () => {
  it("種類だけが違う指標を、まとめる組の1つの項目にし、組の順に並べる", () => {
    const list = [
      ind("hs_grad_employment_rate", "高校卒業者に占める就職者の割合", "教育"),
      ind("jhs_students_private", "私立中学校の生徒割合", "教育"),
      ind("hs_grad_university_rate", "高校卒業者の大学等進学率", "教育"),
    ];
    const items = listItems(list, "教育");
    expect(items.map((i) => i.title)).toEqual(["高校卒業者の進路", "私立中学校の生徒割合"]);
    expect(items[0].members.map((m) => m.label)).toEqual(["大学等", "就職"]);
    expect(items[0].href).toBe("/indicators/hs_grad_university_rate/");
  });

  it("組の指標が1つしかない公開版では、まとめずにその指標の項目にする", () => {
    const items = listItems([ind("hs_grad_university_rate", "高校卒業者の大学等進学率", "教育")], "教育");
    expect(items).toHaveLength(1);
    expect(items[0].title).toBe("高校卒業者の大学等進学率");
    expect(items[0].members).toHaveLength(1);
  });

  it("基準だけが違う指標は、代表の項目に基準のリンクとして付ける", () => {
    const list = [
      ind("employees_agriculture", "農林漁業で働く人の数", "農業", fam("x", "農林漁業", "人数")),
      ind("employees_agriculture_share", "農林漁業で働く人の割合", "農業", fam("x", "農林漁業", "割合")),
    ];
    const [item] = listItems(list, "農業");
    expect(item.title).toBe("農林漁業で働く人の数");
    expect(item.members[0].extras).toEqual([{ label: "割合", href: "/indicators/employees_agriculture_share/" }]);
    expect(item.ids).toEqual(["employees_agriculture", "employees_agriculture_share"]);
  });

  it("family で選ぶ組は、総数を除いた種別をまとめ、各種別の基準のリンクも残す", () => {
    const list = [
      ind("census_foreign_population", "国勢調査の外国人の数", "外国人住民", fam("census_foreign", "総数", "人数")),
      ind("census_foreign_population_share", "国勢調査の外国人の割合", "外国人住民", fam("census_foreign", "総数", "割合")),
      ind("census_foreign_china", "国勢調査の外国人の数（中国）", "外国人住民", fam("census_foreign", "中国", "人数")),
      ind("census_foreign_china_share", "国勢調査の外国人の割合（中国）", "外国人住民", fam("census_foreign", "中国", "割合")),
      ind("census_foreign_brazil", "国勢調査の外国人の数（ブラジル）", "外国人住民", fam("census_foreign", "ブラジル", "人数")),
    ];
    const items = listItems(list, "外国人住民");
    expect(items.map((i) => i.title)).toEqual(["国勢調査の外国人の数", "国勢調査の外国人の数（国籍別）"]);
    expect(items[1].members.map((m) => [m.label, m.extras.map((x) => x.label)])).toEqual([["中国", ["割合"]], ["ブラジル", []]]);
  });

  it("名前が「共通の名前（種別）」の組は、種別を1つの項目にまとめる（得票率など）", () => {
    const list = ["自由民主党", "公明党"].map((p, k) =>
      ind(`vote_share_${k}`, `比例代表の得票率（${p}）`, "選挙", fam("vote_share", p, "得票率")));
    const [item] = listItems(list, "選挙");
    expect(item.title).toBe("比例代表の得票率");
    expect(item.members.map((m) => m.label)).toEqual(["自由民主党", "公明党"]);
    expect(item.description).toContain("比例代表選挙");
  });
});

describe("listTags", () => {
  const tokyo = ind("a", "A", "緑", { prefectures: ["13"] });
  const pref = ind("b", "B", "教育", { periods: [period(["prefecture"])] });
  const byId = new Map([tokyo, pref].map((i) => [i.id, i]));
  const name = (code: string) => (code === "13" ? "東京都" : code);
  const item = (ids: string[]) => ({ title: "", href: "", description: "", members: [], ids });

  it("一部の都道府県だけの指標には地域の札、都道府県別の値だけの指標には「県別」を付ける", () => {
    expect(listTags(item(["a"]), byId, 47, name)).toEqual([{ kind: "area", text: "東京都" }]);
    expect(listTags(item(["b"]), byId, 47, name)).toEqual([{ kind: "pref", text: "県別" }]);
  });
  it("項目の一部だけが当てはまるときと、1つの都道府県だけの公開版では付けない", () => {
    expect(listTags(item(["a", "b"]), byId, 47, name)).toEqual([]);
    expect(listTags(item(["a"]), byId, 1, name)).toEqual([]);
  });
});
