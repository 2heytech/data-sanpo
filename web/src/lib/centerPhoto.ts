// 地域ページの「中心部の昔と今」の航空写真（設計変更記録 #215）。ビルド時とブラウザの両方で使う（node の読み込みはしない）。
// 中心部は、その市区町村で1日の乗降客数がいちばん多い駅（乗り換えのできる駅は事業者の合計。空港の駅は除く）。
// 乗降客数の分かる駅がない市区町村は、地価がいちばん高い商業地の地点（地価公示・都道府県地価調査の最新の価格。
// 商業地の地点がなければ、ほかの用途も含めていちばん高い地点）。どちらもなければ、国勢調査で人口がいちばん多い町丁目の代表点（#219）。
// 写真は地理院タイルをそのまま並べる（サイトの静的ファイルは増やさない）。
import { PHOTO_ERAS, type PhotoEra } from "../map/photoEras";
import type { LandPoint, School, SmallArea, Station } from "./types";

/** 地価公示・都道府県地価調査の用途のコードのうち商業地 */
const COMMERCIAL = "005";

/**
 * 写真の縮尺。z16 のタイルを 128 CSS 画素で並べる（高精細の画面でもくっきり見える）。
 * 地図の縮尺（MapLibre は 512 画素のタイルで数える）では 14 にあたる。写真を押して開く地図もこの縮尺にする
 */
export const PHOTO_MAP_ZOOM = 14;
/** 写真の欄のいちばん大きいときの大きさ（CSS 画素）。これを覆うだけのタイルを並べ、はみ出した分は隠す */
export const PHOTO_BOX = { width: 440, height: 330 } as const;

/** 昔の写真の候補（古い順）。年度別空中写真（2007年度〜）と最新の写真は「昔」にしない */
export const OLD_PHOTO_ERAS: PhotoEra[] = PHOTO_ERAS.filter((e) => /^photo\d{4}$/.test(e.id));
export const LATEST_PHOTO_ERA: PhotoEra = PHOTO_ERAS.find((e) => e.id === "photo")!;

/** 乗降客数がいちばん多い駅 */
export interface StationSpot {
  kind: "station";
  lng: number;
  lat: number;
  /** 駅の名前（「金沢」。「駅」は付けない） */
  name: string;
  /** 1日の乗降客数（乗り換えのできる駅は事業者の合計） */
  passengers: number;
  /** 乗降客数の年度（「2024年度」） */
  year: string;
}

/** 地価がいちばん高い地点（乗降客数の分かる駅がない市区町村） */
export interface LandSpot {
  kind: "land";
  lng: number;
  lat: number;
  /** 商業地の地点か */
  commercial: boolean;
  /** 用途（商業地・住宅地など） */
  use: string;
  /** 都道府県地価調査の地点か（でなければ地価公示） */
  survey: boolean;
  /** 価格の年（「2026年」） */
  year: string;
  /** 所在地の町名（「本町2丁目」など）。読み取れないときは null */
  place: string | null;
  /** 最寄りの駅（1km 以内の駅だけ） */
  station: { name: string; distance: number } | null;
}

/** 人口がいちばん多い町丁目（乗降客数の分かる駅も地価の地点もない市区町村） */
export interface TownSpot {
  kind: "town";
  /** 町丁目の代表点 */
  lng: number;
  lat: number;
  /** 町丁目の名前（境界の名前のまま。「大字長塚」） */
  name: string;
  /** 国勢調査の人口 */
  population: number;
  /** 国勢調査の年（「2020年」） */
  year: string;
  /** これより新しい国勢調査で人口のいる町丁目がなかった年（古い順。「2015年」「2020年」）。なければ空 */
  skipped: string[];
  /**
   * 町丁目が市区町村のほぼ全体にあたる（島の村など、町丁目の名前が市区町村の名前と同じ）とき、中心にした学校の名前。
   * 町丁目の範囲の真ん中は山や森になりやすいので、集落にある学校の位置にする。学校の位置がなければ null（町丁目の代表点のまま）
   */
  school: string | null;
}

export type CenterSpot = StationSpot | LandSpot | TownSpot;

