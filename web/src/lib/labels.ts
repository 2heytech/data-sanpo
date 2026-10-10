// 地図の地名の文字の大きさ（docs/design-changes.md #89・#90）

export type LabelItem = { name: string; bbox?: [number, number, number, number] };

// 地名（と値）を地域の範囲に収められる文字の大きさ。ズーム0での px で、ズームが1上がるごとに2倍になる。
// 範囲（bbox）の幅を文字数で、高さを行数で割り、形がいびつでもはみ出しにくいよう小さめにとる
export const textUnits = (t: string) => [...t].reduce((n, c) => n + (c.charCodeAt(0) < 0x2000 ? 0.62 : 1), 0);
const mercX = (lon: number) => ((lon + 180) / 360) * 256;
const mercY = (lat: number) => {
  const r = (lat * Math.PI) / 180;
  return ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * 256;
};
export function labelFit(a: LabelItem, value: string | null): number {
  if (!a.bbox) return 0;
  const [w, s, e, n] = a.bbox;
  const width = (mercX(e) - mercX(w)) * 0.7;
  const height = (mercY(s) - mercY(n)) * 0.7;
  const units = Math.max(textUnits(a.name), textUnits(value ?? "") * 0.9, 1);
  // 値を出すときは、値のない地域も2行分で計算する（値のない地域だけ文字が大きくならないように）
  const lines = value === null ? 1.2 : 2.3;
  return Math.min(width / units, height / lines);
}

// 同じ種類の地名どうしで大きさがばらつきすぎないよう、各地域の収まる大きさを全体の中央値に半分寄せる
// （対数で中間＝幾何平均）。広い地域は少し小さく、狭い地域は少し大きくなる（最小・最大は growingTextSize で守る）
export function balancedFits(fits: number[]): number[] {
  const pos = fits.filter((f) => f > 0).sort((a, b) => a - b);
  if (!pos.length) return fits;
  const median = pos[Math.floor(pos.length / 2)];
  return fits.map((f) => (f > 0 ? Math.sqrt(f * median) : 0));
}

// 形の中でいちばん大きい部分の範囲。東京都の島しょ部のように離れた島があると範囲が大きくなりすぎるので、
// 文字の大きさはこの範囲で決める
type Geometry = { type: string; coordinates: unknown };
export function mainPartBbox(g: Geometry | null | undefined): [number, number, number, number] | undefined {
  if (!g) return undefined;
  const polys = (g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : []) as number[][][][];
  let best: [number, number, number, number] | undefined;
  let bestArea = -1;
  for (const poly of polys) {
    const ring = poly[0];
    if (!ring?.length) continue;
    let area = 0;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) area += (ring[j][0] + ring[i][0]) * (ring[j][1] - ring[i][1]);
    area = Math.abs(area);
    if (area > bestArea) {
      bestArea = area;
      const xs = ring.map((c) => c[0]);
      const ys = ring.map((c) => c[1]);
      best = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
    }
  }
  return best;
}
// 文字の大きさ: 拡大するにつれて、地域に収まる範囲で大きくする。stops は [ズーム, 最小, 最大]。
// 最小は収まらなくても使う大きさ（重なる地名は MapLibre が間引く）、最大は大きくなりすぎない上限
// 収まる大きさはズームごとに2倍になるので、直線で補間してもはみ出さないよう1ズームごとに区切る
export function growingTextSize(stops: [number, number, number][], prop: "fit" | "fitv"): unknown[] {
  const at = (z: number, k: 1 | 2) => {
    const i = stops.findIndex(([sz]) => sz >= z);
    if (i <= 0) return stops[Math.max(i, 0)][k];
    const [z0, z1] = [stops[i - 1][0], stops[i][0]];
    return stops[i - 1][k] + ((stops[i][k] - stops[i - 1][k]) * (z - z0)) / (z1 - z0);
  };
  const out: unknown[] = ["interpolate", ["linear"], ["zoom"]];
  for (let z = stops[0][0]; z <= stops[stops.length - 1][0]; z++) {
    out.push(z, ["max", at(z, 1), ["min", at(z, 2), ["*", ["get", prop], 2 ** z]]]);
  }
  return out;
}
