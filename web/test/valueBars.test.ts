import { describe, expect, it } from "vitest";
import { barScale, barStyle, barZero } from "../src/lib/valueBars";

// ランキングの表の値の横棒（設計変更記録 #226）
describe("値の横棒", () => {
  it("目盛りは 0 から最大値まで（差を大きく見せるために途中から始めない）", () => {
    expect(barScale([40, 50, null, 45])).toEqual({ lo: 0, hi: 50 });
    const scale = barScale([40, 50, null, 45]);
    expect(barStyle(50, scale)).toBe("--b:100%");
    expect(barStyle(40, scale)).toBe("--b:80%");
    expect(barZero(scale)).toBeUndefined();
  });
  it("値のない行・値のない表・すべて 0 の表には棒を出さない（欠測を 0 の棒にしない）", () => {
    expect(barStyle(null, barScale([1, 2]))).toBeUndefined();
    expect(barScale([null, null])).toBeNull();
    expect(barScale([0, 0])).toBeNull();
    expect(barStyle(3, null)).toBeUndefined();
  });
  it("0 は長さ 0、0 でない小さな値は見える長さにする", () => {
    const scale = barScale([0, 1, 100000]);
    expect(barStyle(0, scale)).toBe("--b:0%");
    expect(barStyle(1, scale)).toBe("--b:0.5%");
  });
  it("負の値がある表は、0 の位置から左右に伸ばす", () => {
    const scale = barScale([-20, 60, 0, 20]);
    expect(scale).toEqual({ lo: -20, hi: 60 });
    expect(barZero(scale)).toBe("--z:25%");
    expect(barStyle(60, scale)).toBe("--a:25%;--b:100%");
    expect(barStyle(20, scale)).toBe("--a:25%;--b:50%");
    expect(barStyle(-20, scale)).toBe("--b:25%");
    expect(barStyle(-10, scale)).toBe("--a:12.5%;--b:25%");
    expect(barStyle(0, scale)).toBe("--a:25%;--b:25%");
  });
  it("すべて負の表は、右端の 0 から左へ伸ばす", () => {
    const scale = barScale([-8, -2]);
    expect(scale).toEqual({ lo: -8, hi: 0 });
    expect(barZero(scale)).toBe("--z:100%");
    expect(barStyle(-2, scale)).toBe("--a:75%;--b:100%");
  });
  it("行の多い表でも止まらない（町丁・字等は20万行を超える）", () => {
    const values = Array.from({ length: 250000 }, (_, i) => i);
    expect(barScale(values)).toEqual({ lo: 0, hi: 249999 });
  });
});
