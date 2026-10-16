// 地図に重ねる土地利用図（国土数値情報「土地利用細分メッシュ」の100m四方のマスの区分、docs/design-changes.md #123）。
// 公開版の land_use/ に年度ごとのタイル（年度/ズーム/x/y.png。ズーム5は1024画素、ズーム7は2048画素）と、
// 年度・タイルの一覧・凡例の tiles.json がある。海だけの範囲のタイルはないので、一覧にないタイルは読みにいかない
// （読むと 404 になる）。タイルは画素がマスとほぼ同じ大きさなので、拡大してもぼかさない（nearest）。
import type * as MapLibre from "maplibre-gl";
import type { Map as MapLibreMap, RasterTileSource } from "maplibre-gl";
import { esc } from "../lib/html";
import type { Source } from "../lib/types";

export interface LandUseIndex {
  years: { year: number; label: string; tiles: Record<string, string[]> }[];
  zooms: Record<string, number>;
  legend: { id: number; name: string; color: string }[];
  source_ids?: string[];
}

const PROTOCOL = "landuse";
/** これより縮小しているときは出さない（ズーム5のタイルから） */
export const LAND_USE_MINZOOM = 5;
// ズーム5のタイルは縮尺7まで、ズーム7のタイルはそれより拡大したときに使う
const LAYERS = [
  { id: "landuse-z5", zoom: 5, minzoom: LAND_USE_MINZOOM, maxzoom: 7 },
  { id: "landuse-z7", zoom: 7, minzoom: 7, maxzoom: 24 },
];

interface Options {
  maplibregl: typeof MapLibre;
  map: MapLibreMap;
  /** 公開版のデータの場所（land_use/… の前） */
  base: string;
  fetchJSON: <T>(rel: string) => Promise<T>;
  /** 年度のスライドバーと、その上の年度の表示・両端の年度 */
  range: HTMLInputElement;
  label: HTMLOutputElement;
  ends: HTMLElement;
  /** スライドバーなどを囲む要素（表示しているときだけ出す） */
  controls: HTMLElement;
  /** 凡例・説明 */
  legend: HTMLElement;
  /** 出典（地図の右下の表示に使う） */
  source: Source | undefined;
  /** この層より下（境界の塗り・線より下）に入れる */
  beforeLayer: () => string | undefined;
}

export interface LandUseLayer {
  /** 表示する・消す。データがない公開版では false を返す */
  setVisible(on: boolean): Promise<boolean>;
  /** 縮尺が変わったとき（縮小しすぎて見えないことを知らせる） */
  sync(): void;
}

export function initLandUse(o: Options): LandUseLayer {
  let index: LandUseIndex | null = null;
  let available = new Set<string>();
  let at = 0;   // index.years の番号
  let visible = false;
  let blank: Promise<ImageBitmap> | null = null;

  async function load(): Promise<boolean> {
    if (index) return true;
    try {
      index = await o.fetchJSON<LandUseIndex>("land_use/tiles.json");
    } catch {
      return false;
    }
    available = new Set(index.years.flatMap((y) =>
      Object.entries(y.tiles).flatMap(([z, ts]) => ts.map((t) => `${y.year}/${z}/${t}`))));
    at = index.years.length - 1;
    // 一覧にないタイル（海だけの範囲）は、読まずに透明な画像にする
    o.maplibregl.addProtocol(PROTOCOL, async (params, abort) => {
      const key = params.url.slice(PROTOCOL.length + 3);
      if (!available.has(key)) {
        blank ??= createImageBitmap(new ImageData(1, 1));
        return { data: await blank };
      }
      const r = await fetch(`${o.base}/land_use/${key}.png`, { signal: abort.signal });
      if (!r.ok) throw new Error(`land_use/${key}.png: ${r.status}`);
      return { data: await r.arrayBuffer() };
    });
    const s = o.source;
    const attribution = s?.url
      ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">国土数値情報（土地利用細分メッシュ）</a>を加工`
      : "国土数値情報（土地利用細分メッシュ）を加工";
    for (const l of LAYERS) {
      o.map.addSource(l.id, {
        type: "raster", tiles: [tileUrl()], tileSize: 512, minzoom: l.zoom, maxzoom: l.zoom, attribution,
      });
      o.map.addLayer({
        id: l.id, type: "raster", source: l.id, minzoom: l.minzoom, maxzoom: l.maxzoom,
        layout: { visibility: "none" },
        paint: { "raster-opacity": 0.85, "raster-resampling": "nearest", "raster-fade-duration": 0 },
      }, o.beforeLayer());
    }
    const years = index.years;
    o.range.max = String(years.length - 1);
    o.range.value = String(at);
    o.range.disabled = years.length < 2;
    o.ends.innerHTML = years.length < 2 ? ""
      : `<span>${esc(years[0].label)}</span><span>${esc(years[years.length - 1].label)}</span>`;
    o.range.addEventListener("input", () => {
      at = Number(o.range.value);
      for (const l of LAYERS) (o.map.getSource(l.id) as RasterTileSource).setTiles([tileUrl()]);
      sync();
    });
    return true;
  }

  const tileUrl = () => `${PROTOCOL}://${index!.years[at].year}/{z}/{x}/{y}`;

  function sync() {
    o.controls.hidden = !visible || !index;
    o.legend.hidden = !visible;
    if (!visible) return;
    if (!index) {
      o.legend.textContent = "この公開版には土地利用図がありません。";
      return;
    }
    const y = index.years[at];
    o.label.value = `${y.label}の土地利用`;
    const zoomIn = o.map.getZoom() < LAND_USE_MINZOOM;
    o.legend.innerHTML = (zoomIn ? "拡大すると表示されます。" : "") +
      "100m四方のマスごとに、その中で最も広い土地利用の色で塗っています。年度によって判読の方法が違います。" +
      `<span class="land-bins">${index.legend.map((c) =>
        `<span><span class="sw sq" style="background:${esc(c.color)}"></span>${esc(c.name)}</span>`).join("")}</span>`;
  }

  async function setVisible(on: boolean): Promise<boolean> {
    const ok = !on || (await load());
    visible = on;
    for (const l of LAYERS) {
      if (o.map.getLayer(l.id)) o.map.setLayoutProperty(l.id, "visibility", on && ok ? "visible" : "none");
    }
    sync();
    return ok;
  }

  return { setVisible, sync };
}
