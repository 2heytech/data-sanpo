import { describe, expect, it } from "vitest";
import { detailPageLinks, pageLinksHtml } from "../src/map/pageLinks";

describe("detailPageLinks", () => {
  const indicator = { id: "population_total", name: "人口" };
  it("選んだ市区町村・都道府県のページと、指標のランキングのページを近い順に並べる", () => {
    const links = detailPageLinks({
      municipality: { id: "muni-28202", name: "尼崎市" }, prefecture: { code: "28", name: "兵庫県" }, indicator, prefectureOnly: false,
    });
    expect(links.map((l) => [l.href, l.title])).toEqual([
      ["/areas/muni-28202/", "尼崎市のページ"],
      ["/prefectures/28/", "兵庫県のページ"],
      ["/indicators/population_total/", "人口のランキング"],
    ]);
    expect(links[2].note).toBe("全国の順位と、意味・計算方法・出典");
  });
  it("都道府県を選んだときは市区町村のページを出さず、都道府県だけの指標は「都道府県別の順位」と書く", () => {
    const links = detailPageLinks({ municipality: null, prefecture: { code: "13", name: "東京都" }, indicator, prefectureOnly: true });
    expect(links.map((l) => l.kind)).toEqual(["prefecture", "indicator"]);
    expect(links[1].note).toBe("都道府県別の順位と、意味・計算方法・出典");
  });
  it("リンクの文字は書き換えて出す", () => {
    const html = pageLinksHtml([{ href: "/indicators/x/", kind: "indicator", title: "A<B", note: "c&d" }]);
    expect(html).toContain('<a href="/indicators/x/">');
    expect(html).toContain("<strong>A&lt;B</strong><small>c&amp;d</small>");
  });
});
