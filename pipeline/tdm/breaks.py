"""凡例の区切り位置（docs/design-changes.md #35）。

- nice: まず切りのよい刻み（1, 2, 5 × 10^k など）の等間隔を試し、どの階級にも値が集まりすぎなければ使う。
  飛び抜けた地域があるときは、両端5%を除いた範囲の等間隔も試す（両端の階級は「未満」「以上」）。
  偏った分布（差の大きい指標）は等間隔だと大半が1色になるので、分位点の近くで切りのよい数値を選ぶ。
- diverging: 0 を境に、減少側・増加側をそれぞれ classes/2 の階級に分ける（区切りは切りのよい数値）。
- quantile: 分位点をそのまま区切りにする（切りのよい数値には寄せない）。
- national_breaks: 市区町村・町丁目の、全国で共通の区切り（#145）。nice・quantile の指標の市区町村・町丁目に使う。
区切りは「その値以上が次の階級」。切りのよい数値は 1000, 500, 100, 50, 10, 5, 1, 0.5, 0.1 … の順に探す。
"""
from __future__ import annotations

import bisect
import math
import statistics

MAX_SHARE = 0.25   # 等間隔で1つの階級にこれより多く集まるなら分位点の方式にする
TRIM = 0.05       # 等間隔で飛び抜けた値に引っぱられるときは、両端5%を除いた範囲を等分する
TOLERANCE = 0.5    # 分位点から隣の分位点までの距離のうち、ずらしてよい割合（中間点まで）

# 全国で共通の区切り（市区町村・町丁目。#145）
FINE_CLASSES = 20  # 区分の上限
BASE_CLASSES = 12  # 最初に目盛りで分ける区分の上限（残りは地域の多い区分を分けて足す）
EDGE = 0.005       # 目盛りの範囲から外す両端の割合（飛び抜けた地域は「未満」「以上」の区分に入れる）
SKEW = 0.25        # 中央値が5%点〜95%点の幅の下から1/4に届かない分布は、桁で分ける目盛りにする
LOG_STEPS = ((1,), (1, 3), (1, 2, 5), (1, 2, 3, 5, 7))   # 桁ごとの目盛り（粗い順）


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
    out = _refined_quantile_breaks(vals, classes, digits)
    if not out and vals[0] < vals[-1]:
        out = _split_off_minimum(vals, classes, digits)
    return out


def _split_off_minimum(vals: list[float], classes: int, digits: int) -> list[float]:
    """ほとんどが最小値（例: 県内の大半が0%）で分位点の区切りが作れないときは、最小値とそれより大きい値を分け、
    大きい側をさらに区切る（区切りがないと、0% の市区町村も値のある市区町村と同じ色になるため）。"""
    upper = [v for v in vals if v > vals[0]]
    b = round(math.floor(upper[0] * 10 ** digits) / 10 ** digits, digits)
    if b <= vals[0]:
        b = upper[0]   # 表示の桁より細かい差（値は区切りちょうどで上の階級に入る）
    more = [x for x in _refined_quantile_breaks(upper, classes - 1, digits) if x > b] if len(upper) >= 2 else []
    return [b, *more]


