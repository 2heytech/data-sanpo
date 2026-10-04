// 色分け。色覚の多様性に配慮した ColorBrewer の配色（単色系は9色、増減は発散系10色）を、
// 階級の数に合わせて補間して使う（docs/design-changes.md #29、12区分は #35）。

export const SCHEMES: Record<string, string[]> = {
  blues: ["#f7fbff", "#deebf7", "#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5", "#08519c", "#08306b"],
  purples: ["#fcfbfd", "#efedf5", "#dadaeb", "#bcbddc", "#9e9ac8", "#807dba", "#6a51a3", "#54278f", "#3f007d"],
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

const toRgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const toHex = (rgb: number[]) => "#" + rgb.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");

/** 配色の色の間を補間して n 色を取り出す（両端の色は保つ）。 */
function sample(palette: string[], n: number): string[] {
  if (n <= 0) return [];
  if (n === 1) return [palette[Math.floor(palette.length / 2)]];
  if (n === palette.length) return [...palette];
  return Array.from({ length: n }, (_, i) => {
    const t = (i * (palette.length - 1)) / (n - 1);
    const lo = Math.floor(t), hi = Math.min(lo + 1, palette.length - 1), f = t - lo;
    const [a, b] = [toRgb(palette[lo]), toRgb(palette[hi])];
    return toHex(a.map((v, k) => v + (b[k] - v) * f));
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
 *  byGroup があれば、地物の id の groupOf 部分（都道府県コード）ごとにその区切りで塗る（ないグループは breaks）。 */
export function fillColorExpression(scheme: string, breaks: number[], zeroBlank = false,
                                    byGroup?: { key: unknown; breaks: Record<string, number[]> }): unknown {
  const groups = Object.entries(byGroup?.breaks ?? {});
  const colorExpr = groups.length
    ? ["match", byGroup!.key, ...groups.flatMap(([k, b]) => [k, stepExpression(scheme, b, zeroBlank)]),
       stepExpression(scheme, breaks, zeroBlank)]
    : stepExpression(scheme, breaks, zeroBlank);
  const blank = zeroBlank ? [["==", VALUE, 0], BLANK_COLOR] : [];
  return ["case", ["!=", ["typeof", VALUE], "number"], NO_DATA_COLOR, ...blank, colorExpr];
}
