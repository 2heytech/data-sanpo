import { describe, expect, it } from "vitest";
import { rakutenFurusatoSearchUrl } from "../src/lib/rakuten";
import { affiliateLink } from "../src/lib/rakutenUrl";

describe("楽天ふるさと納税のリンク", () => {
  it("都道府県名と市区町村名で検索する", () => {
    const url = rakutenFurusatoSearchUrl("広島県", "府中市");
    expect(url.startsWith("https://search.rakuten.co.jp/search/mall/")).toBe(true);
    expect(decodeURIComponent(url)).toContain("ふるさと納税 広島県府中市");
  });
  it("渡したアフィリエイトID でリンクにし、ID が空・形違いなら作らない（地図からも使う、#257）", () => {
    const id = "0123abcd.4567ef01.89abcdef.01234567";
    const url = rakutenFurusatoSearchUrl("宮崎県", "都城市");
    expect(affiliateLink(id, url)).toBe(`https://hb.afl.rakuten.co.jp/hgc/${id}/?pc=${encodeURIComponent(url)}&link_type=text`);
    expect(affiliateLink("", url)).toBeNull();
    expect(affiliateLink("0123abcd.4567ef01", url)).toBeNull();
  });
});
