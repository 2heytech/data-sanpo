// 値のない施設の点レイヤー（道の駅）。点の大きさはそろえ、選ぶと所在地・登録の時期・ホームページを出す。
// 道の駅は全国で約1,200か所と少ないので、places/michi_no_eki.json の1ファイルに全件をまとめ、全国を見ているときから表示する。
// 2つの市区町村にまたがる駅は、点は1つで、情報には両方の市区町村を出す（docs/design-changes.md #149）。
import type { Map as MapLibreMap } from "maplibre-gl";
import { sourcesHtml, type PointLayer } from "./points";
import { formatNumber } from "../lib/format";
import type { FacilityFile, FacilityPoint, Source } from "../lib/types";
import { esc } from "../lib/html";

export type FacilityKind = "michi";

const KINDS: Record<FacilityKind, { file: string; show: string; param: string; label: string; color: string; text: string }> = {
  michi: { file: "michi_no_eki", show: "michi", param: "me", label: "道の駅", color: "#d9480f", text: "#8a2c06" },
};

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

export function initFacilities(o: Options): PointLayer {
  const k = KINDS[o.kind];
  const LAYER = `${o.kind}-circle`;
  const SELECTED = `${o.kind}-selected`;
  const LABEL = `${o.kind}-label`;
  const SOURCE = `${o.kind}-points`;
  let data: FacilityFile | null = null;
  let byId = new Map<string, FacilityPoint>();

  async function load(): Promise<boolean> {
    if (data) return true;
    try {
      data = await o.fetchJSON<FacilityFile>(`places/${k.file}.json`);
    } catch {
      o.legend.hidden = false;
      o.legend.textContent = `この公開版には${k.label}のデータがありません。`;
      return false;
    }
    const points = data.points ?? [];
    byId = new Map(points.map((p) => [p.id, p]));
    const located = points.filter((p) => p.coord);
    o.map.addSource(SOURCE, {
      type: "geojson",
      data: {
        type: "FeatureCollection",
        features: located.map((p) => ({
          type: "Feature",
          properties: { id: p.id, name: facilityName(o.kind, p.name), label: p.name },
          geometry: { type: "Point", coordinates: p.coord! },
        })),
      } as never,
    });
    // 施設1か所ずつ同じ大きさ。拡大するほど大きく描く
    const radius = ["interpolate", ["linear"], ["zoom"], 4, 2.6, 8, 4, 12, 6.5];
    o.map.addLayer({
      id: LAYER, type: "circle", source: SOURCE,
      paint: {
        "circle-radius": radius as never,
        "circle-color": k.color, "circle-opacity": 0.85,
        "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.2,
      },
    }, o.beforeLayer);
    o.map.addLayer({
      id: SELECTED, type: "circle", source: SOURCE, filter: ["==", ["get", "id"], ""],
      paint: { "circle-radius": radius as never, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#d00", "circle-stroke-width": 3 },
    }, o.beforeLayer);
    o.map.addLayer({
      id: LABEL, type: "symbol", source: SOURCE, minzoom: 9,
      layout: {
        "text-field": ["get", "label"], "text-font": o.labelFont, "text-size": 11,
        "text-offset": [0, 0.9], "text-anchor": "top", "text-padding": 4,
      },
      paint: { "text-color": k.text, "text-halo-color": "rgba(255,255,255,0.95)", "text-halo-width": 1.6 },
    });
    o.map.on("mouseenter", LAYER, () => (o.map.getCanvas().style.cursor = "pointer"));
    o.map.on("mouseleave", LAYER, () => (o.map.getCanvas().style.cursor = ""));
    const when = data.periods[data.periods.length - 1]?.label ?? "";
    o.legend.innerHTML = `国土交通省に登録された${k.label}（${esc(when)}、${formatNumber(points.length, 0)}か所）。` +
      (located.length < points.length ? `位置が分からない${formatNumber(points.length - located.length, 0)}か所は地図に表示していません。` : "");
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

  /** 情報を出している施設の位置 */
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
    const where = municipalityText(p, o.municipalityName) || p.address || "";
    const registered = p.registered ? `${p.registered}に登録${p.round ? `（第${p.round}回）` : ""}` : "";
    o.panel.hidden = false;
    o.panel.innerHTML = `
      <button type="button" class="close" data-close aria-label="${k.label}の情報を閉じる">×</button>
      <p class="muted">${esc(where)}</p>
      <h2>${esc(facilityName(o.kind, p.name))}</h2>
      ${registered ? `<p>${esc(registered)}</p>` : ""}
      ${p.url ? `<p><a href="${esc(p.url)}" target="_blank" rel="noopener">ホームページ</a></p>` : ""}
      ${p.location_note ? `<p class="note small">地図の位置は${esc(p.location_note)}です。</p>` : ""}
      <p class="muted small">${esc(data.description)}</p>
      <p class="muted small">${data.caveats.map(esc).join(" ")}</p>
      ${sourcesHtml(data.source_ids, o.sources)}`;
    o.onPanel();
  }

  o.panel.addEventListener("click", (ev) => {
    if ((ev.target as HTMLElement).closest("[data-close]")) showPoint(null);
  });

  // ?show=michi で開いたときは表示をオンにする（トップページの指標の一覧から）。?me=<ID> ならその施設を選ぶ
  const params = new URLSearchParams(location.search);
  const initial = params.get(k.param);
  if (initial || params.get("show")?.split(",").includes(k.show)) {
    o.toggle.checked = true;
    void setVisible(true).then(() => {
      const p = initial ? byId.get(initial) : undefined;
      if (!p) return;
      if (p.coord) o.map.jumpTo({ center: p.coord, zoom: Math.max(o.map.getZoom(), 10) });
      showPoint(p.id);
    });
  }

  return {
    layer: LAYER,
    kind: k.label,
    visible: () => !!o.map.getLayer(LAYER) && o.toggle.checked,
    show: showPoint,
    isOpen: () => !o.panel.hidden,
    coord: () => (o.panel.hidden ? null : at),
  };
}
