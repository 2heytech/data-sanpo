// 認可保育所の点レイヤー（東京都福祉局「社会福祉施設等一覧」）。認可定員が多いほど円を大きくする。
// 「認可保育所を表示」をオンにしたときに初めて places/nursery_capacity.json を読み込む。
// 定員は受け入れの上限で、通っている子どもの数ではないことを凡例と詳細に明記する。
import type { Map as MapLibreMap } from "maplibre-gl";
import type { PointLayer } from "./points";
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
  const latest = () => (data ? data.periods.length - 1 : 0);

  async function load(): Promise<boolean> {
    if (data) return true;
    try {
      data = await o.fetchJSON<NurseryFile>("places/nursery_capacity.json");
    } catch {
      o.legend.hidden = false;
      o.legend.textContent = "この公開版には認可保育所のデータがありません。";
      return false;
    }
    byId = new Map(data.points.map((p) => [p.id, p]));
    const i = latest();
    const shown = data.points.filter((p) => p.coord && p.values[i] != null);
    o.map.addSource("nurseries", {
      type: "geojson",
      data: {
        type: "FeatureCollection",
        features: shown.map((p) => ({
          type: "Feature",
          properties: { id: p.id, name: p.name, v: p.values[i] },
          geometry: { type: "Point", coordinates: p.coord! },
        })),
      } as never,
    });
    const v = ["get", "v"];
    // 定員（人）に応じた大きさ。ズームに合わせて全体を大きくする
    const size = (z: number) => ["interpolate", ["linear"], v, 20, 2 * z, 60, 3 * z, 120, 4.2 * z, 250, 6 * z];
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
        "text-field": ["concat", ["get", "name"], "\n定員", ["to-string", v], "人"],
        "text-font": o.labelFont, "text-size": 10, "text-offset": [0, 1], "text-anchor": "top", "text-padding": 4,
        "symbol-sort-key": ["-", 0, v] as never,
      },
      paint: { "text-color": LABEL_COLOR, "text-halo-color": "rgba(255,255,255,0.95)", "text-halo-width": 1.5 },
    });
    o.map.on("mouseenter", LAYER, () => (o.map.getCanvas().style.cursor = "pointer"));
    o.map.on("mouseleave", LAYER, () => (o.map.getCanvas().style.cursor = ""));
    o.legend.innerHTML =
      `${esc(data.periods[i].label)}の認可保育所（${formatNumber(shown.length, 0)}か所）。円が大きいほど認可定員が多い施設です。` +
      `定員は受け入れの上限で、通っている子どもの数ではありません。`;
    return true;
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
      <div>${esc(data.name)}（${esc(data.periods[i].label)}）</div>
      <div class="value">${v != null ? `${formatNumber(v, 0)}人` : "値なし"}</div>
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
