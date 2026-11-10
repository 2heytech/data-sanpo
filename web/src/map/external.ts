// 見ている場所を Google マップ・ストリートビューで開くリンク（設計変更記録 #187）。地図の右下、ズームのボタンの下（狭い地図では左）の2つのアイコン。
// 開くのは地図の中心の地点。アイコンにマウスを載せる（キーボードで選ぶ）と、中心に十字の印を出してどこが開くかを示す。
// リンクは Google の Maps URLs（https://developers.google.com/maps/documentation/urls/get-started）で作り、別のタブで開く。
// 緯度・経度は押したときに Google へ渡るだけで、このサイトからは送らない。
import type { IControl, Map as MapLibreMap } from "maplibre-gl";

/** 地図の中心と縮尺（MapLibre の縮尺） */
export interface MapView {
  lat: number;
  lng: number;
  zoom: number;
}

/** 背景の種類（app.ts の baseMode） */
export type BaseMode = "pale" | "photo" | "relief" | "slope" | "landuse";

// 緯度・経度は小数第6位（約10cm）まで
const coord = (v: MapView) => `${v.lat.toFixed(6)},${v.lng.toFixed(6)}`;

/**
 * Google マップのリンク。縮尺は、MapLibre（512px のタイル）の縮尺 + 1 が Google（256px のタイル）の縮尺に当たる。
 * Google は整数の 0〜21 だけを受け付ける。背景が航空写真なら航空写真、標高・傾斜なら地形で開く。
 */
export function googleMapsUrl(v: MapView, base: BaseMode = "pale"): string {
  const p = new URLSearchParams({
    api: "1", map_action: "map", center: coord(v),
    zoom: String(Math.min(21, Math.max(0, Math.round(v.zoom + 1)))),
  });
  if (base === "photo") p.set("basemap", "satellite");
  else if (base === "relief" || base === "slope") p.set("basemap", "terrain");
  return `https://www.google.com/maps/@?${p}`;
}

/** ストリートビューのリンク。地点のいちばん近くで撮られた写真が開く */
export function streetViewUrl(v: MapView): string {
  const p = new URLSearchParams({ api: "1", map_action: "pano", viewpoint: coord(v) });
  return `https://www.google.com/maps/@?${p}`;
}

const ICON_MAP =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21.5s-6.5-6-6.5-11.5a6.5 6.5 0 0 1 13 0c0 5.5-6.5 11.5-6.5 11.5z"/><circle cx="12" cy="10" r="2.4"/></svg>';
const ICON_STREET =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="4.6" r="2.4"/><path d="M9.5 9h5a2 2 0 0 1 2 2v4.5h-2V21h-5v-5.5h-2V11a2 2 0 0 1 2-2zM12 16v5"/></svg>';

interface ExternalOptions {
  map: MapLibreMap;
  /** いまの背景（Google マップを航空写真・地形で開くため） */
  base: () => BaseMode;
}

export function initExternalMaps(o: ExternalOptions): void {
  const mark = document.createElement("div");
  mark.className = "center-mark";
  mark.hidden = true;
  o.map.getContainer().append(mark);

  let mapLink: HTMLAnchorElement;
  let streetLink: HTMLAnchorElement;
  const update = () => {
    const c = o.map.getCenter();
    const v = { lat: c.lat, lng: c.lng, zoom: o.map.getZoom() };
    mapLink.href = googleMapsUrl(v, o.base());
    streetLink.href = streetViewUrl(v);
  };

  const control: IControl = {
    onAdd() {
      const div = document.createElement("div");
      div.className = "maplibregl-ctrl maplibregl-ctrl-group external-ctrl";
      div.innerHTML =
        `<a target="_blank" rel="noopener" title="地図の中心を Google マップで開く（別のタブ）" aria-label="地図の中心を Google マップで開く（別のタブ）">${ICON_MAP}</a>` +
        `<a target="_blank" rel="noopener" title="地図の中心のストリートビューを開く（別のタブ）" aria-label="地図の中心のストリートビューを開く（別のタブ）">${ICON_STREET}</a>`;
      [mapLink, streetLink] = [...div.querySelectorAll("a")];
      update();
      // 地図を動かしたら、リンクの地点を中心に合わせる。背景を変えたあとや地図が動いている途中もあるので、
      // マウスを載せたとき・押し始めたとき（中ボタンや長押しで開くときも）・キーボードで選んだときにも合わせ直す
      o.map.on("moveend", update);
      for (const type of ["pointerenter", "pointerdown", "focusin", "click"]) div.addEventListener(type, update, true);
      // 中心の印は、アイコンにマウスを載せている間と、キーボードで選んでいる間だけ出す
      // （押したときのフォーカスでは出さない。別のタブから戻ったときに印が残らないように）
      let hover = false;
      let keyFocus = false;
      const sync = () => { mark.hidden = !(hover || keyFocus); };
      div.addEventListener("pointerenter", (e) => { hover = e.pointerType === "mouse"; sync(); });
      div.addEventListener("pointerleave", () => { hover = false; sync(); });
      div.addEventListener("focusin", (e) => { keyFocus = (e.target as Element).matches(":focus-visible"); sync(); });
      div.addEventListener("focusout", () => { keyFocus = false; sync(); });
      return div;
    },
    onRemove() {},
  };
  o.map.addControl(control, "bottom-right");
  // 右下の操作は後から足したものが上に積まれるので、ズームのボタンのすぐ後ろへ移す。広い地図ではズームの下に縦に並び、
  // 狭い地図（スマホ）ではズームの左に並ぶ（CSS）。上に積むと、スマホで上から開く土地利用のパネルに隠れるため
  const zoom = o.map.getContainer().querySelector(".maplibregl-ctrl-bottom-right .maplibregl-ctrl-zoom-in")?.parentElement;
  const div = zoom?.parentElement?.querySelector(".external-ctrl");
  if (zoom && div) zoom.after(div);
}
