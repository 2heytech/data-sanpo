// 色分け。色覚の多様性に配慮した ColorBrewer の配色（9色、増減は発散系10色）を、
// 階級の数に合わせて補間して使う（docs/design-changes.md #29、12区分は #35）。
// 市区町村・町丁目は全国で共通の区切りで最大20区分になるので（#145）、色は見た目の差（OKLab の距離）が
// 等しくなるように配色の上で等間隔に取り、青・紫は色相も変わる配色にして隣の区分との差を大きくする。

export const SCHEMES: Record<string, string[]> = {
  // 青（人口など）: 黄 → 緑 → 青（YlGnBu）。紫（人口密度など）: 桃 → 紫（RdPu）
  blues: ["#ffffd9", "#edf8b1", "#c7e9b4", "#7fcdbb", "#41b6c4", "#1d91c0", "#225ea8", "#253494", "#081d58"],
  purples: ["#fff7f3", "#fde0dd", "#fcc5c0", "#fa9fb5", "#f768a1", "#dd3497", "#ae017e", "#7a0177", "#49006a"],
  oranges: ["#fff5eb", "#fee6ce", "#fdd0a2", "#fdae6b", "#fd8d3c", "#f16913", "#d94801", "#a63603", "#7f2704"],
  greens: ["#f7fcf5", "#e5f5e0", "#c7e9c0", "#a1d99b", "#74c476", "#41ab5d", "#238b45", "#006d2c", "#00441b"],
  bugn: ["#f7fcfd", "#e5f5f9", "#ccece6", "#99d8c9", "#66c2a4", "#41ae76", "#238b45", "#006d2c", "#00441b"],
  rdpu: ["#fff7f3", "#fde0dd", "#fcc5c0", "#fa9fb5", "#f768a1", "#dd3497", "#ae017e", "#7a0177", "#49006a"],
  ylorbr: ["#ffffe5", "#fff7bc", "#fee391", "#fec44f", "#fe9929", "#ec7014", "#cc4c02", "#993404", "#662506"],
  bupu: ["#f7fcfd", "#e0ecf4", "#bfd3e6", "#9ebcda", "#8c96c6", "#8c6bb1", "#88419d", "#810f7c", "#4d004b"],
  reds: ["#fff5f0", "#fee0d2", "#fcbba1", "#fc9272", "#fb6a4a", "#ef3b2c", "#cb181d", "#a50f15", "#67000d"],
  // 増減率用の発散配色（減少＝橙、増加＝紫）。前半が0未満、後半が0以上に対応する
  puor: ["#7f3b08", "#b35806", "#e08214", "#fdb863", "#fee0b6", "#d8daeb", "#b2abd2", "#8073ac", "#542788", "#2d004b"],
};

/** 0 を境に前半・後半の色を使い分ける配色。 */
const DIVERGING = new Set(["puor"]);

export const NO_DATA_COLOR = "#c8c8c8";
/** 値が0で色を塗らない地域（zero_blank の指標）。 */
export const BLANK_COLOR = "rgba(0,0,0,0)";

// sRGB ⇄ OKLab（見た目の差がおおよそ距離に比例する色空間。https://bottosson.github.io/posts/oklab/）
const toLinear = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const toGamma = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
function toOklab(hex: string): number[] {
  const [r, g, b] = [1, 3, 5].map((i) => toLinear(parseInt(hex.slice(i, i + 2), 16) / 255));
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
          1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
          0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}
function fromOklab([L, a, b]: number[]): string {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const rgb = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
               -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
               -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
  return "#" + rgb.map((c) => Math.round(Math.min(1, Math.max(0, toGamma(c))) * 255).toString(16).padStart(2, "0")).join("");
}

