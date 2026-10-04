"""凡例の区切り位置（docs/design-changes.md #35）。

- nice: まず切りのよい刻み（1, 2, 5 × 10^k など）の等間隔を試し、どの階級にも値が集まりすぎなければ使う。
  飛び抜けた地域があるときは、両端5%を除いた範囲の等間隔も試す（両端の階級は「未満」「以上」）。
  偏った分布（差の大きい指標）は等間隔だと大半が1色になるので、分位点の近くで切りのよい数値を選ぶ。
- diverging: 0 を境に、減少側・増加側をそれぞれ classes/2 の階級に分ける（区切りは切りのよい数値）。
区切りは「その値以上が次の階級」。切りのよい数値は 1000, 500, 100, 50, 10, 5, 1, 0.5, 0.1 … の順に探す。
"""
from __future__ import annotations

import bisect
import math
import statistics

MAX_SHARE = 0.25   # 等間隔で1つの階級にこれより多く集まるなら分位点の方式にする
TRIM = 0.05       # 等間隔で飛び抜けた値に引っぱられるときは、両端5%を除いた範囲を等分する
TOLERANCE = 0.5    # 分位点から隣の分位点までの距離のうち、ずらしてよい割合（中間点まで）


def _steps(top: float, digits: int):
    """切りのよい刻みを粗い順に返す（10^e, 5×10^(e-1), 10^(e-1), …、10^-digits まで）。"""
    e = math.floor(math.log10(top)) if top > 0 else 0
    while e >= -digits:
        yield 10.0 ** e
        if e - 1 >= -digits:
            yield 5 * 10.0 ** (e - 1)
        e -= 1


def _nice_round(q: float, lo: float, hi: float, digits: int) -> float:
    """lo〜hi の範囲で、いちばん切りのよい数値を選ぶ。"""
    for step in _steps(max(abs(lo), abs(hi), abs(q)), digits):
        v = round(round(q / step) * step, digits)
        if lo <= v <= hi:
            return v
    return round(q, digits)


def _quantile_breaks(vals: list[float], classes: int, digits: int) -> list[float]:
    if len(vals) < 2 or classes < 2:
        return []
    qs = statistics.quantiles(vals, n=classes, method="inclusive")
    edges = [vals[0], *qs, vals[-1]]
    out: list[float] = []
    for i, q in enumerate(qs, start=1):
        lo = q - TOLERANCE * (q - edges[i - 1])
        hi = q + TOLERANCE * (edges[i + 1] - q)
        b = _nice_round(q, lo, hi, digits)
        if vals[0] < b <= vals[-1] and (not out or b > out[-1]):
            out.append(b)
    return out


def _refined_quantile_breaks(vals: list[float], classes: int, digits: int) -> list[float]:
    out = _quantile_breaks(vals, classes, digits)
    # 同じ値が多く区切りが減ったとき（件数の少ない指標など）は、いちばん上の階級をさらに分ける
    while out and len(out) < classes - 1:
        tail = [v for v in vals if v > out[-1]]
        more = [b for b in _quantile_breaks(tail, classes - len(out), digits) if b > out[-1]]
        if not more:
            break
        out += more[: classes - 1 - len(out)]
    return out


def _on_grid(step: float, digits: int) -> bool:
    """表示の桁（digits）で割り切れる刻みか（小数0桁なら 2.5 は使わない）。"""
    x = step * 10 ** digits
    return x >= 1 and abs(x - round(x)) < 1e-9


def _interval_breaks(vals: list[float], classes: int, digits: int, trim: float = 0.0) -> list[float]:
    """切りのよい刻みの等間隔のうち、区切りが classes-1 個以内に収まる最も細かいもの。

    trim > 0 なら両端の trim の割合の値（飛び抜けた地域）を除いた範囲を等分し、両端の階級は「未満」「以上」で受ける。
    """
    lo, hi = vals[0], vals[-1]
    if trim:
        k = int(len(vals) * trim)
        lo, hi = vals[k], vals[-1 - k]
    if hi <= lo:
        return []
    steps = sorted({round(10.0 ** e * m, 12) for e in range(-digits, math.floor(math.log10(hi - lo)) + 2)
                    for m in (1, 2, 2.5, 5) if _on_grid(10.0 ** e * m, digits)})
    for step in steps:
        out, b = [], math.floor(lo / step) * step + step
        while b < hi and len(out) < classes:
            out.append(round(b, digits))
            b += step
        if len(out) <= classes - 1:
            # 区分が少なくなりすぎる（10区分未満）なら等間隔は使わない
            return out if len(out) >= classes - 3 else []
    return []


def _max_share(vals: list[float], breaks: list[float]) -> float:
    counts = [0] * (len(breaks) + 1)
    for v in vals:
        counts[bisect.bisect_right(breaks, v)] += 1
    return max(counts) / len(vals)


def nice_breaks(values: list[float], classes: int, digits: int) -> list[float]:
    vals = sorted(values)
    if len(vals) < 2:
        return []
    for trim in (0.0, TRIM):
        equal = _interval_breaks(vals, classes, digits, trim)
        if equal and _max_share(vals, equal) <= MAX_SHARE:
            return equal
    return _refined_quantile_breaks(vals, classes, digits)


def diverging_breaks(values: list[float], classes: int, digits: int) -> list[float]:
    """0（増減なし）を境にし、減少側・増加側をそれぞれ classes/2 の階級に分ける。"""
    half = max(1, classes // 2)
    neg = sorted(-v for v in values if v < 0)
    pos = sorted(v for v in values if v > 0)
    below = [-b for b in reversed(_refined_quantile_breaks(neg, half, digits))] if len(neg) >= 2 else []
    above = _refined_quantile_breaks(pos, half, digits) if len(pos) >= 2 else []
    return [*below, 0.0, *above]
