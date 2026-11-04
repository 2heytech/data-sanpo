// 政令指定都市の市全体の値（設計変更記録 #191）。
// 地図と市区町村のランキングは政令指定都市を区ごとに並べるので、指標ページに市全体の表を添える。
// 市全体の値は区の分子・分母（人数・件数は値）を合計して計算し、値のない区が1つでもあれば値なしにする
// （都道府県の値と同じ決まり。欠けた区を0とみなさない）。平均など区から足せない値の指標は計算しない。
import type { Indicator, Municipality, ValueRow } from "./types";

export interface DesignatedCity {
  /** 市の名前（「横浜市」） */
  name: string;
  /** 都道府県コード */
  prefecture: string;
  /** 区の地域 ID（地図と地域ページの境界の区。区を再編した浜松市は2020年の7区） */
  wards: string[];
}

/** 地域の一覧から政令指定都市と区を集める（区の region は市の名前で、名前が市の名前から始まる） */
export function designatedCities(municipalities: Municipality[]): DesignatedCity[] {
  const byCity = new Map<string, DesignatedCity>();
  for (const m of municipalities) {
    const city = m.region;
    if (!city || !city.endsWith("市") || m.name === city || !m.name.startsWith(city)) continue;
    const key = `${m.prefecture}:${city}`;
    if (!byCity.has(key)) byCity.set(key, { name: city, prefecture: m.prefecture, wards: [] });
    byCity.get(key)!.wards.push(m.id);
  }
  return [...byCity.values()].filter((c) => c.wards.length > 1);
}

export interface CityValue {
  city: DesignatedCity;
  value: number | null;
  /** 値がないときの理由 */
  note?: string;
}

/** 区の値から市全体の値を計算できる指標か（区分で公表された値は合計も平均もできない） */
export const summable = (ind: Indicator) => !ind.legend?.band;

/**
 * 政令指定都市ごとの市全体の値。分子・分母のある指標は合計してから割り、人数・件数は値を合計する。
 * 計算できない指標（分子・分母のない平均など）は null を返す
 */
export function cityValues(ind: Indicator, cities: DesignatedCity[], rows: ValueRow[]): CityValue[] | null {
  if (!summable(ind) || !cities.length) return null;
  const byId = new Map(rows.map((r) => [r.entity_id, r]));
  const scale = ind.scale ?? 1;
  let computable = true;
  const out = cities.map((city): CityValue => {
    const got = city.wards.map((id) => byId.get(id));
    if (got.every((r) => !r)) return { city, value: null, note: "この時点の区の値がありません" };
    if (got.some((r) => !r || r.value === null)) return { city, value: null, note: "値のない区があるため出していません" };
    const ok = got as ValueRow[];
    if (ok.every((r) => r.numerator !== undefined && r.denominator !== undefined)) {
      const num = ok.reduce((s, r) => s + r.numerator!, 0);
      const den = ok.reduce((s, r) => s + r.denominator!, 0);
      return den ? { city, value: (num / den) * scale } : { city, value: null, note: "値がありません" };
    }
    if (ind.kind === "count") return { city, value: ok.reduce((s, r) => s + r.value!, 0) };
    computable = false;
    return { city, value: null };
  });
  return computable ? out : null;
}
