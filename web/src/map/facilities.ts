// 値のない施設の点レイヤー（道の駅・国指定文化財）。点の大きさはそろえ、選ぶと所在地・登録や指定の時期などを出す。
// 道の駅は全国で約1,200か所と少ないので、places/michi_no_eki.json の1ファイルに全件をまとめ、全国を見ているときから表示する。
// 文化財は全国で約2万件あるので、地図に映っている都道府県のファイル（places/cultural_properties/<都道府県>.json）だけを読む。
// 2つの市区町村にまたがる道の駅は、点は1つで、情報には両方の市区町村を出す（docs/design-changes.md #149）。
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import { createPrefLoader, sourcesHtml, type PointLayer, type FocusPoint, pointUrlState } from "./points";
import { formatNumber } from "../lib/format";
import type { FacilityFile, FacilityPoint, Source } from "../lib/types";
import { esc } from "../lib/html";

export type FacilityKind = "michi" | "bunka";

interface KindConfig {
  file: string; show: string; param: string; label: string; color: string; text: string;
  /** 都道府県ごとのファイルに分けているか */
  split: boolean;
  /** 地名を出す縮尺 */
  labelZoom: number;
  /** 種類ごとの色（types の最初の種類で決める）。ないときは color */
  colors?: Record<string, string>;
}

const KINDS: Record<FacilityKind, KindConfig> = {
  michi: { file: "michi_no_eki", show: "michi", param: "me", label: "道の駅", color: "#d9480f", text: "#8a2c06", split: false, labelZoom: 9 },
  bunka: {
    file: "cultural_properties", show: "bunka", param: "cp", label: "文化財", color: "#8a5a2b", text: "#5a3a1a", split: true, labelZoom: 13,
    colors: {
      "重要文化財（建造物）": "#b02a1c", "登録有形文化財（建造物）": "#e08a2e", "史跡": "#7a5a2f",
      "名勝": "#1f8a7a", "天然記念物": "#4c9a2a", "重要伝統的建造物群保存地区": "#6a4c93",
    },
  },
};

const DB_URL = "https://kunishitei.bunka.go.jp/heritage/detail/";

interface Options {
  kind: FacilityKind;
  map: MapLibreMap;
  fetchJSON: <T>(rel: string) => Promise<T>;
  toggle: HTMLInputElement;
  legend: HTMLElement;
  panel: HTMLElement;
  sources: Map<string, Source>;
  municipalityName: (id: string) => string;
  beforeLayer: string;
  labelFont: string[];
  /** 地点の情報の表示が変わったとき（開いた・閉じた・別の地点にした） */
  onPanel: () => void;
  /** 共有URLの地点へ地図を動かす */
  focus: FocusPoint;
}

/** 地図・ポップアップに出す名前。道の駅の一覧の駅名には「道の駅」が付かないので付ける */
export function facilityName(kind: FacilityKind, name: string): string {
  return kind === "michi" && !name.startsWith("道の駅") ? `道の駅 ${name}` : name;
}

/** 所在地の市区町村の名前（2つ以上にまたがる施設は「・」でつなぐ）。分からなければ空 */
export function municipalityText(p: Pick<FacilityPoint, "municipality_id" | "municipality_ids">,
  nameOf: (id: string) => string): string {
  const ids = p.municipality_ids ?? (p.municipality_id ? [p.municipality_id] : []);
  return ids.map(nameOf).filter(Boolean).join("・");
}

/** 点の色（文化財は最初の種類の色） */
export function facilityColor(kind: FacilityKind, p: Pick<FacilityPoint, "types">): string {
  const k = KINDS[kind];
  return (p.types?.length && k.colors?.[p.types[0]]) || k.color;
}

