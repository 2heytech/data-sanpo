// 認可保育所の点レイヤー（東京都福祉局「社会福祉施設等一覧」）。認可定員が多いほど円を大きくする。
// 「認可保育所を表示」をオンにしたときに初めて places/nursery_capacity.json を読み込み、施設の一覧は地図に映っている
// 都道府県の分だけ読む（createPrefLoader）。東京都以外は定員の公開データがなく、国土数値情報の位置だけを小さな点で出す。
// 定員は受け入れの上限で、通っている子どもの数ではないことを凡例と詳細に明記する。
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import { createPrefLoader, type PointLayer } from "./points";
import { formatNumber } from "../lib/format";
import type { Source, NurseryFile, NurseryPoint } from "../lib/types";

const LAYER = "nursery-circle";
const SELECTED = "nursery-selected";
const LABEL = "nursery-label";
export const NURSERY_COLOR = "#c2255c";
const LABEL_COLOR = "#8a1c43";

interface Options {
  map: MapLibreMap;
  fetchJSON: <T>(rel: string) => Promise<T>;
  toggle: HTMLInputElement;
  legend: HTMLElement;
  panel: HTMLElement;
  sources: Map<string, Source>;
  municipalityName: (id: string) => string;
  beforeLayer: string;
  labelFont: string[];
  /** 右の欄の表示が変わったとき（開いた・閉じた） */
  onPanel: () => void;
}

