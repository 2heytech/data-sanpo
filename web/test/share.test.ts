import { describe, expect, it } from "vitest";
import { safeFileName, wrapText } from "../src/map/share";

// 1文字の幅を 1 とする（全角・半角を区別しない）
const measure = (s: string) => [...s].length;

describe("画像の文字の折り返し", () => {
  it("収まる文はそのまま1行", () => {
    expect(wrapText("65歳以上の割合", 10, measure)).toEqual(["65歳以上の割合"]);
  });
  it("行の後ろ半分にある「・」の後で折る（言葉の途中で切らない）", () => {
    expect(wrapText("2020年10月1日現在・市区町村別・赤い枠は金沢市", 18, measure))
      .toEqual(["2020年10月1日現在・市区町村別・", "赤い枠は金沢市"]);
  });
  it("区切りがないときは文字で折り、句読点・閉じかっこは行の頭に置かない", () => {
    expect(wrapText("あいうえおかきくけこ。", 5, measure)).toEqual(["あいうえお", "かきくけこ。"]);
  });
  it("折り返した行の頭の空白は除く", () => {
    expect(wrapText("あいうえお かきくけこ", 5, measure)).toEqual(["あいうえお", "かきくけこ"]);
  });
});

describe("保存する画像のファイル名", () => {
  it("ファイル名に使えない文字と空白を「_」にする", () => {
    expect(safeFileName("データさんぽ_通勤/通学 の手段:鉄道.png")).toBe("データさんぽ_通勤_通学_の手段_鉄道.png");
  });
});
