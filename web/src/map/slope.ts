// 背景の「傾斜」（設計変更記録 #177）。地理院タイル「標高タイル」（dem_png、基盤地図情報 数値標高モデル）をブラウザで読み、
// 画素ごとの地面の傾斜（度）を計算して、区分ごとに色を塗った画像を地図に重ねる（計算はブラウザの中だけ）。
// 傾斜の計算は地理院の傾斜量図と同じ、周りの8画素の標高を使う方法（Horn 法）。タイルの端の画素は隣のタイルの標高を使う。
// 区分の境目は、歩いて感じる坂の違いが見えるよう4度までは1度ごと、12度までは2度ごと、急な斜面は15度から5度ごとの14段階にする（#178・#180）。
// 色は薄い黄から緑・青を経て濃い紫へ（viridis）。区分ごとに色合いと明るさの両方が変わり、色覚の違いがあっても明るさの順で区分の順がわかる。
// 3度・15度・30度は指標「平らな土地の割合」「急な斜面の割合」と同じ。30度は法律の「急傾斜地」の基準
import type * as MapLibre from "maplibre-gl";

/** 傾斜の区分（min 度以上）。1度未満は色を塗らず、下の地図をそのまま見せる */
export const SLOPE_CLASSES: { min: number; label: string; color: string | null }[] = [
  { min: 0, label: "1度未満", color: null },
  { min: 1, label: "1〜2度", color: "#f6ef9a" },
  { min: 2, label: "2〜3度", color: "#fde725" },
  { min: 3, label: "3〜4度", color: "#cae126" },
  { min: 4, label: "4〜6度", color: "#97d745" },
  { min: 6, label: "6〜8度", color: "#66ca5f" },
  { min: 8, label: "8〜10度", color: "#3eba75" },
  { min: 10, label: "10〜12度", color: "#22a884" },
  { min: 12, label: "12〜15度", color: "#21968b" },
  { min: 15, label: "15〜20度", color: "#27828d" },
  { min: 20, label: "20〜25度", color: "#2f6e8e" },
  { min: 25, label: "25〜30度", color: "#385a8c" },
  { min: 30, label: "30〜35度", color: "#414487" },
  { min: 35, label: "35〜40度", color: "#472b79" },
  { min: 40, label: "40度以上", color: "#461261" },
];
/** 塗る色の不透明度（0〜255）。下の地図の道や地名が透けて見えるようにする */
export const SLOPE_ALPHA = 200;
/** 地図の source に書くタイルの URL（registerSlopeProtocol の slope:// で作る） */
export const SLOPE_TILES = "slope://{z}/{x}/{y}";
// 標高タイル（DEM10B）はズーム14まで（約10m間隔）。それより拡大したときは z14 の画像を引き伸ばす。
// ズーム12以下（30m間隔より粗い）は傾斜がゆるく出るので作らない（地図の縮尺11.5くらいから出る）
export const SLOPE_MINZOOM = 13;
export const SLOPE_MAXZOOM = 14;
const DEM_TILES = "https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png";
const TILE = 256;
const PAD = TILE + 2;
const NO_VALUE = 2 ** 23;
const EARTH_CIRCUMFERENCE = 2 * Math.PI * 6378137;
// 読んだ標高タイルを覚えておく枚数（1枚 256KB。隣のタイルを描くときに使い回す）
const DEM_CACHE_MAX = 160;

/** 標高タイルの画素（RGBA）→ 標高（m）。標高のない画素（海など。色が 128,0,0）は NaN */
export function decodeDem(rgba: ArrayLike<number>): Float32Array {
  const out = new Float32Array(TILE * TILE);
  for (let i = 0; i < out.length; i++) {
    const x = rgba[i * 4] * 65536 + rgba[i * 4 + 1] * 256 + rgba[i * 4 + 2];
    out[i] = x === NO_VALUE ? NaN : (x < NO_VALUE ? x : x - 2 ** 24) * 0.01;
  }
  return out;
}

/** 画素の地上の大きさ（m）。ウェブメルカトルの画素は東西・南北とも 赤道での大きさ × cos(緯度) */
export function pixelMeters(z: number, y: number, row: number): number {
  const n = 2 ** z;
  const lat = Math.atan(Math.sinh(Math.PI * (1 - (2 * (y + (row + 0.5) / TILE)) / n)));
  return (EARTH_CIRCUMFERENCE / (TILE * n)) * Math.cos(lat);
}

/**
 * 3×3 のタイルの標高（左上から行ごと、真ん中が描くタイル。ないタイルは null）→ 真ん中のタイルの画素ごとの傾斜（度）。
 * 標高のない画素は NaN。周りの画素に標高がないとき（海岸・タイルのない所）は、その画素の標高と同じとして計算する。
 */
