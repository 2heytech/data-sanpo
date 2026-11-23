import { describe, expect, it } from "vitest";
import { settleOpen } from "../src/map/sheet";

// スマホの地図の下端のパネルを引いて離したとき、開くか閉じるか（設計変更記録 #254）。閉じた高さ 64px・開いた高さ 400px
describe("settleOpen", () => {
  const closed = 64;
  const open = 400;

  it("閉じていたときは、少し（2割）引き上げただけで開く", () => {
    expect(settleOpen(64 + 80, closed, open, 0, false)).toBe(true);
    expect(settleOpen(64 + 50, closed, open, 0, false)).toBe(false);
  });

  it("開いていたときは、少し（2割）引き下げただけで閉じる", () => {
    expect(settleOpen(400 - 80, closed, open, 0, true)).toBe(false);
    expect(settleOpen(400 - 50, closed, open, 0, true)).toBe(true);
  });

  it("速く払ったときは、引いた長さによらずその向きに", () => {
    expect(settleOpen(64 + 10, closed, open, -0.6, false)).toBe(true);
    expect(settleOpen(400 - 10, closed, open, 0.6, true)).toBe(false);
    // 引き上げてから下へ払えば閉じる
    expect(settleOpen(380, closed, open, 0.5, false)).toBe(false);
  });

  it("開いた高さが閉じた高さ以下のときは、元のまま", () => {
    expect(settleOpen(64, closed, 64, 0, true)).toBe(true);
    expect(settleOpen(64, closed, 64, 0, false)).toBe(false);
  });
});