def diverging_breaks(values: list[float], classes: int, digits: int) -> list[float]:
    """0（増減なし）を境にし、減少側・増加側をそれぞれ classes/2 の階級に分ける。"""
    half = max(1, classes // 2)
    neg = sorted(-v for v in values if v < 0)
    pos = sorted(v for v in values if v > 0)
    below = [-b for b in reversed(_refined_quantile_breaks(neg, half, digits))] if len(neg) >= 2 else []
    above = _refined_quantile_breaks(pos, half, digits) if len(pos) >= 2 else []
    return [*below, 0.0, *above]


def quantile_breaks(values: list[float], classes: int, digits: int) -> list[float]:
    """分位点（表示の桁に丸めたもの）をそのまま区切りにする。同じ値になった区切りは1つにまとめる。"""
    if len(values) < 2:
        return []
    qs = statistics.quantiles(values, n=classes, method="inclusive")
    breaks: list[float] = []
    for q in qs:
        b = round(q, digits)
        if not breaks or b > breaks[-1]:
            breaks.append(b)
    return breaks


def _pct(vals: list[float], p: float) -> float:
    return vals[min(len(vals) - 1, max(0, round(p * (len(vals) - 1))))]


def _right_skewed(vals: list[float]) -> bool:
    """右に裾の長い分布か（人口・件数・金額のように、数百から数十万まで桁の違う値が並ぶ指標）。"""
    p5, p50, p95 = _pct(vals, 0.05), _pct(vals, 0.5), _pct(vals, 0.95)
    return vals[0] >= 0 and p95 > p5 and (p50 - p5) / (p95 - p5) < SKEW


def _displayable(b: float, digits: int) -> bool:
    return b >= 10.0 ** -digits * (1 - 1e-9) and abs(round(b, digits) - b) <= 1e-9 * max(1.0, abs(b))


def _log_scale(vals: list[float], classes: int, digits: int) -> list[float]:
    """1・2・5 の倍数のような、桁ごとの目盛り。区切りが classes-1 個以内に収まる最も細かいもの。"""
    pos = [v for v in vals if v > 0]
    if len(pos) < 2:
        return []
    lo, hi = max(_pct(pos, EDGE), 10.0 ** -digits), pos[-1]
    out: list[float] = []
    for steps in LOG_STEPS:
        grid = sorted({round(m * 10.0 ** e, digits)
                       for e in range(math.floor(math.log10(lo)) - 1, math.floor(math.log10(hi)) + 2)
                       for m in steps if _displayable(m * 10.0 ** e, digits)})
        start = max([b for b in grid if b <= lo], default=grid[0])
        cand = [b for b in grid if start <= b <= hi and b > vals[0]]
        if len(cand) > classes - 1:
            break
        out = cand
    return out


def _linear_scale(vals: list[float], classes: int, digits: int) -> list[float]:
    """切りのよい刻みの等間隔の目盛り（両端の EDGE を除いた範囲）。区切りが classes-1 個以内に収まる最も細かいもの。"""
    lo, hi = _pct(vals, EDGE), _pct(vals, 1 - EDGE)
    if hi <= lo:
        return []
    steps = sorted({round(10.0 ** e * m, 12) for e in range(-digits, math.floor(math.log10(hi - lo)) + 2)
                    for m in (1, 2, 2.5, 5) if _on_grid(10.0 ** e * m, digits)})
    for step in steps:
        out, b = [], math.floor(lo / step) * step + step
        while b <= hi and len(out) < classes:
            out.append(round(b, digits))
            b += step
        if len(out) <= classes - 1:
            return out
    return []


def _weight(part: list[float], log: bool) -> float:
    """区分を分ける順の重み: 地域の数 × 値の幅（桁の目盛りでは倍率の対数）。
    地域の多く集まる区分と、値の幅の広い区分（人口の多い区がまとまる上の端など）を先に分ける。"""
    if log:
        pos = [v for v in part if v > 0]
        span = math.log(pos[-1] / pos[0]) if len(pos) > 1 else 0.0
    else:
        span = part[-1] - part[0]
    return len(part) * span if span > 0 else 0.0


def _split_one(vals: list[float], breaks: list[float], digits: int, log: bool) -> list[float] | None:
    """重みのいちばん大きい区分を、その区分の中央値に近い切りのよい数値で2つに分ける。分けられなければ None。"""
    idx = [0, *(bisect.bisect_left(vals, b) for b in breaks), len(vals)]
    parts = [vals[idx[i]:idx[i + 1]] for i in range(len(idx) - 1)]
    for part in sorted((p for p in parts if len(p) >= 2 and p[0] < p[-1]), key=lambda p: -_weight(p, log)):
        q = statistics.median(part)
        for b in (_nice_round(q, _pct(part, 0.25), _pct(part, 0.75), digits), round(q, digits)):
            if part[0] < b <= part[-1] and b not in breaks:
                return sorted([*breaks, b])
    return None


def _round_down(v: float, digits: int) -> float:
    """v 以下で最大の切りのよい数値（1・2・5 × 10^k）。v が表示の桁より小さいときは表示の桁の1
    （表示すると 0 になる値は 0 と同じ区分にする）。"""
    e = math.floor(math.log10(v))
    for m in (5, 2, 1):
        b = round(m * 10.0 ** e, 12)
        if b <= v and _displayable(b, digits):
            return round(b, digits)
    return 10.0 ** -digits


def _drop_empty(vals: list[float], breaks: list[float]) -> list[float]:
    """値の入らない区分ができる区切りを除く（目盛りの間に地域がないときは、隣の区分とまとめる）。"""
    out: list[float] = []
    for b in breaks:
        lo = bisect.bisect_left(vals, out[-1]) if out else 0
        if bisect.bisect_left(vals, b) > lo and vals[-1] >= b:
            out.append(b)
    return out


def national_breaks(values: list[float], classes: int, digits: int) -> list[float]:
    """全国で共通の区切り（市区町村・町丁目。#145）。

    1. 値の範囲を、切りのよい目盛りで BASE_CLASSES 以内に分ける。右に裾の長い分布（人口・件数・金額など）は
       1・2・5 などの倍数の桁ごとの目盛り、ほかは等間隔の目盛り。端の区分も目盛りで分かれるので、
       人口の多い区どうし・少ない村どうしも同じ色にまとまりにくい。
    2. 地域の多く集まる区分を、切りのよい数値で2つに分けることを classes 区分になるまで繰り返す。
    0 とそれより大きい値は分ける（0 の地域が値のある地域と同じ色にならないように。#75）。
    """
    vals = sorted(values)
    if len(vals) < 2 or vals[0] == vals[-1]:
        return []
    log = _right_skewed(vals)
    out = _drop_empty(vals, (_log_scale if log else _linear_scale)(vals, BASE_CLASSES, digits))
    upper = [v for v in vals if v > 0]
    if vals[0] == 0 and upper and (not out or out[0] > upper[0]):
        b = _round_down(upper[0], digits)
        if vals[-1] >= b:
            out = sorted({*out, b})
    while len(out) < classes - 1:
        nxt = _split_one(vals, out, digits, log)
        if nxt is None:
            break
        out = nxt
    return out
