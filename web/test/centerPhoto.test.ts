import { describe, expect, it } from "vitest";
import {
  centerSpots, landSpots, LATEST_PHOTO_ERA, OLD_PHOTO_ERAS, PHOTO_BOX, PHOTO_MAP_ZOOM, photoTiles, photoTileSize, placeName,
  spotArea, spotWhere, stationSpots, townSpot, type LandSource, type StationSource, type TownSource,
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
    expect(placeName("福島県 大沼郡会津美里町字瀬戸町甲３０７３番", "会津美里町")).toBe("瀬戸町");
  });
  it("市区町村名が見つからない・町名がないときは null", () => {
    expect(placeName("石川県 金沢市本町２丁目５７１番１外", "小松市")).toBeNull();
    expect(placeName("北海道 歌志内市１０２７番１０", "歌志内市")).toBeNull();
    expect(placeName(null, "金沢市")).toBeNull();
  });
});

describe("地価がいちばん高い地点（駅のない市区町村の中心部）", () => {
  it("商業地のうち最新の時点の価格がいちばん高い地点（住宅地のほうが高くても商業地）", () => {
    const spots = landSpots([{ survey: false, periods: KOUJI, points: [
      point({ coord: [1, 1], values: [null, 500] }),
      point({ coord: [2, 2], values: [9000, 800] }),
      point({ coord: [3, 3], use: "000", use_label: "住宅地", values: [null, 5000] }),
    ] }], NAMES);
    const s = spots.get("muni-17201")!;
    expect([s.lng, s.lat]).toEqual([2, 2]);
    expect(s).toMatchObject({ commercial: true, use: "商業地", survey: false, year: "2026年", place: "本町2丁目" });
  });
  it("商業地の地点がなければ用途を問わずいちばん高い地点。最新の時点に価格のない地点は使わない", () => {
    const spots = landSpots([{ survey: false, periods: KOUJI, points: [
      point({ coord: [1, 1], use: "000", use_label: "住宅地", values: [null, 300] }),
      point({ coord: [2, 2], use: "009", use_label: "工業地", values: [null, 400] }),
      point({ coord: [3, 3], values: [9000, null] }),
    ] }], NAMES);
    expect(spots.get("muni-17201")).toMatchObject({ kind: "land", lng: 2, commercial: false, use: "工業地" });
  });
  it("地価公示と都道府県地価調査を合わせて比べ、同じ価格なら先に渡した地価公示の地点にする", () => {
    const sources: LandSource[] = [
      { survey: false, periods: KOUJI, points: [point({ coord: [1, 1], values: [null, 700] })] },
      { survey: true, periods: CHOUSA, points: [point({ coord: [2, 2], values: [null, 700] }),
        point({ municipality_id: "muni-01400", coord: [3, 3], address: "北海道 虻田郡倶知安町南１条西１丁目４０番１外", values: [null, 100] })] },
    ];
    const spots = landSpots(sources, NAMES);
    expect(spots.get("muni-17201")).toMatchObject({ lng: 1, survey: false });
    expect(spots.get("muni-01400")).toMatchObject({ lng: 3, survey: true, year: "2025年", place: "南1条西1丁目" });
  });
  it("地点のない市区町村は入れない", () => {
    expect(landSpots([{ survey: false, periods: KOUJI, points: [] }], NAMES).size).toBe(0);
  });
});

describe("地価の地点の説明", () => {
  const base = { kind: "land", lng: 0, lat: 0, commercial: true, use: "商業地", survey: false, year: "2026年" } as const;
  it("町名と1km以内の駅", () => {
    expect(spotWhere({ ...base, place: "本町2丁目", station: { name: "金沢", distance: 250 } })).toBe("本町2丁目、金沢駅から約250m");
    expect(spotWhere({ ...base, place: "銀座4丁目", station: { name: "銀座", distance: 0 } })).toBe("銀座4丁目、銀座駅のすぐ近く");
    expect(spotWhere({ ...base, place: null, station: null })).toBe("");
  });
  it("バス停と1kmより遠い駅は書かない", () => {
    const stationOf = (p: Partial<Point>) =>
      landSpots([{ survey: false, periods: KOUJI, points: [point(p)] }], NAMES).get("muni-17201")!.station;
    expect(stationOf({ station: "倶知安", station_distance_m: 6500 })).toBeNull();
    expect(stationOf({ station: "バス停歌志内市街", station_distance_m: 280 })).toBeNull();
    expect(stationOf({ station: "地下鉄西２８丁目", station_distance_m: 650 })).toEqual({ name: "地下鉄西28丁目", distance: 650 });
  });
});

