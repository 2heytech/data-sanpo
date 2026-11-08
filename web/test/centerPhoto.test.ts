import { describe, expect, it } from "vitest";
import {
  centerSpots, LATEST_PHOTO_ERA, OLD_PHOTO_ERAS, PHOTO_BOX, PHOTO_MAP_ZOOM, photoTiles, photoTileSize, placeName, spotWhere,
  type LandSource,
} from "../src/lib/centerPhoto";
import { PHOTO_ERAS } from "../src/map/photoEras";

type Point = LandSource["points"][number];
const point = (over: Partial<Point>): Point => ({
  municipality_id: "muni-17201", coord: [136.65, 36.577], use: "005", use_label: "商業地",
  address: "石川県 金沢市本町２丁目５７１番１外", station: "金沢", station_distance_m: 250, values: [1000, 2000], ...over,
});
const NAMES = new Map([["muni-17201", "金沢市"], ["muni-01400", "倶知安町"]]);
const KOUJI = ["2025年1月1日現在", "2026年1月1日現在"];
const CHOUSA = ["2024年7月1日現在", "2025年7月1日現在"];

describe("地価の地点の所在地から町名を取り出す", () => {
  it("市区町村名の後ろから地番の前まで（数字は半角）", () => {
    expect(placeName("石川県 金沢市本町２丁目５７１番１外", "金沢市")).toBe("本町2丁目");
    expect(placeName("東京都 中央区銀座４丁目２番４", "中央区")).toBe("銀座4丁目");
    expect(placeName("北海道 虻田郡倶知安町南１条西１丁目４０番１外", "倶知安町")).toBe("南1条西1丁目");
    expect(placeName("東京都 渋谷区宇田川町７７番１４外", "渋谷区")).toBe("宇田川町");
    expect(placeName("神奈川県 茅ケ崎市元町２番１外", "茅ヶ崎市")).toBe("元町");
  });
  it("大字・字は大字の名前だけにする", () => {
    expect(placeName("長野県 北安曇郡白馬村大字北城字新田３０２０番８３７外", "白馬村")).toBe("北城");
    expect(placeName("神奈川県 足柄下郡箱根町湯本字白石下７０６番１２外", "箱根町")).toBe("湯本");
    expect(placeName("北海道 虻田郡ニセコ町字本通８３番１", "ニセコ町")).toBe("本通");
  });
  it("市区町村名が見つからない・町名がないときは null", () => {
    expect(placeName("石川県 金沢市本町２丁目５７１番１外", "小松市")).toBeNull();
    expect(placeName("北海道 歌志内市１０２７番１０", "歌志内市")).toBeNull();
    expect(placeName(null, "金沢市")).toBeNull();
  });
});

describe("中心部の地点", () => {
  it("商業地のうち最新の時点の価格がいちばん高い地点（住宅地のほうが高くても商業地）", () => {
    const spots = centerSpots([{ survey: false, periods: KOUJI, points: [
      point({ coord: [1, 1], values: [null, 500] }),
      point({ coord: [2, 2], values: [9000, 800] }),
      point({ coord: [3, 3], use: "000", use_label: "住宅地", values: [null, 5000] }),
    ] }], NAMES);
    const s = spots.get("muni-17201")!;
    expect([s.lng, s.lat]).toEqual([2, 2]);
    expect(s).toMatchObject({ commercial: true, use: "商業地", survey: false, year: "2026年", place: "本町2丁目" });
  });
  it("商業地の地点がなければ用途を問わずいちばん高い地点。最新の時点に価格のない地点は使わない", () => {
    const spots = centerSpots([{ survey: false, periods: KOUJI, points: [
      point({ coord: [1, 1], use: "000", use_label: "住宅地", values: [null, 300] }),
      point({ coord: [2, 2], use: "009", use_label: "工業地", values: [null, 400] }),
      point({ coord: [3, 3], values: [9000, null] }),
    ] }], NAMES);
    expect(spots.get("muni-17201")).toMatchObject({ lng: 2, commercial: false, use: "工業地" });
  });
  it("地価公示と都道府県地価調査を合わせて比べ、同じ価格なら先に渡した地価公示の地点にする", () => {
    const sources: LandSource[] = [
      { survey: false, periods: KOUJI, points: [point({ coord: [1, 1], values: [null, 700] })] },
      { survey: true, periods: CHOUSA, points: [point({ coord: [2, 2], values: [null, 700] }),
        point({ municipality_id: "muni-01400", coord: [3, 3], address: "北海道 虻田郡倶知安町南１条西１丁目４０番１外", values: [null, 100] })] },
    ];
    const spots = centerSpots(sources, NAMES);
    expect(spots.get("muni-17201")).toMatchObject({ lng: 1, survey: false });
    expect(spots.get("muni-01400")).toMatchObject({ lng: 3, survey: true, year: "2025年", place: "南1条西1丁目" });
  });
  it("地点のない市区町村は入れない", () => {
    expect(centerSpots([{ survey: false, periods: KOUJI, points: [] }], NAMES).size).toBe(0);
  });
});

