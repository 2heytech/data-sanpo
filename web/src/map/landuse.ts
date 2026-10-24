// 地図に重ねる土地利用図（国土数値情報「土地利用細分メッシュ」の100m四方のマスの区分、docs/design-changes.md #123）。
// 公開版の land_use/ に年度ごとのタイル（年度/ズーム/x/y.png。ズーム5は1024画素、ズーム7は2048画素）と、
// 年度・タイルの一覧・凡例の tiles.json がある。海だけの範囲のタイルはないので、一覧にないタイルは読みにいかない
// （読むと 404 になる）。タイルは画素がマスとほぼ同じ大きさなので、拡大してもぼかさない（nearest）。
// 年度のスライドバー・再生ボタン・凡例は地図の上のパネルに置く（航空写真の撮影年代と同じ形、#128）。
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
// 再生で次の年度へ送る間隔（タイルが大きいので、指標の再生より長めに見せる）
const PLAY_INTERVAL_MS = 2200;
// 地図の幅がこれ以下（スマホなど）のときは、重ねた点の凡例（地図の左下）を畳んだ状態で始める（app.ts）。
// 地図の画面の CSS（@container）でパネルを地図の上側に置く幅と同じ。土地利用の凡例はどの幅でも開いた状態で始める（#162）
export const NARROW_MAP_PX = 560;

interface Options {
  maplibregl: typeof MapLibre;
  map: MapLibreMap;
  /** 公開版のデータの場所（land_use/… の前） */
  base: string;
  fetchJSON: <T>(rel: string) => Promise<T>;
  /** 地図の上のパネル（表示しているときだけ出す） */
  panel: HTMLElement;
  /** 年度のスライドバーと、その上の年度の表示・下の年度の目盛り・再生ボタン */
  range: HTMLInputElement;
  label: HTMLOutputElement;
  ticks: HTMLElement;
  play: HTMLButtonElement;
  /** 凡例と、その開閉のボタン */
  legend: HTMLElement;
  legendToggle: HTMLButtonElement;
  /** パネルの下の一言（縮小しすぎて見えないときなど） */
  note: HTMLElement;
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
  let timer: number | undefined;

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
    o.play.disabled = years.length < 2;
    o.legend.innerHTML = index.legend.map((c) =>
      `<span><span class="sw sq" style="background:${esc(c.color)}"></span>${esc(c.name)}</span>`).join("");
    o.range.addEventListener("input", () => {
      stopPlay();
      setYear(Number(o.range.value));
    });
    // 目盛りの年度を押してもその年度にする（時点の目盛りと同じ）
    o.ticks.addEventListener("click", (e) => {
      const t = (e.target as HTMLElement).closest<HTMLElement>("span[data-i]");
      if (!t) return;
      stopPlay();
      setYear(Number(t.dataset.i));
    });
    // 再生: 古い年度から順に送り、最新まで来たら止める。途中で止めたときは次の再生をその年度から続ける（航空写真と同じ、#99）
    o.play.addEventListener("click", () => {
      if (timer !== undefined) return stopPlay();
      o.play.setAttribute("aria-pressed", "true");
      o.play.textContent = "■";
      if (at === years.length - 1) setYear(0);
      timer = window.setInterval(() => {
        if (at >= years.length - 1) return stopPlay();
        setYear(at + 1);
      }, PLAY_INTERVAL_MS);
    });
    return true;
  }

  const tileUrl = () => `${PROTOCOL}://${index!.years[at].year}/{z}/{x}/{y}`;

  function setYear(i: number) {
    if (!index || i === at) return sync();
    at = i;
    for (const l of LAYERS) (o.map.getSource(l.id) as RasterTileSource).setTiles([tileUrl()]);
    sync();
  }

  function stopPlay() {
    clearInterval(timer);
    timer = undefined;
    o.play.setAttribute("aria-pressed", "false");
    o.play.textContent = "▶";
  }

  function sync() {
    o.panel.hidden = !visible;
    if (!visible) return;
    o.range.hidden = o.play.hidden = o.ticks.hidden = o.legendToggle.hidden = !index;
    o.legend.hidden = !index || o.legendToggle.getAttribute("aria-expanded") !== "true";
    if (!index) {
      o.label.value = "土地利用";
      o.note.hidden = false;
      o.note.textContent = "この公開版には土地利用図がありません。";
      return;
    }
    const years = index.years;
    o.label.value = `${years[at].label}の土地利用`;
    o.range.value = String(at);
    o.ticks.innerHTML = years.length < 2 ? "" : years.map((y, i) =>
      `<span data-i="${i}"${i === at ? ' aria-current="true"' : ""}>${esc(y.label)}</span>`).join("");
    const zoomIn = o.map.getZoom() < LAND_USE_MINZOOM;
    o.note.hidden = !zoomIn;
    o.note.textContent = zoomIn ? "拡大すると表示されます。" : "";
  }

  o.legendToggle.addEventListener("click", () => {
    o.legendToggle.setAttribute("aria-expanded", String(o.legendToggle.getAttribute("aria-expanded") !== "true"));
    sync();
  });

  async function setVisible(on: boolean): Promise<boolean> {
    if (!on) stopPlay();
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
