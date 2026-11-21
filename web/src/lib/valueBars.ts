// ランキングの表の値の横棒（設計変更記録 #226）。
// 棒の長さはページを作るときに計算し、値のセルの style（--a・--b）に書く。描くのは CSS（global.css の .bars）だけで、
// 行ごとの要素を増やさない（市区町村の表は約1,900行ある）。
// 目盛りは 0 から最大値まで。差を大きく見せるために途中から始めることはしない。
// 負の値がある指標（増減率など）は最小値から最大値までを幅にして、0 の位置から左右に伸ばす。

export interface BarScale { lo: number; hi: number }

/** 表の値から棒の目盛りを決める。値がない・すべて 0 のときは棒を出さない（null） */
export function barScale(values: Iterable<number | null>): BarScale | null {
  let lo = 0;
  let hi = 0;
  for (const v of values) {
    if (v === null || !Number.isFinite(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return hi > lo ? { lo, hi } : null;
}

const pct = (x: number) => `${Number(x.toFixed(1))}%`;
// 0 でない値は、棒が見えなくならない長さ（幅の 0.5%）を最低でも出す
const MIN_LENGTH = 0.5;

/** 0 の位置（負の値がある表だけ。表の style に --z として書く） */
export function barZero(scale: BarScale | null): string | undefined {
  return scale && scale.lo < 0 ? `--z:${pct((-scale.lo / (scale.hi - scale.lo)) * 100)}` : undefined;
}

/** 値のセルの style。棒の左端（--a。0 から始まるときは書かない）と右端（--b）を幅に対する％で書く */
export function barStyle(value: number | null, scale: BarScale | null): string | undefined {
  if (value === null || !scale || !Number.isFinite(value)) return undefined;
  const span = scale.hi - scale.lo;
  const zero = (-scale.lo / span) * 100;
  let at = ((value - scale.lo) / span) * 100;
  if (value > 0) at = Math.max(at, zero + MIN_LENGTH);
  if (value < 0) at = Math.min(at, zero - MIN_LENGTH);
  const a = Math.max(0, Math.min(zero, at));
  const b = Math.min(100, Math.max(zero, at));
  return a > 0 ? `--a:${pct(a)};--b:${pct(b)}` : `--b:${pct(b)}`;
}