describe("中心部の駅", () => {
  type St = StationSource["stations"][number];
  const st = (over: Partial<St>): St => ({ name: "金沢", group: "g1", municipality_id: "muni-17201", coord: [136.648, 36.578], values: [100, 200, 300], ...over });
  const PERIODS = ["2022年度", "2023年度", "2024年度"];
  it("乗り換えのできる駅は事業者の値を同じ年度で合計し、いちばん多い駅にする。位置はいちばん多い事業者の駅", () => {
    const spots = stationSpots({ periods: PERIODS, stations: [
      st({ name: "金沢", group: "g1", coord: [1, 1], values: [null, null, 300] }),
      st({ name: "金沢", group: "g1", coord: [2, 2], values: [null, null, 250] }),
      st({ name: "野町", group: "g2", coord: [3, 3], values: [null, null, 500] }),
    ] });
    expect(spots.get("muni-17201")).toEqual({ kind: "station", lng: 1, lat: 1, name: "金沢", passengers: 550, year: "2024年度" });
  });
  it("最新の年度に値のない駅は、3年度前までの値を使う。それより古い値しかない駅は使わない", () => {
    const spots = stationSpots({ periods: ["2020年度", ...PERIODS], stations: [
      st({ name: "古い", group: "a", values: [9999, null, null, null] }),
      st({ name: "美瑛", group: "b", values: [null, 692, null, null] }),
    ] });
    expect(spots.get("muni-17201")).toMatchObject({ name: "美瑛", passengers: 692, year: "2022年度" });
  });
  it("乗降客数が 0 の駅しかない市区町村は入れない（地価の地点にする）", () => {
    expect(stationSpots({ periods: PERIODS, stations: [st({ values: [null, null, 0] })] }).size).toBe(0);
  });
  it("空港の駅は選ばない", () => {
    const spots = stationSpots({ periods: PERIODS, stations: [
      st({ name: "那覇空港", group: "a", values: [null, null, 15896] }),
      st({ name: "県庁前", group: "b", values: [null, null, 9000] }),
    ] });
    expect(spots.get("muni-17201")).toMatchObject({ name: "県庁前" });
  });
  it("駅があれば駅、乗降客数の分かる駅がなければ地価の地点。どちらもない市区町村は入れない", () => {
    const spots = centerSpots({ periods: PERIODS, stations: [st({ values: [null, null, 300] }), st({ municipality_id: "muni-01400", values: [null, null, null] })] },
      [{ survey: false, periods: KOUJI, points: [point({}), point({ municipality_id: "muni-01400", address: "北海道 虻田郡倶知安町南１条西１丁目４０番１外" })] }],
      new Map([...NAMES, ["muni-13382", "御蔵島村"]]));
    expect(spots.get("muni-17201")).toMatchObject({ kind: "station", name: "金沢" });
    expect(spots.get("muni-01400")).toMatchObject({ kind: "land", place: "南1条西1丁目" });
    expect(spots.has("muni-13382")).toBe(false);
  });
});

