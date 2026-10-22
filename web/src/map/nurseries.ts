// 保育所などの点レイヤー（東京都の認可保育所は東京都福祉局「社会福祉施設等一覧」の認可定員、それ以外の認可保育所・
// 認定こども園・小規模保育・事業所内保育は「ここdeサーチ」の利用定員と利用者数。#138）。定員が多いほど円を大きくする。
// 「保育所」をオンにしたときに初めて places/nursery_capacity.json を読み込み、施設の一覧は地図に映っている
// 都道府県の分だけ読む（createPrefLoader）。時点は出典ごとに違うので、施設ごとに値のある時点を出す。
// 定員は受け入れの上限で、通っている子どもの数ではないことを凡例と詳細に明記する。
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import { createPrefLoader, type PointLayer, sourcesHtml } from "./points";
import { formatNumber } from "../lib/format";
import type { Source, NurseryFile, NurseryPoint } from "../lib/types";
import { esc } from "../lib/html";

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
  /** 地点の情報の表示が変わったとき（開いた・閉じた・別の地点にした） */
  onPanel: () => void;
}

export function initNurseries(o: Options): PointLayer {
  let data: NurseryFile | null = null;
  let byId = new Map<string, NurseryPoint>();
  /** 施設ごとの時点（値か状態のある最後の時点。ない施設は -1） */
  const lastIndex = (p: NurseryPoint) => {
    for (let i = p.values.length - 1; i >= 0; i--) if (p.values[i] != null || p.status?.[i] != null) return i;
    return -1;
  };
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
      o.legend.textContent = "この公開版には保育所のデータがありません。";
      return false;
    }
    loader.init(data);
    o.map.addSource("nurseries", { type: "geojson", data: { type: "FeatureCollection", features: [] } as never });
    const v = ["get", "v"];
    // 定員（人）に応じた大きさ。ズームに合わせて全体を大きくする
    // 定員のない施設（公表していない施設、v = -1）は小さな点
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
      `認可保育所・認定こども園・小規模保育など。円が大きいほど定員が多い施設です。` +
      `定員は受け入れの上限で、通っている子どもの数ではありません。定員を公表していない施設は小さな点で表示しています。` +
      (only ? "位置だけの施設があります。" : "") +
      (loader.tooFar() ? "保育所は地図を拡大すると表示します。" : "");
  }

  /** 読み込んだ施設（都道府県の分が増えるたびに全体）を地図に描き直す */
  function render(items: NurseryPoint[]) {
    byId = new Map(items.map((p) => [p.id, p]));
    const shown = items.filter((p) => p.coord && (p.location_only || lastIndex(p) >= 0));
    (o.map.getSource("nurseries") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: shown.map((p) => ({
        type: "Feature",
        properties: { id: p.id, name: p.name, v: p.values[lastIndex(p)] ?? -1 },
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

  /** 情報を出している施設の位置（位置を求められなかった施設は null） */
  let at: [number, number] | null = null;
  function showPoint(id: string | null) {
    if (o.map.getLayer(SELECTED)) o.map.setFilter(SELECTED, ["==", ["get", "id"], id ?? ""]);
    const p = id ? byId.get(id) : undefined;
    at = p && data ? p.coord : null;
    if (!p || !data) {
      o.panel.hidden = true;
      o.panel.innerHTML = "";
      o.onPanel();
      return;
    }
    const i = lastIndex(p);
    const v = i >= 0 ? p.values[i] : null;
    const kind = p.capacity_kind ?? "認可定員";
    // ここdeサーチの値は、各施設が公表している内容を取得した日の時点
    const when = i < 0 ? "" : kind === "利用定員"
      ? `${data.periods[i].label.replace("現在", "")}に取得` : data.periods[i].label;
    const users = i >= 0 ? p.users?.[i] : null;
    const ages = Object.entries(p.by_age ?? {}).filter(([, vals]) => vals[i] != null);
    o.panel.hidden = false;
    o.panel.innerHTML = `
      <button type="button" class="close" data-close aria-label="保育所の情報を閉じる">×</button>
      <p class="muted">${esc(o.municipalityName(p.municipality_id))}・${esc(p.facility_type ?? "認可保育所")}</p>
      <h2>${esc(p.name)}</h2>
      <p class="muted small">${esc(p.address ?? "")}${p.founder ? `（設置: ${esc(p.founder)}）` : ""}</p>
      ${p.location_only ? `<div>${esc(data.name)}</div>
      <div class="value">公開データなし</div>`
      : `<div>${esc(kind)}${when ? `（${esc(when)}）` : ""}</div>
      <div class="value">${v != null ? `${formatNumber(v, 0)}人` : "公表なし"}</div>
      ${users != null ? `<p>通っている子ども（利用者数）: ${formatNumber(users, 0)}人</p>` : ""}
      ${ages.length ? `<p class="small">年齢別: ${ages.map(([a, vals]) => `${esc(a)} ${formatNumber(vals[i]!, 0)}人`).join("、")}</p>` : ""}
      ${kind === "利用定員" ? `<p class="note small">子ども・子育て支援情報公表システム「ここdeサーチ」で施設が公表している内容です。施設ごとに更新の時期が違います。</p>` : ""}`}
      ${!p.coord ? `<p class="note small">所在地から位置を求められなかったため、地図には表示していません。</p>`
        : p.precision === "町丁目" ? `<p class="note small">所在地の街区が見つからないため、町丁目の代表点に表示しています。</p>` : ""}
      <p class="muted small">${data.caveats.map(esc).join(" ")}</p>
      ${sourcesHtml(p.sources ?? data.source_ids, o.sources)}`;
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
    kind: "保育所",
    visible: () => !!o.map.getLayer(LAYER) && o.toggle.checked,
    sourceIds: () => data?.source_ids ?? [],
    show: showPoint,
    isOpen: () => !o.panel.hidden,
    coord: () => (o.panel.hidden ? null : at),
  };
}