export interface StationSource {
  stations: Pick<Station, "name" | "group" | "municipality_id" | "coord" | "values">[];
  /** 乗降客数の時点の名前（values と同じ順。「2024年度」） */
  periods: string[];
}

export interface LandSource {
  points: Pick<LandPoint, "municipality_id" | "coord" | "use" | "use_label" | "address" | "station" | "station_distance_m" | "values">[];
  /** 価格の時点の名前（values と同じ順。「2026年1月1日現在」） */
  periods: string[];
  survey: boolean;
}

export interface TownSource {
  /** 市区町村の名前 */
  muniName: string;
  /** 市区町村の町丁目（名前と代表点） */
  areas: Pick<SmallArea, "id" | "name" | "center">[];
  /** 国勢調査の町丁目の人口。新しい順 */
  censuses: { label: string; rows: { entity_id: string; value: number | null }[] }[];
  /** 市区町村の公立小中学校（町丁目が市区町村のほぼ全体にあたるときだけ使う） */
  schools: Pick<School, "id" | "name" | "school_type" | "coord" | "closed">[];
}

const toHalfWidth = (s: string) => s.replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0));
/** 「茅ヶ崎市」と「茅ケ崎市」のような書き方の違いをそろえる */
const sameKana = (s: string) => s.replace(/ヶ/g, "ケ");

/**
 * 地価の地点の所在地から町名を取り出す（「石川県 金沢市本町２丁目５７１番１外」→「本町2丁目」）。
 * 市区町村名の後ろから、地番（「５７１番１」）より前。大字・字は大字の名前だけにする（「大字北城字新田」→「北城」）
 */
export function placeName(address: string | null | undefined, muniName: string): string | null {
  if (!address) return null;
  // 書き方の違いはそろえて探す（同じ文字数なので位置は変わらない）
  const at = sameKana(address).indexOf(sameKana(muniName));
  if (at < 0) return null;
  let rest = address.slice(at + muniName.length).trim();
  rest = rest.replace(/[0-9０-９]+番.*$/, "").replace(/^(大字|字)/, "").replace(/^(.{2,}?)字.+$/, "$1")
    .replace(/(.{2,})[甲乙丙丁]$/, "$1");
  rest = toHalfWidth(rest).trim();
  return rest && !/[0-9]$/.test(rest) ? rest : null;
}

/** 最寄りの駅。バス停と、1km より遠い駅は出さない */
function nearStation(name: string | null | undefined, distance: number | null | undefined): LandSpot["station"] {
  if (!name || distance == null || distance > 1000 || name.startsWith("バス停")) return null;
  return { name: toHalfWidth(name), distance };
}

const yearOf = (label: string | undefined) => /^(\d{4})年/.exec(label ?? "")?.[1];

/**
 * 市区町村ごとの地価がいちばん高い地点。最新の時点に価格のある地点のうち、商業地でいちばん高い地点
 * （商業地がなければいちばん高い地点）。同じ価格なら先に渡した出典（地価公示）の地点にする
 */
export function landSpots(sources: LandSource[], names: Map<string, string>): Map<string, LandSpot> {
  const best = new Map<string, { key: [number, number]; spot: LandSpot }>();
  for (const src of sources) {
    const last = src.periods.length - 1;
    const year = yearOf(src.periods[last]);
    if (last < 0 || !year) continue;
    for (const p of src.points) {
      const value = p.values[last];
      const name = names.get(p.municipality_id);
      if (value == null || !name || !p.coord) continue;
      const commercial = p.use === COMMERCIAL;
      const key: [number, number] = [commercial ? 1 : 0, value];
      const cur = best.get(p.municipality_id);
      if (cur && (cur.key[0] > key[0] || (cur.key[0] === key[0] && cur.key[1] >= key[1]))) continue;
      best.set(p.municipality_id, {
        key,
        spot: {
          kind: "land", lng: p.coord[0], lat: p.coord[1], commercial, use: p.use_label, survey: src.survey, year: `${year}年`,
          place: placeName(p.address, name), station: nearStation(p.station, p.station_distance_m),
        },
      });
    }
  }
  return new Map([...best].map(([id, b]) => [id, b.spot]));
}

