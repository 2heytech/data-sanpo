import { describe, expect, it } from "vitest";
import { fallbackView, type MapFallbackData } from "../src/lib/mapFallback";

const DATA: MapFallbackData = {
  default: "population_total",
  indicators: {
    population_total: { name: "人口", image: { path: "/images/indicators/population_total.png", alt: "全国の市区町村別の人口（2025年）を色分けした地図" } },
    aging_rate: { name: "高齢化率", image: { path: "/images/indicators/aging_rate.png", alt: "全国の市区町村別の高齢化率（2020年）を色分けした地図" } },
    crime_rate: { name: "刑法犯の認知件数" },
  },
  prefectures: { "01": "北海道", "13": "東京都" },
  municipalities: { "muni-13104": "新宿区", "muni-01101": "札幌市中央区" },
};

describe("地図を表示できないときの案内", () => {
  it("URL に何もなければ、地図の既定の指標のページと画像", () => {
    expect(fallbackView({}, DATA)).toEqual({
      links: [{ href: "/indicators/population_total/", text: "「人口」のランキング", note: "全国の順位の表と、指標の意味・出典" }],
      image: { path: "/images/indicators/population_total.png", alt: "全国の市区町村別の人口（2025年）を色分けした地図", href: "/indicators/population_total/" },
    });
  });

  it("選んでいた指標のページと画像にする", () => {
    const view = fallbackView({ indicator: "aging_rate" }, DATA);
    expect(view.links.map((l) => l.href)).toEqual(["/indicators/aging_rate/"]);
    expect(view.image?.path).toBe("/images/indicators/aging_rate.png");
  });

  it("画像がない指標は、リンクはその指標、画像は既定の指標のもの", () => {
    const view = fallbackView({ indicator: "crime_rate" }, DATA);
    expect(view.links[0].text).toBe("「刑法犯の認知件数」のランキング");
    expect(view.image?.href).toBe("/indicators/population_total/");
  });

  it("知らない指標の ID は既定の指標として扱う", () => {
    expect(fallbackView({ indicator: "no_such" }, DATA).links[0].href).toBe("/indicators/population_total/");
  });

  it("選んでいた都道府県・市区町村のページを足す", () => {
    expect(fallbackView({ area: "pref-13" }, DATA).links[1]).toMatchObject({ href: "/prefectures/13/", text: "東京都のデータ" });
    expect(fallbackView({ area: "muni-01101" }, DATA).links[1]).toMatchObject({
      href: "/areas/muni-01101/", text: "北海道札幌市中央区のデータ", note: "データで見た特徴と、主な指標の全国順位",
    });
  });

  it("町丁・字等はページがないので、その市区町村のページにする", () => {
    expect(fallbackView({ area: "area-13104001001" }, DATA).links[1]).toMatchObject({
      href: "/areas/muni-13104/", text: "東京都新宿区のデータ", note: "選んでいた町丁目がある市区町村のページ",
    });
  });

  it("名前の分からない地域はリンクにしない", () => {
    expect(fallbackView({ area: "muni-99999" }, DATA).links).toHaveLength(1);
    expect(fallbackView({ area: "pref-99" }, DATA).links).toHaveLength(1);
  });
});