export function slopeTile(dems: (Float32Array | null)[], z: number, y: number): Float32Array {
  const grid = new Float32Array(PAD * PAD).fill(NaN);
  const at = (t: number, r: number, c: number) => dems[t]?.[r * TILE + c] ?? NaN;
  for (let r = -1; r <= TILE; r++) {
    const tr = r < 0 ? 0 : r < TILE ? 1 : 2;
    const sr = r < 0 ? TILE - 1 : r < TILE ? r : 0;
    for (let c = -1; c <= TILE; c++) {
      const tc = c < 0 ? 0 : c < TILE ? 1 : 2;
      const sc = c < 0 ? TILE - 1 : c < TILE ? c : 0;
      grid[(r + 1) * PAD + c + 1] = at(tr * 3 + tc, sr, sc);
    }
  }
  const out = new Float32Array(TILE * TILE);
  for (let r = 0; r < TILE; r++) {
    const d8 = 8 * pixelMeters(z, y, r);
    for (let c = 0; c < TILE; c++) {
      const i = (r + 1) * PAD + c + 1;
      const e = grid[i];
      if (Number.isNaN(e)) { out[r * TILE + c] = NaN; continue; }
      const v = (j: number) => (Number.isNaN(grid[j]) ? e : grid[j]);
      const a = v(i - PAD - 1), b = v(i - PAD), cc = v(i - PAD + 1);
      const d = v(i - 1), f = v(i + 1);
      const g = v(i + PAD - 1), h = v(i + PAD), k = v(i + PAD + 1);
      const sx = (cc + 2 * f + k - (a + 2 * d + g)) / d8;
      const sy = (g + 2 * h + k - (a + 2 * b + cc)) / d8;
      out[r * TILE + c] = (Math.atan(Math.hypot(sx, sy)) * 180) / Math.PI;
    }
  }
  return out;
}

const CLASS_RGB = SLOPE_CLASSES.map((s) => s.color && [1, 3, 5].map((i) => parseInt(s.color!.slice(i, i + 2), 16)));

/** 傾斜（度）→ 区分の色の画素（RGBA）。1度未満と標高のない画素は透明 */
export function paintSlope(slope: Float32Array): Uint8ClampedArray<ArrayBuffer> {
  const out = new Uint8ClampedArray(slope.length * 4);
  for (let i = 0; i < slope.length; i++) {
    const s = slope[i];
    if (Number.isNaN(s)) continue;
    let k = 0;
    while (k + 1 < SLOPE_CLASSES.length && s >= SLOPE_CLASSES[k + 1].min) k++;
    const rgb = CLASS_RGB[k];
    if (!rgb) continue;
    out.set([rgb[0], rgb[1], rgb[2], SLOPE_ALPHA], i * 4);
  }
  return out;
}

function canvas2d(): OffscreenCanvasRenderingContext2D | CanvasRenderingContext2D {
  const canvas = typeof OffscreenCanvas !== "undefined" ? new OffscreenCanvas(TILE, TILE)
    : Object.assign(document.createElement("canvas"), { width: TILE, height: TILE });
  const ctx = canvas.getContext("2d", { willReadFrequently: true }) as OffscreenCanvasRenderingContext2D | CanvasRenderingContext2D | null;
  if (!ctx) throw new Error("canvas が使えません");
  return ctx;
}

/**
 * 地図に slope:// のタイルを作る処理を登録する。標高タイルは読んだものを少しの間覚えておき、隣のタイルにも使う。
 * 標高タイルがない所（海だけの所。404）は標高なし、通信の失敗は覚えずに次に読み直す。
 */
export function registerSlopeProtocol(maplibregl: typeof MapLibre): void {
  const ctx = canvas2d();
  const dems = new Map<string, Promise<Float32Array | null>>();
  const dem = (z: number, x: number, y: number): Promise<Float32Array | null> => {
    const n = 2 ** z;
    if (y < 0 || y >= n) return Promise.resolve(null);
    const key = `${z}/${(x + n) % n}/${y}`;
    let p = dems.get(key);
    if (p) {
      dems.delete(key);   // 使ったものを後ろに回し、古いものから忘れる
    } else {
      const url = DEM_TILES.replace("{z}/{x}/{y}", key);
      p = fetch(url).then(async (r) => {
        if (r.status === 404) return null;
        if (!r.ok) throw new Error(`標高タイルを読めませんでした（${r.status}）`);
        const image = await createImageBitmap(await r.blob(), { premultiplyAlpha: "none", colorSpaceConversion: "none" });
        // 描いてから読むまでの間に await を挟まない（ほかのタイルと canvas を取り合わないように）
        ctx.clearRect(0, 0, TILE, TILE);
        ctx.drawImage(image, 0, 0);
        image.close();
        return decodeDem(ctx.getImageData(0, 0, TILE, TILE).data);
      });
      p.catch(() => dems.delete(key));
    }
    dems.set(key, p);
    if (dems.size > DEM_CACHE_MAX) dems.delete(dems.keys().next().value!);
    return p;
  };
  maplibregl.addProtocol("slope", async (params) => {
    const [z, x, y] = params.url.replace("slope://", "").split("/").map(Number);
    const tiles = await Promise.all([-1, 0, 1].flatMap((dy) => [-1, 0, 1].map((dx) => dem(z, x + dx, y + dy))));
    const rgba = tiles[4] ? paintSlope(slopeTile(tiles, z, y)) : new Uint8ClampedArray(TILE * TILE * 4);
    // 描いた画像はそのまま渡す（PNG にしない）
    return { data: await createImageBitmap(new ImageData(rgba, TILE, TILE)) };
  });
}