/** 空港の駅は、まちの中心ではないので選ばない（新千歳空港・成田空港・那覇空港など） */
const AIRPORT = /空港/;
/** 乗降客数はこれより前の年度の値を使わない（地域ページの考察と同じく最新から3つの年度まで） */
const STATION_RECENT = 3;

/**
 * 市区町村ごとに1日の乗降客数がいちばん多い駅。同じ駅グループ（乗り換えのできる駅）の事業者の値を、
 * 同じ年度でそろえて合計する（地域ページの考察と同じ数え方）。位置はグループの中でいちばん多い事業者の駅
 */
export function stationSpots(src: StationSource): Map<string, StationSpot> {
  const groups = new Map<string, StationSource["stations"]>();
  for (const s of src.stations) {
    if (AIRPORT.test(s.name) || !s.coord) continue;
    const key = `${s.municipality_id}|${s.group || s.name}`;
    groups.set(key, [...(groups.get(key) ?? []), s]);
  }
  const best = new Map<string, StationSpot>();
  for (const members of groups.values()) {
    let at = -1;
    for (const s of members) {
      for (let i = s.values.length - 1; i >= Math.max(0, s.values.length - STATION_RECENT); i--) {
        if (s.values[i] != null) { at = Math.max(at, i); break; }
      }
    }
    if (at < 0) continue;
    const counted = members.filter((s) => s.values[at] != null);
    const total = counted.reduce((a, s) => a + (s.values[at] as number), 0);
    const top = counted.reduce((a, s) => ((s.values[at] as number) > (a.values[at] as number) ? s : a));
    const muni = top.municipality_id;
    const cur = best.get(muni);
    // 乗降客数が 0 の駅（資料で 0 人の駅）は「いちばん多い駅」にしない
    if (total <= 0 || (cur && cur.passengers >= total)) continue;
    best.set(muni, { kind: "station", lng: top.coord[0], lat: top.coord[1], name: toHalfWidth(top.name).replace(/駅$/, ""),
      passengers: total, year: src.periods[at] ?? "" });
  }
  return best;
}

/** 町丁目の名前から大字・字を外す（「大字長塚」→「長塚」） */
const townName = (name: string) => toHalfWidth(name).replace(/^(大字|字)/, "");
const SCHOOL_ORDER: Record<string, number> = { elementary: 0, compulsory: 1, junior_high: 2 };

/**
 * 人口がいちばん多い町丁目。新しい国勢調査から順に、人口のいる町丁目がある最初の年で選ぶ
 * （同じ人口なら町丁目のコードの小さい方）。人口のいる町丁目がどの年にもなければ null。
 * 町丁目の名前が市区町村の名前と同じ（町丁目が市区町村のほぼ全体）なら、位置の分かる学校（小学校を先に）を中心にする
 */
export function townSpot(src: TownSource): TownSpot | null {
  const areas = new Map(src.areas.map((a) => [a.id, a]));
  const skipped: string[] = [];
  for (const census of src.censuses) {
    const year = yearOf(census.label);
    if (!year) continue;
    let best: { area: TownSource["areas"][number]; value: number } | null = null;
    for (const r of census.rows) {
      const area = areas.get(r.entity_id);
      if (!area || r.value == null || r.value <= 0) continue;
      if (!best || r.value > best.value || (r.value === best.value && area.id < best.area.id)) best = { area, value: r.value };
    }
    if (best) {
      const whole = sameKana(townName(best.area.name)) === sameKana(src.muniName);
      const school = whole
        ? src.schools.filter((x) => x.coord && !x.closed)
          .sort((a, b) => (SCHOOL_ORDER[a.school_type] ?? 9) - (SCHOOL_ORDER[b.school_type] ?? 9) || a.id.localeCompare(b.id))[0]
        : undefined;
      const [lng, lat] = school?.coord ?? best.area.center;
      return { kind: "town", lng, lat, name: best.area.name, population: best.value, year: `${year}年`, skipped,
        school: school ? toHalfWidth(school.name) : null };
    }
    skipped.unshift(`${year}年`);
  }
  return null;
}

