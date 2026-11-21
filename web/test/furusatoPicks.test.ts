import { describe, expect, it } from "vitest";
import {
  PICK_INDICATORS, furusatoAmountText, furusatoAreaLead, furusatoPicks, furusatoPrefLead, pickLead,
} from "../src/lib/furusatoPicks";
import { rakutenFurusatoSearchUrl } from "../src/lib/rakuten";

describe("楽天ふるさと納税の上位のまちのリンク（#252）", () => {
  it("受入額を億円・万円で書く", () => {
    expect(furusatoAmountText(21646.4)).toBe("約216億円");
    expect(furusatoAmountText(378.18)).toBe("約3.8億円");
    expect(furusatoAmountText(400)).toBe("約4億円");
    expect(furusatoAmountText(25.3)).toBe("約2,530万円");
    expect(furusatoAmountText(0)).toBeNull();
    expect(furusatoAmountText(null)).toBeNull();
  });

  it("地域ページの1文は、上位のときだけ順位を書く", () => {
    const base = { name: "都城市", prefName: "宮崎県", value: 21646.4, periodLabel: "2025年度" };
    expect(furusatoAreaLead({ ...base, national: { rank: 3, total: 1720 }, inPref: { rank: 1, total: 26 } }))
      .toBe("都城市のふるさと納税の受入額は約216億円で、全国1,720市区町村のうち3位です（2025年度）。");
    expect(furusatoAreaLead({ ...base, national: { rank: 240, total: 1720 }, inPref: { rank: 2, total: 26 } }))
      .toBe("都城市のふるさと納税の受入額は約216億円で、宮崎県の26市区町村のうち2位です（2025年度）。");
    expect(furusatoAreaLead({ ...base, national: { rank: 900, total: 1720 }, inPref: { rank: 12, total: 26 } }))
      .toBe("都城市のふるさと納税の受入額は約216億円です（2025年度）。");
    expect(furusatoAreaLead({ ...base, value: null, national: null, inPref: null })).toBeNull();
  });

  it("都道府県ページの1文は、県（都・道・府）と県内の合計と書き、10位までだけ順位を書く", () => {
    expect(furusatoPrefLead({ prefName: "宮崎県", value: 62467.1, periodLabel: "2025年度", standing: { rank: 2, total: 47 } }))
      .toBe("宮崎県（県と県内の市区町村の合計）のふるさと納税の受入額は約625億円で、都道府県の2位です（2025年度）。");
    expect(furusatoPrefLead({ prefName: "東京都", value: 5000, periodLabel: "2025年度", standing: { rank: 30, total: 47 } }))
      .toBe("東京都（都と都内の市区町村の合計）のふるさと納税の受入額は約50億円です（2025年度）。");
  });

  it("箱の説明は、検索に足す言葉があればその品の返礼品と書く", () => {
    expect(pickLead("果実の産出額", PICK_INDICATORS.agri_output_fruits, 10))
      .toBe("果実の産出額の上位10の市町村で、果物の返礼品を楽天ふるさと納税で探せます。");
    expect(pickLead("農業産出額", PICK_INDICATORS.agri_output, 6, "宮崎県の"))
      .toBe("宮崎県の農業産出額の上位6の市町村の返礼品を、楽天ふるさと納税で探せます。");
  });

  it("検索に言葉を足せる・都道府県だけでも探せる", () => {
    expect(decodeURIComponent(rakutenFurusatoSearchUrl("青森県", "弘前市", "果物"))).toContain("ふるさと納税 果物 青森県弘前市");
    expect(decodeURIComponent(rakutenFurusatoSearchUrl("宮崎県", ""))).toContain("/ふるさと納税 宮崎県/");
  });

  it("アフィリエイトID がなければリンクを作らない", () => {
    expect(furusatoPicks([{ label: "1位", name: "都城市", pref: "宮崎県" }])).toEqual([]);
  });
});
