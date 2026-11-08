// 地域ページの「中心部の昔と今」の航空写真（設計変更記録 #215）。ビルド時とブラウザの両方で使う（node の読み込みはしない）。
// 中心部は、その市区町村で地価がいちばん高い商業地の地点（地価公示・都道府県地価調査の最新の価格）。
// 商業地の地点がない市区町村は、ほかの用途も含めていちばん高い地点にする。地点がなければ欄を出さない。
// 写真は地理院タイルをそのまま並べる（サイトの静的ファイルは増やさない）。
import { PHOTO_ERAS, type PhotoEra } from "../map/photoEras";
import type { LandPoint } from "./types";

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

export interface CenterSpot {
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

export interface LandSource {
  points: Pick<LandPoint, "municipality_id" | "coord" | "use" | "use_label" | "address" | "station" | "station_distance_m" | "values">[];
  /** 価格の時点の名前（values と同じ順。「2026年1月1日現在」） */
  periods: string[];
  survey: boolean;
}

const toHalfWidth = (s: string) => s.replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0));

/**
 * 地価の地点の所在地から町名を取り出す（「石川県 金沢市本町２丁目５７１番１外」→「本町2丁目」）。
 * 市区町村名の後ろから、地番（「５７１番１」）より前。大字・字は大字の名前だけにする（「大字北城字新田」→「北城」）
 */
export function placeName(address: string | null | undefined, muniName: string): string | null {
  if (!address) return null;
  // 「茅ヶ崎市」と「茅ケ崎市」のような書き方の違いはそろえて探す（同じ文字数なので位置は変わらない）
  const same = (s: string) => s.replace(/ヶ/g, "ケ");
  const at = same(address).indexOf(same(muniName));
  if (at < 0) return null;
  let rest = address.slice(at + muniName.length).trim();
  rest = rest.replace(/[0-9０-９]+番.*$/, "").replace(/^(大字|字)/, "").replace(/^(.{2,}?)字.+$/, "$1");
  rest = toHalfWidth(rest).trim();
  return rest && !/[0-9]$/.test(rest) ? rest : null;
}

/** 最寄りの駅。バス停と、1km より遠い駅は出さない */
function nearStation(name: string | null | undefined, distance: number | null | undefined): CenterSpot["station"] {
  if (!name || distance == null || distance > 1000 || name.startsWith("バス停")) return null;
  return { name: toHalfWidth(name), distance };
}

const yearOf = (label: string | undefined) => /^(\d{4})年/.exec(label ?? "")?.[1];

/**
 * 市区町村ごとの中心部の地点。最新の時点に価格のある地点のうち、商業地でいちばん高い地点
 * （商業地がなければいちばん高い地点）。同じ価格なら先に渡した出典（地価公示）の地点にする
 */
export function centerSpots(sources: LandSource[], names: Map<string, string>): Map<string, CenterSpot> {
  const best = new Map<string, { key: [number, number]; spot: CenterSpot }>();
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
          lng: p.coord[0], lat: p.coord[1], commercial, use: p.use_label, survey: src.survey, year: `${year}年`,
          place: placeName(p.address, name), station: nearStation(p.station, p.station_distance_m),
        },
      });
    }
  }
  return new Map([...best].map(([id, b]) => [id, b.spot]));
}

/** 中心部の地点の説明（「本町2丁目、金沢駅から約250m」）。何もなければ空 */
export function spotWhere(spot: CenterSpot): string {
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