/**
 * 中心部: 乗降客数がいちばん多い駅、なければ地価がいちばん高い地点、どちらもなければ人口がいちばん多い町丁目。
 * towns は町丁目の名前と人口を返す（駅も地価の地点もない市区町村の分だけ読む）
 */
export function centerSpots(stations: StationSource, lands: LandSource[], names: Map<string, string>,
  towns?: (id: string) => TownSource | null): Map<string, CenterSpot> {
  const out = new Map<string, CenterSpot>(landSpots(lands, names));
  for (const [id, spot] of stationSpots(stations)) if (names.has(id)) out.set(id, spot);
  if (towns) {
    for (const id of names.keys()) {
      if (out.has(id)) continue;
      const src = towns(id);
      const spot = src && townSpot(src);
      if (spot) out.set(id, spot);
    }
  }
  return out;
}

/**
 * 写真の見出しに添える場所（「金沢駅」「本町2丁目」「長塚」「利島小学校」）。見出しでは「（〇〇周辺）」と書く。
 * 地価の地点で町名が読み取れない（市区町村の名前と同じも含む）ときは最寄りの駅。町丁目の名前が市区町村の名前と同じで学校もないときや、
 * 何もないときは null
 */
export function spotArea(spot: CenterSpot, muniName: string): string | null {
  if (spot.kind === "station") return `${spot.name}駅`;
  if (spot.kind === "land") {
    const place = spot.place && sameKana(spot.place) !== sameKana(muniName) ? spot.place : null;
    return place ?? (spot.station ? `${spot.station.name}駅` : null);
  }
  if (spot.school) return spot.school;
  const name = townName(spot.name);
  return name && sameKana(name) !== sameKana(muniName) ? name : null;
}

/** 地価の地点の説明（「本町2丁目、金沢駅から約250m」）。何もなければ空 */
export function spotWhere(spot: LandSpot): string {
  const station = spot.station
    ? spot.station.distance <= 100 ? `${spot.station.name}駅のすぐ近く` : `${spot.station.name}駅から約${spot.station.distance.toLocaleString("ja-JP")}m`
    : "";
  return [spot.place, station].filter(Boolean).join("、");
}

/**
 * 写真のタイルの拡大の段階と、並べるときの1枚の大きさ（CSS 画素）。縮尺はどれも PHOTO_MAP_ZOOM と同じ。
 * PNG の年代（1928〜1969年）は1枚 90KB ほどあるので、高精細でない画面（devicePixelRatio 1.5 未満）では
 * 1段下のタイルを大きく並べ、読む枚数を4分の1にする（その画面では細かいタイルでも見え方は変わらない）
 */
export function photoTileSize(era: Pick<PhotoEra, "ext">, pixelRatio = 2): { z: number; px: number } {
  return era.ext === "png" && pixelRatio < 1.5 ? { z: PHOTO_MAP_ZOOM + 1, px: 256 } : { z: PHOTO_MAP_ZOOM + 2, px: 128 };
}

export interface PhotoTile {
  url: string;
  /** 欄の中心からタイルの左上までの CSS 画素 */
  left: number;
  top: number;
  px: number;
}

/** 地点を中心に、幅・高さ（CSS 画素）の範囲を覆うタイル */
export function photoTiles(era: Pick<PhotoEra, "ext" | "tiles">, lng: number, lat: number, pixelRatio = 2,
  width: number = PHOTO_BOX.width, height: number = PHOTO_BOX.height): PhotoTile[] {
  const { z, px } = photoTileSize(era, pixelRatio);
  const n = 2 ** z;
  const cx = ((lng + 180) / 360) * n;
  const r = (lat * Math.PI) / 180;
  const cy = ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * n;
  const hw = width / 2 / px;
  const hh = height / 2 / px;
  const tiles: PhotoTile[] = [];
  for (let y = Math.max(0, Math.floor(cy - hh)); y < Math.min(n, Math.ceil(cy + hh)); y++) {
    for (let x = Math.floor(cx - hw); x < Math.ceil(cx + hw); x++) {
      tiles.push({
        url: era.tiles.replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y)),
        left: Math.round((x - cx) * px),
        top: Math.round((y - cy) * px),
        px,
      });
    }
  }
  return tiles;
}
