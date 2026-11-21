import { describe, expect, it } from "vitest";
import { rakutenFurusatoSearchUrl } from "../src/lib/rakuten";

describe("楽天ふるさと納税のリンク", () => {
  it("都道府県名と市区町村名で検索する", () => {
    const url = rakutenFurusatoSearchUrl("広島県", "府中市");
    expect(url.startsWith("https://search.rakuten.co.jp/search/mall/")).toBe(true);
    expect(decodeURIComponent(url)).toContain("ふるさと納税 広島県府中市");
  });
});