export function initFacilities(o: Options): PointLayer {
  const k = KINDS[o.kind];
  const LAYER = `${o.kind}-circle`;
  const SELECTED = `${o.kind}-selected`;
  const LABEL = `${o.kind}-label`;
  const SOURCE = `${o.kind}-points`;
  let data: FacilityFile | null = null;
  let byId = new Map<string, FacilityPoint>();
  let total = 0;
  let located = 0;
  const loader = k.split ? createPrefLoader<FacilityPoint>({
    map: o.map, fetchJSON: o.fetchJSON, id: k.file, key: "points",
    active: () => o.toggle.checked,
    onChange: (items) => render(items),
  }) : null;

  async function load(): Promise<boolean> {
    if (data) return true;
    try {
      data = await o.fetchJSON<FacilityFile>(`places/${k.file}.json`);
    } catch {
      o.legend.hidden = false;
      o.legend.textContent = `この公開版には${k.label}のデータがありません。`;
      return false;
    }
    loader?.init(data);
    o.map.addSource(SOURCE, { type: "geojson", data: { type: "FeatureCollection", features: [] } as never });
    // 施設1か所ずつ同じ大きさ。拡大するほど大きく描く
    const radius = k.split
      ? ["interpolate", ["linear"], ["zoom"], 8, 2.6, 12, 4.5, 15, 6.5]
      : ["interpolate", ["linear"], ["zoom"], 4, 2.6, 8, 4, 12, 6.5];
    o.map.addLayer({
      id: LAYER, type: "circle", source: SOURCE,
      paint: {
        "circle-radius": radius as never,
        "circle-color": ["get", "color"] as never, "circle-opacity": 0.85,
        "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.2,
      },
    }, o.beforeLayer);
    o.map.addLayer({
      id: SELECTED, type: "circle", source: SOURCE, filter: ["==", ["get", "id"], ""],
      paint: { "circle-radius": radius as never, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#d00", "circle-stroke-width": 3 },
    }, o.beforeLayer);
    o.map.addLayer({
      id: LABEL, type: "symbol", source: SOURCE, minzoom: k.labelZoom,
      layout: {
        "text-field": ["get", "label"], "text-font": o.labelFont, "text-size": 11,
        "text-offset": [0, 0.9], "text-anchor": "top", "text-padding": 4,
      },
      paint: { "text-color": k.text, "text-halo-color": "rgba(255,255,255,0.95)", "text-halo-width": 1.6 },
    });
    o.map.on("mouseenter", LAYER, () => (o.map.getCanvas().style.cursor = "pointer"));
    o.map.on("mouseleave", LAYER, () => (o.map.getCanvas().style.cursor = ""));
    if (loader) {
      total = Object.values(data.prefectures ?? {}).reduce((s, p) => s + p.count, 0);
      o.map.on("moveend", updateLegend);
    }
    if (data.points) render(data.points);
    updateLegend();
    return true;
  }

  function updateLegend() {
    if (!data) return;
    const when = data.periods[data.periods.length - 1]?.label ?? "";
    if (o.kind === "michi") {
      o.legend.innerHTML = `国土交通省に登録された${k.label}（${esc(when)}、${formatNumber(total, 0)}か所）。` +
        (located < total ? `位置が分からない${formatNumber(total - located, 0)}か所は地図に表示していません。` : "");
      return;
    }
    const swatches = Object.entries(k.colors ?? {}).map(([name, color]) =>
      `<span class="facility-swatch"><i style="background:${color}"></i>${esc(name)}</span>`).join("");
    o.legend.innerHTML = `国が指定・登録・選定した文化財（${esc(when)}、全国${formatNumber(total, 0)}件）。` +
      `史跡などの広い範囲のものも代表の1点で表示しています。<span class="facility-swatches">${swatches}</span>` +
      (loader?.tooFar() ? "文化財は地図を拡大すると表示します。" : "");
  }

  /** 読み込んだ施設を地図に描き直す（文化財は都道府県の分が増えるたびに全体） */
  function render(items: FacilityPoint[]) {
    byId = new Map(items.map((p) => [p.id, p]));
    if (!loader) total = items.length;
    const shown = items.filter((p) => p.coord);
    located = shown.length;
    (o.map.getSource(SOURCE) as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: shown.map((p) => ({
        type: "Feature",
        properties: { id: p.id, name: facilityName(o.kind, p.name), label: p.name, color: facilityColor(o.kind, p) },
        geometry: { type: "Point", coordinates: p.coord! },
      })),
    } as never);
    updateLegend();
  }

  async function setVisible(on: boolean) {
    if (on && !(await load())) {
      o.toggle.checked = false;
      return;
    }
    o.legend.hidden = !on && !!data;
    for (const id of [LAYER, SELECTED, LABEL]) {
      if (o.map.getLayer(id)) o.map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    }
    if (!on) showPoint(null);
    else void loader?.refresh();
  }
  o.toggle.addEventListener("change", () => void setVisible(o.toggle.checked));

  /** 道の駅の登録の時期・ホームページ */
  function michiHtml(p: FacilityPoint): string {
    const registered = p.registered ? `${p.registered}に登録${p.round ? `（第${p.round}回）` : ""}` : "";
    return (registered ? `<p>${esc(registered)}</p>` : "") +
      (p.url ? `<p><a href="${esc(p.url)}" target="_blank" rel="noopener">ホームページ</a></p>` : "");
  }

  /** 文化財の種類・時代・指定の時期・棟・所在地 */
  function bunkaHtml(p: FacilityPoint): string {
    const facts = [
      p.subtype ? `種類: ${p.subtype}` : "",
      p.era ? `時代: ${p.era}` : "",
      p.buildings && p.buildings.length ? `棟: ${p.buildings.join("、")}${p.buildings.length > 1 ? `（${p.buildings.length}棟）` : ""}` : "",
      p.address ? `所在地: ${p.address}` : "",
    ].filter(Boolean);
    return `<div>${esc(p.kind ?? "")}</div>` +
      [p.date, p.treasure].filter(Boolean).map((d) => `<p>${esc(d!)}</p>`).join("") +
      (facts.length ? `<p class="small">${facts.map(esc).join("<br>")}</p>` : "") +
      (p.db ? `<p><a href="${DB_URL}${esc(p.db)}" target="_blank" rel="noopener">国指定文化財等データベースで見る</a></p>` : "");
  }

  /** 情報を出している施設の位置 */
  let at: [number, number] | null = null;
  let picked: string | null = null;
  function showPoint(id: string | null) {
    if (o.map.getLayer(SELECTED)) o.map.setFilter(SELECTED, ["==", ["get", "id"], id ?? ""]);
    const p = id ? byId.get(id) : undefined;
    at = p && data ? p.coord : null;
    picked = p && data ? p.id : null;
    if (!p || !data) {
      o.panel.hidden = true;
      o.panel.innerHTML = "";
      o.onPanel();
      return;
    }
    const where = municipalityText(p, o.municipalityName) || (o.kind === "michi" ? p.address : "") || "";
    o.panel.hidden = false;
    o.panel.innerHTML = `
      <button type="button" class="close" data-close aria-label="${k.label}の情報を閉じる">×</button>
      <p class="muted">${esc(where)}</p>
      <h2>${esc(facilityName(o.kind, p.name))}</h2>
      ${o.kind === "michi" ? michiHtml(p) : bunkaHtml(p)}
      ${p.location_note ? `<p class="note small">地図の位置は${esc(p.location_note)}です。</p>` : ""}
      <p class="muted small">${data.caveats.map(esc).join(" ")}</p>
      ${sourcesHtml(data.source_ids, o.sources)}`;
    o.onPanel();
  }

  o.panel.addEventListener("click", (ev) => {
    if ((ev.target as HTMLElement).closest("[data-close]")) showPoint(null);
  });

  // ?show=michi（文化財は bunka）で開いたときは表示をオンにする（トップページの指標の一覧から）。
  // ?me=<ID>（文化財は ?cp=）ならその施設を選ぶ
  const params = new URLSearchParams(location.search);
  const initial = params.get(k.param);
  if (initial || params.get("show")?.split(",").includes(k.show)) {
    o.toggle.checked = true;
    void setVisible(true).then(async () => {
      const p = !initial ? undefined : loader ? await loader.find((x) => x.id === initial) : byId.get(initial);
      if (!p) return;
      if (p.coord) o.focus(p.coord, k.split ? 13 : 10);
      showPoint(p.id);
    });
  }

  return {
    layer: LAYER,
    kind: k.label,
    visible: () => !!o.map.getLayer(LAYER) && o.toggle.checked,
    sourceIds: () => data?.source_ids ?? [],
    urlState: () => pointUrlState(o.toggle.checked, k.show, k.param, picked, !o.panel.hidden),
    show: showPoint,
    isOpen: () => !o.panel.hidden,
    coord: () => (o.panel.hidden ? null : at),
  };
}