/** 配色の色をつないだ線の上で、見た目の差が等しくなる間隔で n 色を取り出す（両端の色は保つ）。 */
function sample(palette: string[], n: number): string[] {
  if (n <= 0) return [];
  if (n === 1) return [palette[Math.floor(palette.length / 2)]];
  const labs = palette.map(toOklab);
  const seg = labs.slice(1).map((c, k) => Math.hypot(...c.map((v, j) => v - labs[k][j])));
  const total = seg.reduce((a, b) => a + b, 0);
  return Array.from({ length: n }, (_, i) => {
    if (i === 0) return palette[0];
    if (i === n - 1) return palette[palette.length - 1];
    let rest = (total * i) / (n - 1);
    let k = 0;
    while (k < seg.length - 1 && rest > seg[k]) rest -= seg[k++];
    const f = seg[k] ? Math.min(1, rest / seg[k]) : 0;
    return fromOklab(labs[k].map((v, j) => v + (labs[k + 1][j] - v) * f));
  });
}

/** 区切り値の数に合わせて配色から色を選ぶ（区切りが増減しても濃淡の幅を保つ）。
 *  zeroBlank のときは0（色なし）と区別しやすいよう、ほぼ白のいちばん淡い色を使わない。 */
export function colorsFor(scheme: string, breaks: number[], zeroBlank = false): string[] {
  const full = SCHEMES[scheme] ?? SCHEMES.blues;
  const palette = zeroBlank && !DIVERGING.has(scheme) ? full.slice(1) : full;
  const n = breaks.length + 1;
  const zero = breaks.indexOf(0);
  if (DIVERGING.has(scheme) && zero >= 0) {
    // 0 未満の階級は前半、0 以上の階級は後半の色から選び、0 の位置で色が切り替わるようにする
    const half = palette.length / 2;
    const below = sample(palette.slice(0, half).reverse(), zero).reverse();
    const above = sample(palette.slice(half), n - zero);
    return [...below, ...above];
  }
  return sample(palette, n);
}

export function classIndex(value: number, breaks: number[]): number {
  let i = 0;
  while (i < breaks.length && value >= breaks[i]) i++;
  return i;
}

const VALUE = ["feature-state", "v"];

function stepExpression(scheme: string, breaks: number[], zeroBlank: boolean): unknown {
  const colors = colorsFor(scheme, breaks, zeroBlank);
  return breaks.length === 0 ? colors[0] : ["step", VALUE, colors[0], ...breaks.flatMap((b, i) => [b, colors[i + 1]])];
}

/** MapLibre の fill-color 式。値は feature-state の "v" に入れる。zeroBlank なら0は塗らない。
 *  区切りは全国で1つ（都道府県ごとには変えない。#145） */
export function fillColorExpression(scheme: string, breaks: number[], zeroBlank = false): unknown {
  const blank = zeroBlank ? [["==", VALUE, 0], BLANK_COLOR] : [];
  return ["case", ["!=", ["typeof", VALUE], "number"], NO_DATA_COLOR, ...blank, stepExpression(scheme, breaks, zeroBlank)];
}

/** 凡例の文字のおおよその幅（px）。数字・英字は0.6字、「,」「.」は0.3字、漢字・かなは1字として数える。 */
export function textWidth(text: string, fontPx: number): number {
  let em = 0;
  for (const ch of text) em += /[,.]/.test(ch) ? 0.3 : ch.charCodeAt(0) > 0xff ? 1 : 0.6;
  return em * fontPx;
}

/** 凡例の区切りの値を、いくつおきに出せば重ならないか。x は値を置く位置、w は文字の幅（どちらも px）。
 *  rows 段に互い違いに置き、同じ段で隣り合う値の間が gap 以上あく、いちばん小さい間隔を返す。 */
export function tickStep(x: number[], w: number[], rows: number, gap = 4): number {
  for (let step = 1; step < x.length; step++) {
    const shown = x.map((_, k) => k).filter((k) => k % step === 0);
    const fits = shown.every((k, j) => {
      const prev = shown[j - rows];
      return prev === undefined || x[prev] + w[prev] / 2 + gap <= x[k] - w[k] / 2;
    });
    if (fits) return step;
  }
  return Math.max(1, x.length);
}
