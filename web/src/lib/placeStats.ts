// 地図の点のデータ（駅・空港・港・地価公示・天気の観測所）を市区町村ごとにまとめ、全国の中の位置を出す。
// 地域ページの「データで見る〇〇」の考察に使う（areaInsights）。点の値をそのまま使い、地域に割り振る推計はしない。

export interface PlacePoints {
  stations: { name: string; group?: string; operator?: string; municipality_id: string; values: (number | null)[] }[];
  stationPeriods: string[];
  land: { municipality_id: string; use: string; values: (number | null)[] }[];
  landPeriods: string[];
  /** 都道府県地価調査（地価公示の住宅地の地点がない市区町村だけに使う） */
  landSurvey?: { municipality_id: string; use: string; values: (number | null)[] }[];
  landSurveyPeriods?: string[];
  airports: { name: string; municipality_id: string; values: (number | null)[]; international?: (number | null)[] }[];
  airportPeriods: string[];
  ports: { name: string; municipality_id: string; values: (number | null)[] }[];
  portPeriods: string[];
  weather: { name: string; municipality_id: string; coord: [number, number]; altitude_m?: number | null; values: Record<string, number | null | undefined> }[];
  weatherLabel: string;
  /** 市区町村の代表点（天気の観測所が複数あるとき、代表点に近い観測所を選ぶ） */
  centers: Map<string, [number, number]>;
}

/** 全国の中の位置（0〜1）。top は大きい方から、bottom は小さい方から */
export interface Pos { top: number; bottom: number; count: number }

export interface MuniPlaces {
  /** いちばん利用者の多い駅（同じ駅グループの事業者の値の合計） */
  station?: { name: string; total: number; operators: number; label: string; pos: Pos; stationCount: number };
  airport?: { name: string; value: number; international: number; label: string; pos: Pos };
  port?: { name: string; value: number; label: string; pos: Pos };
  /**
   * 住宅地の地価公示の価格（地点の中央値）と、5年前からの変化（同じ地点の変化率の中央値）。
   * 地価公示の住宅地の地点がない市区町村は都道府県地価調査の値（survey: true）で、全国の中の位置は見ない
   */
  land?: { median: number; points: number; label: string; pos: Pos; survey?: boolean; change?: { rate: number; points: number; from: string; pos: Pos } };
  /** 代表点にいちばん近い観測所の平年値（要素ごと）と標高 */
  weather?: { station: string; altitude: number | null; label: string; values: Record<string, { value: number; pos: Pos; station: string }> };
}

const median = (xs: number[]) => {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

/** 値の並びの中の位置を返す関数を作る（同じ値は同じ位置） */
function ranker(values: number[]): (v: number) => Pos {
  const s = [...values].sort((a, b) => a - b);
  const n = s.length;
  const lower = (v: number, strict: boolean) => {
    let lo = 0, hi = n;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (strict ? s[mid] < v : s[mid] <= v) lo = mid + 1; else hi = mid; }
    return lo;
  };
  return (v) => ({ top: (n - lower(v, false) + 1) / n, bottom: (lower(v, true) + 1) / n, count: n });
}

/** 最後の値（並びの後ろから見て最初の null でない値）とその位置。古すぎる値（recent より前）は使わない */
function latest(values: (number | null)[], recent = 3): [number, number] | null {
  for (let i = values.length - 1; i >= Math.max(0, values.length - recent); i--) {
    const v = values[i];
    if (v !== null && v !== undefined) return [v, i];
  }
  return null;
}

