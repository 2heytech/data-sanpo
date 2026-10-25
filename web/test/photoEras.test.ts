import { describe, expect, it } from "vitest";
import { PHOTO_MASK_SIZE, photoMask, photoSamples, photoShare } from "../src/map/photoEras";

const NENDO = { minzoom: 14, maxzoom: 18 };
const GAZO = { minzoom: 10, maxzoom: 17 };
// 三軒茶屋のあたり
const CENTER = { lng: 139.67, lat: 35.6436 };

describe("航空写真を確かめるタイルと点", () => {
  it("表示するタイル（縮尺 + 1 を丸めたズーム）の2つ下のズームで調べる", () => {
    expect(photoSamples(CENTER, 16, 1280, 800, GAZO).z).toBe(15);
    expect(photoSamples(CENTER, 15.4, 1280, 800, GAZO).z).toBe(14);
  });
  it("年代のズームの範囲に収める（年度別空中写真は z14 から、国土画像情報は z17 まで）", () => {
    expect(photoSamples(CENTER, 12, 1280, 800, NENDO).z).toBe(14);
    expect(photoSamples(CENTER, 17, 1280, 800, GAZO).z).toBe(16);
    expect(photoSamples(CENTER, 10, 1280, 800, GAZO).z).toBe(10);
  });
  it("読むタイルは4枚以内（縮小して年代のズームの下限で調べるときも）", () => {
    for (const zoom of [10, 11.3, 12.5, 13, 14.2, 15, 16, 17]) {
      for (const era of [NENDO, GAZO]) {
        const { samples } = photoSamples(CENTER, zoom, 1920, 1080, era);
        expect(new Set(samples.map((s) => `${s.x}/${s.y}`)).size).toBeLessThanOrEqual(4);
      }
    }
  });
  it("地図の中央を調べる（点はタイルの中の升目に入る）", () => {
    const { z, samples } = photoSamples(CENTER, 16, 1280, 800, GAZO);
    const n = 2 ** z;
    const cx = ((CENTER.lng + 180) / 360) * n;
    const xs = samples.map((s) => s.x + (s.px + 0.5) / PHOTO_MASK_SIZE);
    expect(Math.min(...xs)).toBeLessThan(cx);
    expect(Math.max(...xs)).toBeGreaterThan(cx);
    // 中央の範囲（地図の幅の半分 = 640 CSS 画素）は z15 のタイルで 640 / 4 / 256 枚ほど
    expect(Math.max(...xs) - Math.min(...xs)).toBeCloseTo(0.625 * (7 / 8), 1);
    for (const s of samples) {
      expect(s.px).toBeGreaterThanOrEqual(0);
      expect(s.px).toBeLessThan(PHOTO_MASK_SIZE);
      expect(s.py).toBeGreaterThanOrEqual(0);
      expect(s.py).toBeLessThan(PHOTO_MASK_SIZE);
    }
  });
});

describe("タイルの写っている升目", () => {
  it("透明と黒（撮影範囲の外）は写っていないとし、暗い海などは写っているとする", () => {
    const rgba = [
      120, 130, 110, 255, // 写真
      0, 0, 0, 0, // 透明（PNG の撮影範囲の外）
      0, 0, 0, 255, // 黒（JPEG の撮影範囲の外）
      6, 8, 3, 255, // JPEG の圧縮でわずかに色のついた黒
      10, 14, 20, 255, // 暗い海
      200, 200, 200, 60, // ほぼ透明
    ];
    expect([...photoMask(rgba)]).toEqual([1, 0, 0, 0, 1, 0]);
  });
});

describe("中央に写っている割合", () => {
  const full = new Uint8Array(PHOTO_MASK_SIZE * PHOTO_MASK_SIZE).fill(1);
  const left = new Uint8Array(PHOTO_MASK_SIZE * PHOTO_MASK_SIZE).map((_, i) => (i % PHOTO_MASK_SIZE < PHOTO_MASK_SIZE / 2 ? 1 : 0));
  const samples = [
    { x: 1, y: 1, px: 10, py: 10 },
    { x: 1, y: 1, px: 50, py: 10 },
    { x: 2, y: 1, px: 10, py: 10 },
    { x: 3, y: 1, px: 10, py: 10 },
  ];
  it("タイルの写っている升目の点を数える", () => {
    expect(photoShare(samples, new Map([["1/1", left], ["2/1", full], ["3/1", full]]))).toBe(0.75);
  });
  it("タイルがない（null）・確かめていない点は写っていないとする", () => {
    expect(photoShare(samples, new Map([["1/1", full], ["2/1", null]]))).toBe(0.5);
    expect(photoShare([], new Map())).toBe(0);
  });
});
