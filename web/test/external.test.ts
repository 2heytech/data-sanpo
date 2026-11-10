import { describe, expect, it } from "vitest";
import { googleMapsUrl, streetViewUrl } from "../src/map/external";

const tokyo = { lat: 35.6812362, lng: 139.7671248, zoom: 15.4 };

describe("Google マップのリンク", () => {
  it("地図の中心と、Google の縮尺（MapLibre の縮尺 + 1 を丸めたもの）で開く", () => {
    const u = new URL(googleMapsUrl(tokyo));
    expect(u.origin + u.pathname).toBe("https://www.google.com/maps/@");
    expect(Object.fromEntries(u.searchParams)).toEqual({
      api: "1", map_action: "map", center: "35.681236,139.767125", zoom: "16",
    });
  });
  it("縮尺は Google が受け付ける 0〜21 に収める", () => {
    expect(new URL(googleMapsUrl({ ...tokyo, zoom: 21.7 })).searchParams.get("zoom")).toBe("21");
    expect(new URL(googleMapsUrl({ ...tokyo, zoom: -1.6 })).searchParams.get("zoom")).toBe("0");
  });
  it("背景が航空写真なら航空写真、標高・傾斜なら地形で開く（地図・土地利用はふつうの地図）", () => {
    const basemap = (b: Parameters<typeof googleMapsUrl>[1]) => new URL(googleMapsUrl(tokyo, b)).searchParams.get("basemap");
    expect(basemap("photo")).toBe("satellite");
    expect(basemap("relief")).toBe("terrain");
    expect(basemap("slope")).toBe("terrain");
    expect(basemap("pale")).toBeNull();
    expect(basemap("landuse")).toBeNull();
  });
});

describe("ストリートビューのリンク", () => {
  it("地図の中心にいちばん近い写真を開く", () => {
    const u = new URL(streetViewUrl(tokyo));
    expect(Object.fromEntries(u.searchParams)).toEqual({ api: "1", map_action: "pano", viewpoint: "35.681236,139.767125" });
  });
});
