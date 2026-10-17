// ビルド時（Astro のページ生成）にだけ使うデータ読込。ブラウザでは使わない。
import { readFileSync } from "node:fs";
import { join } from "node:path";
import release from "../generated/release.json";
import type { PlacePoints } from "./placeStats";
import type { Geometry } from "./shape";
import type {
  AreasFile, IndicatorCatalog, LegendFile, ReleaseInfo, SmallArea, SmallAreasFile, Source, ValueRow, ValuesFile,
} from "./types";

export const RELEASE = release as ReleaseInfo;
export const DATA_BASE = `/data/${RELEASE.release_id}`;

// 読んだファイルはビルドの間とっておく（市区町村のページ約1,900件がそれぞれ全指標の値を読むため、
// 毎回読み直すとページの生成に数分かかる）。返した値はページ側で書き換えないこと
const cache = new Map<string, unknown>();

function read<T>(rel: string): T {
  if (!cache.has(rel)) {
    cache.set(rel, JSON.parse(readFileSync(join(process.cwd(), "public", DATA_BASE, rel), "utf8")));
  }
  return cache.get(rel) as T;
}

/** 地図の点レイヤーのデータ（駅・学校・地価公示）。公開版にないときは null */
export function loadPlace(name: string): { name: string; unit: string; description: string; periods: { label: string }[] } | null {
  try {
    return read(`places/${name}.json`);
  } catch {
    return null;
  }
}

export const loadIndicators = () => read<IndicatorCatalog>("indicators.json").indicators;
export const loadAreas = () => read<AreasFile>("areas.json");
export const loadSources = () => read<{ sources: Source[] }>("sources.json").sources;

export function loadValues(indicatorId: string, period: string, chunk: string): ValuesFile | null {
  try {
    return read<ValuesFile>(`values/${indicatorId}/${period}/${chunk}.json`);
  } catch {
    return null;
  }
}

/** 色分けの区切り（地図と同じ。地図の画像に使う）。ないときは null */
export function loadLegend(indicatorId: string, period: string): LegendFile | null {
  try {
    return read<LegendFile>(`values/${indicatorId}/${period}/legend.json`);
  } catch {
    return null;
  }
}

// 境界ファイルは形を含んで大きいので、名前などだけをとっておく
const smallAreasCache = new Map<string, SmallArea[]>();

/** 町丁・字等の名前・範囲・代表点（区市町村ごとの境界ファイルから）。ないときは null */
export function loadSmallAreas(municipalityCode: string): SmallArea[] | null {
  try {
    if (!smallAreasCache.has(municipalityCode)) {
      const rel = `boundaries/${loadAreas().boundary_version}/${municipalityCode}.geojson`;
      const gj = JSON.parse(readFileSync(join(process.cwd(), "public", DATA_BASE, rel), "utf8")) as SmallAreasFile;
      smallAreasCache.set(municipalityCode, gj.features.map((f) => f.properties));
    }
    return smallAreasCache.get(municipalityCode)!;
  } catch {
    return null;
  }
}

/**
 * 町丁・字等の値のある行を、指定した都道府県のファイルからまとめて読む（指標ページのランキング用）。
 * 全国では大きいので、ほかと違ってとっておかずに読むたびに捨てる。
 */
export function loadSmallAreaRows(indicatorId: string, period: string, prefectures: string[]): ValueRow[] {
  const out: ValueRow[] = [];
  for (const pref of prefectures) {
    let file: ValuesFile;
    try {
      file = JSON.parse(readFileSync(
        join(process.cwd(), "public", DATA_BASE, `values/${indicatorId}/${period}/${pref}.json`), "utf8"));
    } catch {
      continue;
    }
    for (const r of file.rows) {
      if (r.value !== null) out.push({ entity_id: r.entity_id, value: r.value, status: r.status });
    }
  }
  return out;
}

// 地域ページの町丁目別ランキング用。都道府県のファイルを市区町村ごとに分けて、直近に読んだ数件だけとっておく
// （地域ページは市区町村コードの順に作られるので、同じ都道府県のファイルを続けて使う。全国分をとっておくと大きすぎる）
const smallAreaByMuni = new Map<string, Map<string, ValueRow[]>>();
const SMALL_AREA_KEEP = 6;

/** 町丁・字等の値（値のある行だけ）を、市区町村コードごとに分けて返す。ファイルがないときは空 */
export function loadSmallAreaRowsByMunicipality(indicatorId: string, period: string, prefecture: string): Map<string, ValueRow[]> {
  const key = `${indicatorId}/${period}/${prefecture}`;
  const hit = smallAreaByMuni.get(key);
  if (hit) return hit;
  const byMuni = new Map<string, ValueRow[]>();
  for (const r of loadSmallAreaRows(indicatorId, period, [prefecture])) {
    const code = r.entity_id.slice(5, 10);
    if (!byMuni.has(code)) byMuni.set(code, []);
    byMuni.get(code)!.push(r);
  }
  smallAreaByMuni.set(key, byMuni);
  if (smallAreaByMuni.size > SMALL_AREA_KEEP) smallAreaByMuni.delete(smallAreaByMuni.keys().next().value!);
  return byMuni;
}

/** 境界（GeoJSON）。name は boundaries/<版>/ の下のパス（"prefectures"・"municipalities/13" など）。ないときは null */
export function loadBoundaries(name: string): { features: { properties: { id: string }; geometry: Geometry }[] } | null {
  try {
    return read(`boundaries/${loadAreas().boundary_version}/${name}.geojson`);
  } catch {
    return null;
  }
}

/** 点のデータの都道府県ごとのファイルをまとめて読む（ないときは空） */
function placeRows<T>(name: string, key: string): T[] {
  const index = loadPlace(name) as { prefectures?: Record<string, unknown> } | null;
  if (!index?.prefectures) return [];
  return Object.keys(index.prefectures).flatMap((code) => {
    try {
      return read<Record<string, T[]>>(`places/${name}/${code}.json`)[key] ?? [];
    } catch {
      return [];
    }
  });
}

let placePoints: PlacePoints | null | undefined;
/** 地域ページの考察に使う、全国の駅・空港・港・地価公示・都道府県地価調査・天気の点（ビルドの間とっておく） */
export function loadPlacePoints(): PlacePoints | null {
  if (placePoints !== undefined) return placePoints;
  type Indexed = { periods: { label: string }[]; points?: never[]; stations?: never[] };
  const labels = (name: string) => ((loadPlace(name) as Indexed | null)?.periods ?? []).map((p) => p.label);
  const inline = <T>(name: string, key: "points" | "stations") => ((loadPlace(name) as Indexed | null)?.[key] ?? []) as T[];
  placePoints = {
    stations: placeRows("station_passengers", "stations"),
    stationPeriods: labels("station_passengers"),
    land: placeRows("land_price", "points"),
    landPeriods: labels("land_price"),
    landSurvey: placeRows("land_survey_price", "points"),
    landSurveyPeriods: labels("land_survey_price"),
    airports: inline("airport_passengers", "points"),
    airportPeriods: labels("airport_passengers"),
    ports: inline("port_passengers", "points"),
    portPeriods: labels("port_passengers"),
    weather: inline("weather_normals", "stations"),
    weatherLabel: labels("weather_normals")[0] ?? "",
    centers: new Map(loadAreas().municipalities.map((m) => [m.id, m.center as [number, number]])),
  };
  return placePoints;
}
