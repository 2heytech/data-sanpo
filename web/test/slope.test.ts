import { describe, expect, it } from "vitest";
import { SLOPE_ALPHA, SLOPE_CLASSES, decodeDem, paintSlope, pixelMeters, slopeTile } from "../src/map/slope";

const N = 256;
// 赤道のすぐ南のタイル（画素の大きさが行によってほとんど変わらない）
const Z = 14;
const Y = 2 ** 13;

/** 3×3 のタイルを、全体の画素の位置（行・列。真ん中のタイルの左上が 0,0）から標高を決めて作る */
function tiles(height: (row: number, col: number) => number, missing: number[] = []): (Float32Array | null)[] {
  return Array.from({ length: 9 }, (_, t) => {
    if (missing.includes(t)) return null;
    const out = new Float32Array(N * N);
    const r0 = (Math.floor(t / 3) - 1) * N, c0 = ((t % 3) - 1) * N;
    for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) out[r * N + c] = height(r0 + r, c0 + c);
    return out;
  });
}

describe("標高タイルの読み取り", () => {
  it("RGB から標高（0.01m 単位）。128,0,0 は標高なし、2^23 より大きい値は海面より低い", () => {
    const rgba = new Uint8ClampedArray(N * N * 4);
    rgba.set([0, 0, 100, 255, 128, 0, 0, 255, 255, 255, 156, 255, 0, 39, 16, 255]);
    const h = decodeDem(rgba);
    expect(h[0]).toBeCloseTo(1);
    expect(h[1]).toBeNaN();
    expect(h[2]).toBeCloseTo(-1);
    expect(h[3]).toBeCloseTo(100);
  });
  it("画素の大きさは赤道で約9.55m（ズーム14）、緯度35度ではその cos 倍", () => {
    expect(pixelMeters(14, Y, 0)).toBeCloseTo(9.5546, 3);
    const y35 = Math.floor((1 - Math.asinh(Math.tan((35 * Math.PI) / 180)) / Math.PI) / 2 * 2 ** 14);
    expect(pixelMeters(14, y35, 128) / pixelMeters(14, Y, 0)).toBeCloseTo(Math.cos((35 * Math.PI) / 180), 2);
  });
});

describe("傾斜の計算", () => {
  const px = pixelMeters(Z, Y, 0);
  it("一様な斜面は、どの画素でも同じ角度（タイルの端も隣のタイルを使う）", () => {
    for (const deg of [2, 10, 35]) {
      const rise = Math.tan((deg * Math.PI) / 180) * px;
      const s = slopeTile(tiles((r, c) => (c + r * 0.5) * rise), Z, Y);
      const want = (Math.atan(Math.hypot(1, 0.5) * Math.tan((deg * Math.PI) / 180)) * 180) / Math.PI;
      for (const i of [0, 255, 128 * N + 128, 255 * N, N * N - 1]) expect(s[i]).toBeCloseTo(want, 1);
    }
  });
  it("隣のタイルとの境目の段差も傾斜に入る", () => {
    const s = slopeTile(tiles((_, c) => (c >= N ? 10 : 0)), Z, Y);
    expect(s[255]).toBeGreaterThan(20);
    expect(s[254]).toBe(0);
  });
  it("隣のタイルがないとき・周りが海のときは、その画素と同じ高さとして計算する", () => {
    const steep = (_: number, c: number) => (c >= N ? 10 : 0);
    expect(slopeTile(tiles(steep, [2, 5, 8]), Z, Y)[255]).toBe(0);
    const coast = tiles(() => 0);
    coast[4]![128 * N + 129] = NaN;
    const s = slopeTile(coast, Z, Y);
    expect(s[128 * N + 128]).toBe(0);
    expect(s[128 * N + 129]).toBeNaN();
  });
});

describe("傾斜の色", () => {
  it("区分ごとの色。3度未満と標高のない画素は透明", () => {
    const rgba = paintSlope(Float32Array.from([1, 5, 10, 20, 45, NaN, 3, 15]));
    const px = (i: number) => [...rgba.slice(i * 4, i * 4 + 4)];
    const rgb = (hex: string) => [1, 3, 5].map((k) => parseInt(hex.slice(k, k + 2), 16));
    expect(px(0)[3]).toBe(0);
    expect(px(5)[3]).toBe(0);
    expect(px(1)).toEqual([...rgb(SLOPE_CLASSES[1].color!), SLOPE_ALPHA]);
    expect(px(2)).toEqual([...rgb(SLOPE_CLASSES[2].color!), SLOPE_ALPHA]);
    expect(px(3)).toEqual([...rgb(SLOPE_CLASSES[3].color!), SLOPE_ALPHA]);
    expect(px(4)).toEqual([...rgb(SLOPE_CLASSES[4].color!), SLOPE_ALPHA]);
    // 境目の値は上の区分（3度以上・15度以上）
    expect(px(6)).toEqual([...rgb(SLOPE_CLASSES[1].color!), SLOPE_ALPHA]);
    expect(px(7)).toEqual([...rgb(SLOPE_CLASSES[3].color!), SLOPE_ALPHA]);
  });
});
