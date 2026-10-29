// 共有URLに保存する状態。現在地や自宅の座標は含めない（設計書 第3章「共有」）。
// 地図の位置と縮尺は、共有の画面で「地図の位置と縮尺も入れる」を選んだときのリンクにだけ入れる（アドレス欄には入れない。#175）

export interface MapView {
  zoom: number;
  lat: number;
  lng: number;
  bearing?: number;
  pitch?: number;
}

export interface MapState {
  indicator?: string;
  period?: string;
  area?: string;
  /** 色分けの単位を手で選んだとき（prefecture・municipality・small_area）。ないときは縮尺に合わせて切り替える（#146） */
  level?: string;
  /** 背景。航空写真は撮影年代の ID（photo は最新、photo1945 など）、標高は relief、土地利用は年度つき（landuse2021）。地図のときはなし */
  base?: string;
  /** 既定ではオフのものでオンにしているもの（駅などの重ねる点、背景が写真などのときの色分け）。?show= */
  show?: string[];
  /** 既定ではオンのものでオフにしているもの（色分け・地名・数値）。?hide= */
  hide?: string[];
  /** 選んでいる地点（?s=<駅ID> など）と天気の指標（?wx=） */
  points?: Record<string, string>;
  /** 地図の位置と縮尺（共有の画面のリンクだけ） */
  view?: MapView;
}

const KEYS = { indicator: "i", period: "p", area: "a", level: "l", base: "b" } as const;
const LIST_KEYS = { show: "show", hide: "hide" } as const;
/** 点レイヤーの地点の引数（駅・学校・地価公示・地価調査・保育所・道の駅・文化財・空港・港・天気の観測所）と天気の指標 */
export const POINT_KEYS = ["s", "sc", "lp", "ls", "nu", "me", "cp", "ap", "pt", "ws", "wx"] as const;
const SAFE = /^[A-Za-z0-9_.-]{1,64}$/;
const VIEW = /^(\d{1,2}(?:\.\d+)?)\/(-?\d{1,2}(?:\.\d+)?)\/(-?\d{1,3}(?:\.\d+)?)(?:\/(-?\d{1,3}(?:\.\d+)?)(?:\/(\d{1,2}(?:\.\d+)?))?)?$/;

export function parseState(search: string): MapState {
  const params = new URLSearchParams(search);
  const state: MapState = {};
  for (const [field, key] of Object.entries(KEYS) as [keyof typeof KEYS, string][]) {
    const v = params.get(key);
    if (v && SAFE.test(v)) state[field] = v;
  }
  for (const [field, key] of Object.entries(LIST_KEYS) as [keyof typeof LIST_KEYS, string][]) {
    const items = (params.get(key) ?? "").split(",").filter((v) => SAFE.test(v));
    if (items.length) state[field] = items;
  }
  const points = Object.fromEntries(POINT_KEYS.map((k) => [k, params.get(k)]).filter(([, v]) => v && SAFE.test(v)));
  if (Object.keys(points).length) state.points = points as Record<string, string>;
  const view = parseView(params.get("m"));
  if (view) state.view = view;
  return state;
}

function parseView(v: string | null): MapView | undefined {
  const m = v ? VIEW.exec(v) : null;
  if (!m) return undefined;
  const [zoom, lat, lng, bearing, pitch] = m.slice(1).map((x) => (x === undefined ? undefined : Number(x)));
  if (zoom! > 22 || Math.abs(lat!) > 85 || Math.abs(lng!) > 180) return undefined;
  const view: MapView = { zoom: zoom!, lat: lat!, lng: lng! };
  if (bearing !== undefined && Math.abs(bearing) <= 180) view.bearing = bearing;
  if (pitch !== undefined && pitch <= 85) view.pitch = pitch;
  return view;
}

/** 位置の桁: 地図の1画素ほど（縮尺が大きいほど細かく）。縮尺は小数2桁 */
export function formatView(v: MapView): string {
  const digits = Math.min(6, Math.max(1, Math.ceil(Math.log10((256 * 2 ** v.zoom) / 360))));
  const num = (x: number, d: number) => String(Number(x.toFixed(d)));
  const parts = [num(v.zoom, 2), num(v.lat, digits), num(v.lng, digits)];
  const bearing = Math.round(v.bearing ?? 0);
  const pitch = Math.round(v.pitch ?? 0);
  if (bearing || pitch) parts.push(String(bearing));
  if (pitch) parts.push(String(pitch));
  return parts.join("/");
}

// 値は SAFE の文字だけなので、そのまま並べる（「,」「/」を %2C・%2F にしない）
export function serializeState(state: MapState): string {
  const parts: string[] = [];
  for (const [field, key] of Object.entries(KEYS) as [keyof typeof KEYS, string][]) {
    const v = state[field];
    if (v && SAFE.test(v)) parts.push(`${key}=${v}`);
  }
  for (const [field, key] of Object.entries(LIST_KEYS) as [keyof typeof LIST_KEYS, string][]) {
    const items = [...new Set(state[field] ?? [])].filter((v) => SAFE.test(v));
    if (items.length) parts.push(`${key}=${items.join(",")}`);
  }
  for (const k of POINT_KEYS) {
    const v = state.points?.[k];
    if (v && SAFE.test(v)) parts.push(`${k}=${v}`);
  }
  if (state.view) parts.push(`m=${formatView(state.view)}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

/** 地図の画面へのリンク（例: 寄り道から、全国の市区町村別の色分けで開く） */
export function mapHref(state: MapState): string {
  return `/map/${serializeState(state)}`;
}

export function municipalityCodeOf(entityId: string): string | null {
  const m = /^(?:muni|area)-(\d{5})/.exec(entityId);
  return m ? m[1] : null;
}

/** 地域IDの都道府県コード2桁（町丁・字等の値は都道府県ごとのファイルにある） */
export function prefectureCodeOf(entityId: string): string | null {
  return /^pref-(\d{2})$/.exec(entityId)?.[1] ?? municipalityCodeOf(entityId)?.slice(0, 2) ?? null;
}