describe("人口がいちばん多い町丁目（駅も地価の地点もない市区町村の中心部）", () => {
  const CENSUS = (year: number, rows: [string, number | null][]) => ({
    label: `${year}年10月1日現在`, rows: rows.map(([entity_id, value]) => ({ entity_id, value })) });
  const futaba: TownSource = {
    muniName: "双葉町",
    areas: [
      { id: "area-075460010", name: "大字新山", center: [141.01078, 37.44391] },
      { id: "area-075460100", name: "大字長塚", center: [141.01012, 37.45541] },
    ],
    censuses: [
      CENSUS(2020, [["area-075460010", 0], ["area-075460100", 0]]),
      CENSUS(2015, [["area-075460010", 0], ["area-075460100", 0]]),
      CENSUS(2010, [["area-075460010", 1513], ["area-075460100", 1965]]),
    ],
    schools: [{ id: "school-1", name: "双葉北小学校", school_type: "elementary", coord: [141.0, 37.45] }],
  };
  it("新しい国勢調査から順に、人口のいる町丁目がある最初の年でいちばん多い町丁目。代表点を中心にする", () => {
    expect(townSpot(futaba)).toEqual({ kind: "town", lng: 141.01012, lat: 37.45541, name: "大字長塚", population: 1965, year: "2010年",
      skipped: ["2015年", "2020年"], school: null });
    const latest = { ...futaba, censuses: [CENSUS(2020, [["area-075460010", 10], ["area-075460100", 3]]), ...futaba.censuses.slice(1)] };
    expect(townSpot(latest)).toMatchObject({ name: "大字新山", population: 10, year: "2020年", skipped: [] });
  });
  it("同じ人口なら町丁目のコードの小さい方。人口のいる町丁目がどの年にもなければ null", () => {
    const tie = { ...futaba, censuses: [CENSUS(2020, [["area-075460100", 5], ["area-075460010", 5]])] };
    expect(townSpot(tie)).toMatchObject({ name: "大字新山" });
    expect(townSpot({ ...futaba, censuses: futaba.censuses.slice(0, 2) })).toBeNull();
  });
  it("町丁目の名前が市区町村の名前と同じ（島の村など）なら、閉じていない学校（小学校を先に）の位置にする", () => {
    const toshima: TownSource = {
      muniName: "利島村",
      areas: [{ id: "area-133620010", name: "利島村", center: [139.27979, 34.52246] }],
      censuses: [CENSUS(2020, [["area-133620010", 327]])],
      schools: [
        { id: "school-372010", name: "利島中学校", school_type: "junior_high", coord: [139.278, 34.53] },
        { id: "school-000001", name: "閉じた小学校", school_type: "elementary", coord: [139.27, 34.52], closed: true },
        { id: "school-272010", name: "利島小学校", school_type: "elementary", coord: [139.27801, 34.52999] },
      ],
    };
    expect(townSpot(toshima)).toMatchObject({ lng: 139.27801, lat: 34.52999, name: "利島村", population: 327, school: "利島小学校" });
    // 「青ヶ島村」と「青ケ島村」のような書き方の違いは同じとみなす。位置の分かる学校がなければ町丁目の代表点のまま
    const aogashima: TownSource = {
      muniName: "青ヶ島村",
      areas: [{ id: "area-134020010", name: "青ケ島村", center: [139.76742, 32.45822] }],
      censuses: [CENSUS(2020, [["area-134020010", 169]])],
      schools: [{ id: "school-278010", name: "青ヶ島小学校", school_type: "elementary", coord: null }],
    };
    expect(townSpot(aogashima)).toMatchObject({ lng: 139.76742, lat: 32.45822, school: null });
  });
  it("駅も地価の地点もない市区町村だけ町丁目で選ぶ（町丁目は必要な市区町村の分だけ読む）", () => {
    const asked: string[] = [];
    const spots = centerSpots({ periods: ["2024年度"], stations: [] },
      [{ survey: false, periods: KOUJI, points: [point({})] }],
      new Map([["muni-17201", "金沢市"], ["muni-07546", "双葉町"], ["muni-13382", "御蔵島村"]]),
      (id) => { asked.push(id); return id === "muni-07546" ? futaba : null; });
    expect(asked).toEqual(["muni-07546", "muni-13382"]);
    expect(spots.get("muni-17201")).toMatchObject({ kind: "land" });
    expect(spots.get("muni-07546")).toMatchObject({ kind: "town", name: "大字長塚" });
    expect(spots.has("muni-13382")).toBe(false);
  });
});

describe("写真の見出しに添える場所", () => {
  const land = landSpots([{ survey: false, periods: KOUJI, points: [point({})] }], NAMES).get("muni-17201")!;
  it("駅は「〇〇駅」、地価の地点は町名、町丁目は大字・字を外した名前、島の村は学校の名前", () => {
    expect(spotArea({ kind: "station", lng: 0, lat: 0, name: "金沢", passengers: 1, year: "2024年度" }, "金沢市")).toBe("金沢駅");
    expect(spotArea(land, "金沢市")).toBe("本町2丁目");
    const town = { kind: "town" as const, lng: 0, lat: 0, name: "大字長塚", population: 1965, year: "2010年", skipped: [], school: null };
    expect(spotArea(town, "双葉町")).toBe("長塚");
    expect(spotArea({ ...town, name: "利島村", school: "利島小学校" }, "利島村")).toBe("利島小学校");
  });
  it("町名が読み取れない・市区町村の名前と同じなら最寄りの駅。それもなければ添えない", () => {
    expect(spotArea({ ...land, place: null }, "金沢市")).toBe("金沢駅");
    expect(spotArea({ ...land, place: "蘭越町", station: { name: "蘭越", distance: 300 } }, "蘭越町")).toBe("蘭越駅");
    expect(spotArea({ ...land, place: null, station: null }, "平谷村")).toBeNull();
    const town = { kind: "town" as const, lng: 0, lat: 0, name: "青ケ島村", population: 169, year: "2020年", skipped: [], school: null };
    expect(spotArea(town, "青ヶ島村")).toBeNull();
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
