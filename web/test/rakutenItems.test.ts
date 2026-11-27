import { describe, expect, it } from "vitest";
import { itemsFrom, pickFurusatoItems } from "../src/lib/rakutenItems";

// 楽天市場商品検索 API の結果から、その自治体の返礼品の例を選ぶ（設計変更記録 #195・#257）
describe("返礼品の例", () => {
  const item = (shopName: string, itemName: string, extra: Record<string, unknown> = {}) => ({
    shopName, itemName, itemPrice: 10000, itemUrl: `https://item.rakuten.co.jp/${encodeURIComponent(itemName)}/`,
    mediumImageUrls: ["https://thumbnail.image.rakuten.co.jp/a.jpg?_ex=128x128"], ...extra,
  });

  it("ショップ名に自治体の名前がある品だけを選び、画像は 240px 角にし、アフィリエイトの URL を使う", () => {
    const got = pickFurusatoItems({ Items: [
      item("宮崎県都城市", "宮崎牛", { affiliateUrl: "https://hb.afl.rakuten.co.jp/x" }),
      item("鹿児島県志布志市", "うなぎ"),
      item("都城市ふるさと納税", "焼酎"),
    ] }, "宮崎県", "都城市");
    expect(got.map((g) => g.name)).toEqual(["宮崎牛", "焼酎"]);
    expect(got[0].href).toBe("https://hb.afl.rakuten.co.jp/x");
    expect(got[0].image).toBe("https://thumbnail.image.rakuten.co.jp/a.jpg?_ex=240x240");
  });

  it("市区町村名が空なら、都道府県名のあるショップの品を選ぶ", () => {
    const got = pickFurusatoItems({ items: [item("宮崎県都城市", "宮崎牛"), item("宮崎県", "マンゴー"), item("北海道紋別市", "ほたて")] }, "宮崎県", "");
    expect(got.map((g) => g.name)).toEqual(["宮崎牛", "マンゴー"]);
    expect(pickFurusatoItems({ items: [item("宮崎県", "マンゴー")] }, "", "")).toEqual([]);
  });

  it("返礼品のない寄附を除き、楽天トラベルクーポンは1つだけにする", () => {
    const got = pickFurusatoItems({ Items: [
      item("宮崎県都城市", "【返礼品なし】災害支援"),
      item("宮崎県都城市", "楽天トラベルクーポン 3,000円分"),
      item("宮崎県都城市", "楽天トラベル クーポン 15,000円分"),
      item("宮崎県都城市", "宮崎牛"),
    ] }, "宮崎県", "都城市");
    expect(got.map((g) => g.name)).toEqual(["楽天トラベルクーポン 3,000円分", "宮崎牛"]);
  });

  it("名前の頭の「【ふるさと納税】」は表示では外す", () => {
    const got = pickFurusatoItems({ Items: [item("宮崎県都城市", "【ふるさと納税】宮崎牛 焼肉セット")] }, "宮崎県", "都城市");
    expect(got[0].name).toBe("宮崎牛 焼肉セット");
  });

  it("結果の形が違う・空のときは空にする", () => {
    expect(pickFurusatoItems(null, "宮崎県", "都城市")).toEqual([]);
    expect(pickFurusatoItems({ error: "too_many_requests" }, "宮崎県", "都城市")).toEqual([]);
  });

  it("2つめの欄は5件目から並べ、足りなければ最初から並べる", () => {
    const list = Array.from({ length: 9 }, (_, i) => ({ name: `品${i + 1}`, price: 1, href: "x", image: "" }));
    expect(itemsFrom(list, 4, 4).map((i) => i.name)).toEqual(["品5", "品6", "品7", "品8"]);
    expect(itemsFrom(list.slice(0, 6), 4, 4).map((i) => i.name)).toEqual(["品1", "品2", "品3", "品4"]);
    expect(itemsFrom(list, 0, 4)).toHaveLength(4);
  });
});