export function initNurseries(o: Options): PointLayer {
  let data: NurseryFile | null = null;
  let byId = new Map<string, NurseryPoint>();
  let counts = { valued: 0, only: 0 };
  const latest = () => (data ? data.periods.length - 1 : 0);
  const loader = createPrefLoader<NurseryPoint>({
    map: o.map, fetchJSON: o.fetchJSON, id: "nursery_capacity", key: "points",
    active: () => o.toggle.checked,
    onChange: (items) => render(items),
  });

  async function load(): Promise<boolean> {
    if (data) return true;
    try {
      data = await o.fetchJSON<NurseryFile>("places/nursery_capacity.json");
    } catch {
      o.legend.hidden = false;
      o.legend.textContent = "この公開版には認可保育所のデータがありません。";
      return false;
    }
    loader.init(data);
    o.map.addSource("nurseries", { type: "geojson", data: { type: "FeatureCollection", features: [] } as never });
    const v = ["get", "v"];
    // 定員（人）に応じた大きさ。ズームに合わせて全体を大きくする
    // 定員のない施設（東京都以外、v = -1）は小さな点
    const size = (z: number) => ["case", ["<", v, 0], 1.6 * z,
      ["interpolate", ["linear"], v, 20, 2 * z, 60, 3 * z, 120, 4.2 * z, 250, 6 * z]];
    const radius = ["interpolate", ["linear"], ["zoom"], 9, size(0.8), 12, size(1.2), 15, size(1.8)];
    o.map.addLayer({
      id: LAYER, type: "circle", source: "nurseries",
      layout: { "circle-sort-key": ["-", 0, v] as never },
      paint: {
        "circle-radius": radius as never,
        "circle-color": NURSERY_COLOR,
        "circle-opacity": 0.75,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 1,
      },
    }, o.beforeLayer);
    o.map.addLayer({
      id: SELECTED, type: "circle", source: "nurseries", filter: ["==", ["get", "id"], ""],
      paint: { "circle-radius": radius as never, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#d00", "circle-stroke-width": 3 },
    }, o.beforeLayer);
    o.map.addLayer({
      id: LABEL, type: "symbol", source: "nurseries", minzoom: 14.5,
      layout: {
        "text-field": ["case", ["<", v, 0], ["get", "name"], ["concat", ["get", "name"], "\n定員", ["to-string", v], "人"]] as never,
        "text-font": o.labelFont, "text-size": 10, "text-offset": [0, 1], "text-anchor": "top", "text-padding": 4,
        "symbol-sort-key": ["-", 0, v] as never,
      },
      paint: { "text-color": LABEL_COLOR, "text-halo-color": "rgba(255,255,255,0.95)", "text-halo-width": 1.5 },
    });
    o.map.on("mouseenter", LAYER, () => (o.map.getCanvas().style.cursor = "pointer"));
    o.map.on("mouseleave", LAYER, () => (o.map.getCanvas().style.cursor = ""));
    o.map.on("moveend", updateLegend);
    if (data.points) render(data.points);   // 古い公開版（1ファイルに全件）
    updateLegend();
    return true;
  }

  function updateLegend() {
    if (!data) return;
    const only = loader.locationOnlyInView().length > 0;
    o.legend.innerHTML =
      `${esc(data.periods[latest()].label)}の認可保育所${counts.valued ? `（東京都 ${formatNumber(counts.valued, 0)}か所）` : ""}。` +
      `円が大きいほど認可定員が多い施設です。定員は受け入れの上限で、通っている子どもの数ではありません。` +
      (only ? "定員は東京都だけです。ほかの道府県は保育所の位置だけを小さな点で表示しています（利用条件で商用利用を認めていない自治体の施設は表示していません）。" : "") +
      (loader.tooFar() ? "保育所は地図を拡大すると表示します。" : "");
  }

  /** 読み込んだ施設（都道府県の分が増えるたびに全体）を地図に描き直す */
  function render(items: NurseryPoint[]) {
    byId = new Map(items.map((p) => [p.id, p]));
    const i = latest();
    const shown = items.filter((p) => p.coord && (p.location_only || p.values[i] != null));
    counts = { valued: shown.filter((p) => !p.location_only).length, only: shown.filter((p) => p.location_only).length };
    (o.map.getSource("nurseries") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: shown.map((p) => ({
        type: "Feature",
        properties: { id: p.id, name: p.name, v: p.values[i] ?? -1 },
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
    else void loader.refresh();
  }
  o.toggle.addEventListener("change", () => void setVisible(o.toggle.checked));

  function showPoint(id: string | null) {
    if (o.map.getLayer(SELECTED)) o.map.setFilter(SELECTED, ["==", ["get", "id"], id ?? ""]);
    const p = id ? byId.get(id) : undefined;
    if (!p || !data) {
      o.panel.hidden = true;
      o.panel.innerHTML = "";
      o.onPanel();
      return;
    }
    const i = latest();
    const v = p.values[i];
    const srcs = [...new Set(data.source_ids.map((sid) => o.sources.get(sid)?.attribution ?? sid))];
    o.panel.hidden = false;
    o.panel.innerHTML = `
      <button type="button" class="close" data-close aria-label="認可保育所の情報を閉じる">×</button>
      <p class="muted">${esc(o.municipalityName(p.municipality_id))}・認可保育所</p>
      <h2>${esc(p.name)}</h2>
      <p class="muted small">${esc(p.address ?? "")}${p.founder ? `（設置: ${esc(p.founder)}）` : ""}</p>
      ${p.location_only ? `<div>${esc(data.name)}</div>
      <div class="value">公開データなし</div>
      <p class="note small">定員は東京都の保育所だけです。ほかの道府県は、国土数値情報「福祉施設データ」（${esc(p.as_of ?? "")}）の保育所の位置だけを表示しています。</p>`
      : `<div>${esc(data.name)}（${esc(data.periods[i].label)}）</div>
      <div class="value">${v != null ? `${formatNumber(v, 0)}人` : "値なし"}</div>`}
      ${p.precision === "町丁目" ? `<p class="note small">所在地の街区が見つからないため、町丁目の代表点に表示しています。</p>` : ""}
      <p class="muted small">${data.caveats.map(esc).join(" ")}</p>
      <p class="muted small">${srcs.map(esc).join("／")}</p>`;
    o.onPanel();
  }

  o.panel.addEventListener("click", (e) => {
    if ((e.target as HTMLElement).closest("[data-close]")) showPoint(null);
  });

  // ?show=nurseries で開いたときは表示をオンにする（トップページの指標の一覧から）
  if (new URLSearchParams(location.search).get("show")?.split(",").includes("nurseries")) {
    o.toggle.checked = true;
    void setVisible(true);
  }

  return {
    layer: LAYER,
    kind: "認可保育所",
    visible: () => !!o.map.getLayer(LAYER) && o.toggle.checked,
    show: showPoint,
    isOpen: () => !o.panel.hidden,
  };
}

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