export function summarizePlaces(p: PlacePoints): Map<string, MuniPlaces> {
  const out = new Map<string, MuniPlaces>();
  const get = (id: string) => { let m = out.get(id); if (!m) { m = {}; out.set(id, m); } return m; };

  // 駅: 同じ駅グループ（乗り換えのできる駅）の事業者の値を、同じ年度でそろえて合計する
  const complexes = new Map<string, { muni: string; points: PlacePoints["stations"] }>();
  for (const s of p.stations) {
    const key = `${s.municipality_id}|${s.group ?? s.name}`;
    const c = complexes.get(key) ?? { muni: s.municipality_id, points: [] };
    c.points.push(s);
    complexes.set(key, c);
  }
  const best = new Map<string, NonNullable<MuniPlaces["station"]> & { count: number }>();
  const stationCount = new Map<string, number>();
  for (const c of complexes.values()) {
    stationCount.set(c.muni, (stationCount.get(c.muni) ?? 0) + 1);
    const idx = Math.max(...c.points.map((s) => latest(s.values)?.[1] ?? -1));
    if (idx < 0) continue;
    const withValue = c.points.filter((s) => s.values[idx] != null);
    const total = withValue.reduce((a, s) => a + (s.values[idx] as number), 0);
    const top = withValue.reduce((a, s) => ((s.values[idx] as number) > (a.values[idx] as number) ? s : a));
    const cur = best.get(c.muni);
    if (!cur || total > cur.total) {
      best.set(c.muni, { name: top.name, total, operators: withValue.length, label: p.stationPeriods[idx] ?? "", pos: { top: 1, bottom: 1, count: 0 }, stationCount: 0, count: 0 });
    }
  }
  const stationRank = ranker([...best.values()].map((b) => b.total));
  for (const [muni, b] of best) {
    get(muni).station = { name: b.name, total: b.total, operators: b.operators, label: b.label, pos: stationRank(b.total), stationCount: stationCount.get(muni) ?? 0 };
  }

  // 空港・港: 市区町村にある中でいちばん利用者の多いもの。位置は全国の空港・港の中で見る
  const airports = p.airports.map((a) => ({ a, l: latest(a.values, 2) })).filter((x) => x.l && x.l[0] > 0);
  const airportRank = ranker(airports.map((x) => x.l![0]));
  for (const { a, l } of airports) {
    const m = get(a.municipality_id);
    if (m.airport && m.airport.value >= l![0]) continue;
    const intl = a.international?.[l![1]] ?? 0;
    m.airport = { name: a.name, value: l![0], international: intl ?? 0, label: p.airportPeriods[l![1]] ?? "", pos: airportRank(l![0]) };
  }
  const ports = p.ports.map((x) => ({ x, l: latest(x.values, 2) })).filter((y) => y.l && y.l[0] > 0);
  const portRank = ranker(ports.map((y) => y.l![0]));
  for (const { x, l } of ports) {
    const m = get(x.municipality_id);
    if (m.port && m.port.value >= l![0]) continue;
    m.port = { name: x.name, value: l![0], label: p.portPeriods[l![1]] ?? "", pos: portRank(l![0]) };
  }

  // 地価公示: 住宅地の地点だけ。最新の年の価格の中央値と、5年前と同じ地点の変化率の中央値
  const residential = (points: PlacePoints["land"], periods: string[]) => {
    const last = periods.length - 1;
    const from = last - 5;
    const byMuni = new Map<string, PlacePoints["land"]>();
    for (const pt of points) {
      if (pt.use !== "000" || pt.values[last] == null) continue;
      const list = byMuni.get(pt.municipality_id) ?? [];
      list.push(pt);
      byMuni.set(pt.municipality_id, list);
    }
    return [...byMuni].map(([muni, pts]) => {
      const rates = from >= 0 ? pts.filter((x) => x.values[from]).map((x) => ((x.values[last] as number) / (x.values[from] as number) - 1) * 100) : [];
      return { muni, median: median(pts.map((x) => x.values[last] as number)), points: pts.length, rates, label: periods[last] ?? "", from: periods[from] ?? "" };
    });
  };
  const lands = residential(p.land, p.landPeriods);
  const priceRank = ranker(lands.map((l) => l.median));
  const changed = lands.filter((l) => l.rates.length >= 2);
  const changeRank = ranker(changed.map((l) => median(l.rates)));
  for (const l of lands) {
    const rate = l.rates.length >= 2 ? median(l.rates) : null;
    get(l.muni).land = {
      median: l.median, points: l.points, label: l.label, pos: priceRank(l.median),
      change: rate === null ? undefined : { rate, points: l.rates.length, from: l.from, pos: changeRank(rate) },
    };
  }
  // 地価公示の住宅地の地点がない市区町村は、都道府県地価調査の住宅地の地点で同じように見る（調べ方・時点が違うので順位は付けない）
  const none: Pos = { top: 1, bottom: 1, count: 0 };
  for (const l of residential(p.landSurvey ?? [], p.landSurveyPeriods ?? [])) {
    if (out.get(l.muni)?.land) continue;
    get(l.muni).land = {
      median: l.median, points: l.points, label: l.label, pos: none, survey: true,
      change: l.rates.length >= 2 ? { rate: median(l.rates), points: l.rates.length, from: l.from, pos: none } : undefined,
    };
  }

  // 天気: 要素ごとに、値のある観測所のうち市区町村の代表点に近いものを使う。位置は全国の観測所の中で見る
  const elements = [...new Set(p.weather.flatMap((s) => Object.keys(s.values)))];
  const elementRank = new Map(elements.map((e) => [e, ranker(p.weather.map((s) => s.values[e]).filter((v): v is number => v != null))]));
  const stationsByMuni = new Map<string, PlacePoints["weather"]>();
  for (const s of p.weather) {
    const list = stationsByMuni.get(s.municipality_id) ?? [];
    list.push(s);
    stationsByMuni.set(s.municipality_id, list);
  }
  for (const [muni, list] of stationsByMuni) {
    const c = p.centers.get(muni);
    const dist = (s: PlacePoints["weather"][number]) => (c ? Math.hypot(s.coord[0] - c[0], s.coord[1] - c[1]) : 0);
    const sorted = [...list].sort((a, b) => dist(a) - dist(b));
    const values: NonNullable<MuniPlaces["weather"]>["values"] = {};
    for (const e of elements) {
      const s = sorted.find((x) => x.values[e] != null);
      if (s) values[e] = { value: s.values[e] as number, pos: elementRank.get(e)!(s.values[e] as number), station: s.name };
    }
    get(muni).weather = { station: sorted[0].name, altitude: sorted[0].altitude_m ?? null, label: p.weatherLabel, values };
  }
  return out;
}

/** 人数を「約12万人」「3,456人」のように書く */
export function approxCount(n: number, unit = "人"): string {
  if (n >= 100_000) return `約${Math.round(n / 10_000).toLocaleString("ja-JP")}万${unit}`;
  if (n >= 10_000) return `約${(Math.round(n / 1_000) / 10).toLocaleString("ja-JP")}万${unit}`;
  return `${Math.round(n).toLocaleString("ja-JP")}${unit}`;
}
