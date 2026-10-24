// 航空写真の撮影年代のうち、地図の中央に実際に写っているものを見分ける（docs/design-changes.md #162）。
// 年代別の写真は撮影した範囲がタイルの一部だけのことが多く（年度別空中写真はどの年度も国土の一部だけ）、
// タイルがあっても中央は撮影範囲の外で何も出ないことがある。そこで表示する縮尺に近いタイルの画像を縮めて読み、
// 中央の範囲のうち写っている割合を数える。撮影範囲の外は、PNG の年代は透明、1974〜1990年（国土画像情報の JPEG）は黒。

/** タイルの画像を縮めて調べるときの大きさ（縦横の画素数） */
export const PHOTO_MASK_SIZE = 64;
/** 中央の範囲を縦横この数の点で調べる */
const GRID = 8;
/** 中央の範囲のこれ以上が写っている年代だけを並べる */
export const PHOTO_MIN_SHARE = 0.5;
/** これ以下の暗さ（RGB のいちばん大きい値）は撮影範囲の外の黒とみなす */
const BLACK_MAX = 8;

export interface PhotoSample {
  /** 調べるタイル */
  x: number;
  y: number;
  /** タイルの中の位置（PHOTO_MASK_SIZE の升目） */
  px: number;
  py: number;
}

/**
 * 地図の表示（中心・縮尺・大きさ）から、写真が写っているかを確かめるタイルのズームと、調べる点を求める。
 * 256 画素のタイルは「縮尺 + 1」を丸めたズームで描かれる（MapLibre の raster）。その2つ下のズーム（年代のズームの範囲内）で、
 * 地図の中央（縦横それぞれ半分）を調べる。範囲はタイル1枚の大きさまでにし、読むタイルを4枚以内にする。
 */
export function photoSamples(
  center: { lng: number; lat: number },
  zoom: number,
  width: number,
  height: number,
  era: { minzoom: number; maxzoom: number },
): { z: number; samples: PhotoSample[] } {
  const z = Math.min(Math.max(Math.round(zoom + 1) - 2, era.minzoom), era.maxzoom);
  const world = 256 * 2 ** z;
  const cx = ((center.lng + 180) / 360) * world;
  const r = (center.lat * Math.PI) / 180;
  const cy = ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * world;
  // 地図の 1 CSS 画素が、このズームのタイルの何画素か（地図の縮尺は 512 画素のタイルで数える）
  const scale = 2 ** (z - zoom - 1);
  const hw = Math.min((width / 4) * scale, 128);
  const hh = Math.min((height / 4) * scale, 128);
  const samples: PhotoSample[] = [];
  for (let j = 0; j < GRID; j++) {
    for (let i = 0; i < GRID; i++) {
      const X = cx - hw + ((i + 0.5) / GRID) * 2 * hw;
      const Y = cy - hh + ((j + 0.5) / GRID) * 2 * hh;
      const x = Math.floor(X / 256);
      const y = Math.floor(Y / 256);
      samples.push({
        x, y,
        px: Math.floor(((X - x * 256) / 256) * PHOTO_MASK_SIZE),
        py: Math.floor(((Y - y * 256) / 256) * PHOTO_MASK_SIZE),
      });
    }
  }
  return { z, samples };
}

/** 縮めたタイルの画素（RGBA）から、写っている升目に 1 を立てる（透明と黒は撮影範囲の外） */
export function photoMask(rgba: ArrayLike<number>): Uint8Array {
  const mask = new Uint8Array(rgba.length / 4);
  for (let i = 0; i < mask.length; i++) {
    const o = i * 4;
    mask[i] = rgba[o + 3] >= 128 && Math.max(rgba[o], rgba[o + 1], rgba[o + 2]) > BLACK_MAX ? 1 : 0;
  }
  return mask;
}

/** 調べた点のうち写っている割合。タイルがない（null）・読めていない点は写っていないとする */
export function photoShare(samples: PhotoSample[], masks: Map<string, Uint8Array | null>): number {
  if (!samples.length) return 0;
  let hit = 0;
  for (const s of samples) {
    if (masks.get(`${s.x}/${s.y}`)?.[s.py * PHOTO_MASK_SIZE + s.px]) hit++;
  }
  return hit / samples.length;
}
