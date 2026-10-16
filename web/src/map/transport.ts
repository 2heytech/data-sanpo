// 空港・港の点レイヤー。円の面積を最新の年の乗降客数（空港）・船舶乗降人員（港）に対応させる。
// 空港は全国で約100、港は数百と少ないので、places/<指標>.json の1ファイルに全件をまとめ、全国を見ているときから表示する。
// 空港・港1か所の値なので地域には割り振らない（docs/design-changes.md #110）。選ぶと国内・国際の内訳と年ごとの推移を出す。
import type { Map as MapLibreMap } from "maplibre-gl";
import { sourcesHtml, type PointLayer } from "./points";
import { formatNumber } from "../lib/format";
import type { Source, TransportFile, TransportPoint } from "../lib/types";
import { esc } from "../lib/html";

export type TransportKind = "airport" | "port";

const KINDS: Record<TransportKind, {
  file: string; show: string; param: string; label: string; total: string;
  domestic: string; international: string; color: string; text: string;
}> = {
  airport: {
    file: "airport_passengers", show: "airports", param: "ap", label: "空港", total: "乗降客数",
    domestic: "国内線", international: "国際線", color: "#0b5cad", text: "#0b3f78",
  },
  port: {
    file: "port_passengers", show: "ports", param: "pt", label: "港", total: "乗降人員",
    domestic: "国内航路", international: "外国航路", color: "#0f7a72", text: "#0b524c",
  },
};

