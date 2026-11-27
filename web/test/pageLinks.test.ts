import { describe, expect, it } from "vitest";
import { detailPageLinks, furusatoLink, furusatoLinkHtml, pageLinksHtml } from "../src/map/pageLinks";

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

// 地図の地域の情報の欄の、楽天ふるさと納税で返礼品を探すリンク（設計変更記録 #257）
describe("furusatoLink", () => {
  const ID = "0123abcd.4567ef01.89abcdef.01234567";
  const searched = (href: string) => decodeURIComponent(new URL(href).searchParams.get("pc") ?? "");

  it("市区町村を選んだときは、都道府県名つきでその市区町村の返礼品を探す", () => {
    const link = furusatoLink(ID, { prefName: "宮崎県", municipality: { name: "都城市", region: null } })!;
    expect(link.title).toBe("都城市のふるさと納税の返礼品");
    expect(link.href.startsWith(`https://hb.afl.rakuten.co.jp/hgc/${ID}/`)).toBe(true);
    expect(searched(link.href)).toContain("ふるさと納税 宮崎県都城市");
  });
  it("政令指定都市の区は市の返礼品を探し、東京23区は区そのものを探す", () => {
    const ward = furusatoLink(ID, { prefName: "神奈川県", municipality: { name: "横浜市鶴見区", region: "横浜市" } })!;
    expect(ward.title).toBe("横浜市のふるさと納税の返礼品");
    expect(searched(ward.href)).toContain("神奈川県横浜市/");
    const tokyo = furusatoLink(ID, { prefName: "東京都", municipality: { name: "港区", region: "区部" } })!;
    expect(tokyo.title).toBe("港区のふるさと納税の返礼品");
  });
  it("都道府県を選んだときは、都道府県の中の返礼品を探す", () => {
    const link = furusatoLink(ID, { prefName: "北海道", municipality: null })!;
    expect(link.title).toBe("北海道のふるさと納税の返礼品");
    expect(searched(link.href)).toContain("ふるさと納税 北海道/");
  });
  it("アフィリエイトID がない・形が違う・都道府県が分からないときは出さない", () => {
    expect(furusatoLink("", { prefName: "宮崎県", municipality: null })).toBeNull();
    expect(furusatoLink("abc", { prefName: "宮崎県", municipality: null })).toBeNull();
    expect(furusatoLink(ID, { prefName: "", municipality: { name: "都城市", region: null } })).toBeNull();
  });
  it("別タブ・sponsored で開き、「広告」を付け、GA には地域の名前を送らない印を付ける", () => {
    const html = furusatoLinkHtml({ href: "https://hb.afl.rakuten.co.jp/x?a=1&b=2", title: "A<B" });
    expect(html).toContain('target="_blank" rel="sponsored noopener"');
    expect(html).toContain('href="https://hb.afl.rakuten.co.jp/x?a=1&amp;b=2"');
    expect(html).toContain('data-furusato-kind="map" data-track-text="地図の地域の情報"');
    expect(html).toContain("<strong>A&lt;B</strong>");
    expect(html).toContain('<span class="ad-mark">広告</span>');
  });
});