describe("中心部の地点の説明", () => {
  const base = { lng: 0, lat: 0, commercial: true, use: "商業地", survey: false, year: "2026年" };
  it("町名と1km以内の駅", () => {
    expect(spotWhere({ ...base, place: "本町2丁目", station: { name: "金沢", distance: 250 } })).toBe("本町2丁目、金沢駅から約250m");
    expect(spotWhere({ ...base, place: "銀座4丁目", station: { name: "銀座", distance: 0 } })).toBe("銀座4丁目、銀座駅のすぐ近く");
    expect(spotWhere({ ...base, place: null, station: null })).toBe("");
  });
  it("バス停と1kmより遠い駅は書かない", () => {
    const stationOf = (p: Partial<Point>) =>
      centerSpots([{ survey: false, periods: KOUJI, points: [point(p)] }], NAMES).get("muni-17201")!.station;
    expect(stationOf({ station: "倶知安", station_distance_m: 6500 })).toBeNull();
    expect(stationOf({ station: "バス停歌志内市街", station_distance_m: 280 })).toBeNull();
    expect(stationOf({ station: "地下鉄西２８丁目", station_distance_m: 650 })).toEqual({ name: "地下鉄西28丁目", distance: 650 });
  });
});

describe("写真のタイル", () => {
  it("どの年代も同じ縮尺（z16 のタイルを 128 画素 = 地図の縮尺 14）", () => {
    expect(PHOTO_MAP_ZOOM).toBe(14);
    for (const era of PHOTO_ERAS) {
      for (const ratio of [1, 2, 3]) {
        const { z, px } = photoTileSize(era, ratio);
        expect(px / 2 ** (16 - z)).toBe(128);
        expect(z).toBeLessThanOrEqual(era.maxzoom);
        expect(z).toBeGreaterThanOrEqual(era.minzoom);
      }
    }
  });
  it("PNG の年代は、高精細でない画面だけ1段下のタイルを大きく並べる（JPEG はいつも z16）", () => {
    const png = OLD_PHOTO_ERAS[3];
    expect(photoTileSize(png, 1)).toEqual({ z: 15, px: 256 });
    expect(photoTileSize(png, 2)).toEqual({ z: 16, px: 128 });
    expect(photoTileSize(LATEST_PHOTO_ERA, 1)).toEqual({ z: 16, px: 128 });
  });
  it("昔の写真の候補は1928〜1990年の年代（古い順）で、年度別空中写真と最新の写真を含まない", () => {
    expect(OLD_PHOTO_ERAS.map((e) => e.id)).toEqual(
      ["photo1928", "photo1936", "photo1945", "photo1961", "photo1974", "photo1979", "photo1984", "photo1987"]);
    expect(LATEST_PHOTO_ERA.path).toBe("seamlessphoto");
  });
  it("欄のいちばん大きいときを、隙間なく覆う", () => {
    for (const [era, ratio] of [[LATEST_PHOTO_ERA, 2], [OLD_PHOTO_ERAS[3], 1], [OLD_PHOTO_ERAS[3], 3]] as const) {
      for (const [lng, lat] of [[136.64998, 36.57713], [139.76522, 35.67182], [127.68, 26.21], [141.35, 43.06]]) {
        const tiles = photoTiles(era, lng, lat, ratio);
        const { px, z } = photoTileSize(era, ratio);
        const left = Math.min(...tiles.map((t) => t.left));
        const top = Math.min(...tiles.map((t) => t.top));
        const right = Math.max(...tiles.map((t) => t.left + px));
        const bottom = Math.max(...tiles.map((t) => t.top + px));
        expect(left).toBeLessThanOrEqual(-PHOTO_BOX.width / 2);
        expect(right).toBeGreaterThanOrEqual(PHOTO_BOX.width / 2);
        expect(top).toBeLessThanOrEqual(-PHOTO_BOX.height / 2);
        expect(bottom).toBeGreaterThanOrEqual(PHOTO_BOX.height / 2);
        // 並べたタイルの数は、覆う範囲の縦横の枚数の積（重なり・隙間がない）
        expect(tiles.length).toBe(((right - left) / px) * ((bottom - top) / px));
        expect(new Set(tiles.map((t) => t.url)).size).toBe(tiles.length);
        expect(tiles[0].url).toMatch(new RegExp(`/${era.path}/${z}/\\d+/\\d+\\.${era.ext}$`));
      }
    }
  });
  it("地点はタイルの中の正しい位置に来る（金沢市本町2丁目の z16）", () => {
    const tiles = photoTiles(LATEST_PHOTO_ERA, 136.64998, 36.57713);
    // 地点を含むタイルは left・top が -128〜0
    const own = tiles.find((t) => t.left <= 0 && t.left > -128 && t.top <= 0 && t.top > -128)!;
    const x = Math.floor(((136.64998 + 180) / 360) * 2 ** 16);
    expect(own.url).toContain(`/16/${x}/`);
  });
});