interface Options {
  kind: TransportKind;
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

/** 最新の年に値のある年の番号（値がひとつもなければ最後の年） */
export function latestIndex(p: Pick<TransportPoint, "values">): number {
  for (let k = p.values.length - 1; k >= 0; k--) if (p.values[k] != null) return k;
  return p.values.length - 1;
}

/** 前の年からの増減（例: 「+12.3%」）。どちらかの年に値がない・前の年が0なら空 */
export function changeText(prev: number | null | undefined, v: number | null | undefined): string {
  if (prev == null || v == null || prev <= 0) return "";
  const r = ((v - prev) / prev) * 100;
  return `${r >= 0.05 ? "+" : r <= -0.05 ? "−" : "±"}${formatNumber(Math.abs(r), 1)}%`;
}

/** 地図・右の欄に出す名前。表の名前は「東京国際」「東京」なので「空港」「港」を付ける（飛行場・ヘリポートはそのまま） */
export function displayName(kind: TransportKind, name: string): string {
  if (kind === "airport") return /(空港|飛行場|ヘリポート)$/.test(name) ? name : `${name}空港`;
  return name.endsWith("港") ? name : `${name}港`;
}

export function initTransport(o: Options): PointLayer {
  const k = KINDS[o.kind];
  const LAYER = `${o.kind}-circle`;
  const SELECTED = `${o.kind}-selected`;
  const LABEL = `${o.kind}-label`;
  const SOURCE = `${o.kind}-points`;
  let data: TransportFile | null = null;
  let byId = new Map<string, TransportPoint>();

  async function load(): Promise<boolean> {
    if (data) return true;
    try {
      data = await o.fetchJSON<TransportFile>(`places/${k.file}.json`);
    } catch {
      o.legend.hidden = false;
      o.legend.textContent = `この公開版には${k.label}のデータがありません。`;
      return false;
    }
    byId = new Map(data.points.map((p) => [p.id, p]));
    const last = data.periods.length - 1;
    o.map.addSource(SOURCE, {
      type: "geojson",
      data: {
        type: "FeatureCollection",
        // 最新の年に値のない（廃止・休止した）空港・港は描かない
        features: data.points.filter((p) => p.values[last] != null).map((p) => ({
          type: "Feature",
          properties: { id: p.id, name: displayName(o.kind, p.name), v: p.values[last], label: `${formatNumber(p.values[last]!, 0)}人` },
          geometry: { type: "Point", coordinates: p.coord },
        })),
      } as never,
    });
    // 面積が人数に比例するよう半径は平方根（年の人数なので駅の1日の人数より大きい係数は小さく）。拡大するほど大きく描く
    const v = ["get", "v"];
    const size = (f: number, min: number) => ["max", min, ["*", ["sqrt", v], f]];
    const radius = ["interpolate", ["linear"], ["zoom"], 4, size(0.0022, 2.5), 8, size(0.0045, 3.5), 12, size(0.009, 5)];
    o.map.addLayer({
      id: LAYER, type: "circle", source: SOURCE,
      layout: { "circle-sort-key": ["-", 0, v] as never },
      paint: {
        "circle-radius": radius as never,
        "circle-color": k.color, "circle-opacity": 0.45,
        "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.2,
      },
    }, o.beforeLayer);
    o.map.addLayer({
      id: SELECTED, type: "circle", source: SOURCE, filter: ["==", ["get", "id"], ""],
      paint: { "circle-radius": radius as never, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#d00", "circle-stroke-width": 3 },
    }, o.beforeLayer);
    o.map.addLayer({
      id: LABEL, type: "symbol", source: SOURCE, minzoom: 7,
      layout: {
        "text-field": ["format", ["get", "name"], {}, "\n", {}, ["get", "label"], { "font-scale": 0.85 }] as never,
        "text-font": o.labelFont, "text-size": 11, "text-offset": [0, 1.1], "text-anchor": "top",
        "symbol-sort-key": ["-", 0, v] as never, "text-padding": 4,
      },
      paint: { "text-color": k.text, "text-halo-color": "rgba(255,255,255,0.95)", "text-halo-width": 1.6 },
    });
    o.map.on("mouseenter", LAYER, () => (o.map.getCanvas().style.cursor = "pointer"));
    o.map.on("mouseleave", LAYER, () => (o.map.getCanvas().style.cursor = ""));
    const shown = data.points.filter((p) => p.values[last] != null).length;
    o.legend.innerHTML = `円の面積は${esc(data.periods[last]?.label ?? "")}の1年間の${k.total}（${formatNumber(shown, 0)}か所）。` +
      `${k.label}1か所ずつの値で、地域の合計ではありません。`;
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

  const people = (x: number | null | undefined) => (x == null ? "−" : `${formatNumber(x, 0)}人`);
  // 表の中は単位を見出しにまとめる
  const num = (x: number | null | undefined) => (x == null ? "−" : formatNumber(x, 0));

  function showPoint(id: string | null) {
    if (o.map.getLayer(SELECTED)) o.map.setFilter(SELECTED, ["==", ["get", "id"], id ?? ""]);
    const p = id ? byId.get(id) : undefined;
    if (!p || !data) {
      o.panel.hidden = true;
      o.panel.innerHTML = "";
      o.onPanel();
      return;
    }
    const i = latestIndex(p);
    const per = data.periods;
    // 右の欄の幅に収まるよう、合計の推移と国内・国際の内訳を別の表にする
    const has = (n: number) => p.values[n] != null || p.domestic[n] != null || p.international[n] != null;
    const cur = (n: number) => (n === i ? ' aria-current="true"' : "");
    const rows = per.map((x, n) => has(n) ? `<tr${cur(n)}><td>${esc(x.label)}</td><td class="num">${num(p.values[n])}</td>
        <td class="num">${changeText(p.values[n - 1], p.values[n])}</td></tr>` : "").join("");
    const parts = per.map((x, n) => has(n) ? `<tr${cur(n)}><td>${esc(x.label)}</td><td class="num">${num(p.domestic[n])}</td>
        <td class="num">${num(p.international[n])}</td></tr>` : "").join("");
    o.panel.hidden = false;
    o.panel.innerHTML = `
      <button type="button" class="close" data-close aria-label="${k.label}の情報を閉じる">×</button>
      <p class="muted">${esc(o.municipalityName(p.municipality_id))}</p>
      <h2>${esc(displayName(o.kind, p.name))}</h2>
      <div>${esc(data.name)}（${esc(per[i]?.label ?? "")}）</div>
      <div class="value">${people(p.values[i])}</div>
      <p class="small">${k.domestic} ${people(p.domestic[i])}・${k.international} ${people(p.international[i])}</p>
      <table class="trend"><caption>推移（人）</caption>
        <thead><tr><th>年</th><th class="num">${k.total}</th><th class="num">前年から</th></tr></thead>
        <tbody>${rows}</tbody></table>
      <table class="trend"><caption>内訳（人）</caption>
        <thead><tr><th>年</th><th class="num">${k.domestic}</th><th class="num">${k.international}</th></tr></thead>
        <tbody>${parts}</tbody></table>
      <p class="muted small">${esc(data.description)}</p>
      <p class="muted small">${data.caveats.map(esc).join(" ")}</p>
      ${sourcesHtml(data.source_ids, o.sources)}`;
    o.onPanel();
  }

  o.panel.addEventListener("click", (ev) => {
    if ((ev.target as HTMLElement).closest("[data-close]")) showPoint(null);
  });

  // ?show=airports（港は ports）で開いたときは表示をオンにする（トップページの指標の一覧から）。
  // ?ap=<空港ID>（港は ?pt=）ならその地点を選ぶ
  const params = new URLSearchParams(location.search);
  const initial = params.get(k.param);
  if (initial || params.get("show")?.split(",").includes(k.show)) {
    o.toggle.checked = true;
    void setVisible(true).then(() => {
      const p = initial ? byId.get(initial) : undefined;
      if (!p) return;
      o.map.jumpTo({ center: p.coord, zoom: Math.max(o.map.getZoom(), 9) });
      showPoint(p.id);
    });
  }

  return {
    layer: LAYER,
    kind: k.label,
    visible: () => !!o.map.getLayer(LAYER) && o.toggle.checked,
    show: showPoint,
    isOpen: () => !o.panel.hidden,
  };
}
