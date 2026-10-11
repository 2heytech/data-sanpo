// 天気の点レイヤー（気象庁の平年値、統計期間1991〜2020年）。観測所ごとの年間の日照時間・降水量・
// 最深積雪・降雪量のうち、選んだ1つで円を塗り分ける。観測所は全国で約1,300地点と少ないので、
// places/weather_normals.json の1ファイルに全地点をまとめ、全国を見ているときから表示する（docs/design-changes.md #94）。
// 地域の平均ではなく観測所1地点の値であることを凡例と詳細に明記し、地域には割り振らない。
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import type { PointLayer } from "./points";
import { colorsFor } from "../lib/classify";
import { formatNumber } from "../lib/format";
import type { Source, WeatherElement, WeatherFile, WeatherStation } from "../lib/types";

const LAYER = "weather-circle";
const SELECTED = "weather-selected";
const LABEL = "weather-label";
const SOURCE = "weather-points";
const MONTHS = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"];
// 指標ごとの短い名前（切り替えの選択肢・月の表の見出し）
const SHORT: Record<string, string> = {
  sunshine_normal: "日照時間", precipitation_normal: "降水量", snow_depth_normal: "最深積雪", snowfall_normal: "降雪量",
};

interface Options {
  map: MapLibreMap;
  fetchJSON: <T>(rel: string) => Promise<T>;
  toggle: HTMLInputElement;
  /** 日照時間・降水量などの切り替え */
  select: HTMLSelectElement;
  legend: HTMLElement;
  panel: HTMLElement;
  sources: Map<string, Source>;
  municipalityName: (id: string) => string;
  beforeLayer: string;
  labelFont: string[];
  /** 右の欄の表示が変わったとき（開いた・閉じた） */
  onPanel: () => void;
}

/** 凡例の各区分の文言（例: 「1,000mm未満」「1,000〜1,200mm」「3,000mm以上」） */
export function weatherBins(e: Pick<WeatherElement, "breaks" | "unit" | "digits">): string[] {
  const f = (v: number) => formatNumber(v, e.digits);
  const b = e.breaks;
  if (!b.length) return [`${e.unit}`];
  return [`${f(b[0])}${e.unit}未満`, ...b.slice(1).map((x, k) => `${f(b[k])}〜${f(x)}${e.unit}`),
    `${f(b[b.length - 1])}${e.unit}以上`];
}

/** 円の色。いちばん淡い（ほぼ白の）色は地図の上で見えにくいので使わない */
export function weatherColors(e: Pick<WeatherElement, "scheme" | "breaks">): string[] {
  return colorsFor(e.scheme, e.breaks, true);
}

export function initWeather(o: Options): PointLayer {
  let data: WeatherFile | null = null;
  let byId = new Map<string, WeatherStation>();
  let current = "";
  const element = () => data?.elements.find((e) => e.id === current) ?? data?.elements[0];

  async function load(): Promise<boolean> {
    if (data) return true;
    try {
      data = await o.fetchJSON<WeatherFile>("places/weather_normals.json");
    } catch {
      o.legend.hidden = false;
      o.legend.textContent = "この公開版には天気のデータがありません。";
      return false;
    }
    byId = new Map(data.stations.map((s) => [s.id, s]));
    o.select.innerHTML = data.elements.map((e) =>
      `<option value="${e.id}">${esc(SHORT[e.id] ?? e.name)}</option>`).join("");
    if (!data.elements.some((e) => e.id === current)) current = data.elements[0]?.id ?? "";
    o.select.value = current;
    o.map.addSource(SOURCE, { type: "geojson", data: { type: "FeatureCollection", features: [] } as never });
    const radius = ["interpolate", ["linear"], ["zoom"], 4, 3, 8, 4.5, 12, 7];
    o.map.addLayer({
      id: LAYER, type: "circle", source: SOURCE,
      layout: { "circle-sort-key": ["get", "v"] as never },
      paint: {
        "circle-radius": radius as never,
        "circle-color": "#888",
        "circle-stroke-color": "#1c2733",
        "circle-stroke-width": 1,
      },
    }, o.beforeLayer);
    o.map.addLayer({
      id: SELECTED, type: "circle", source: SOURCE, filter: ["==", ["get", "id"], ""],
      paint: { "circle-radius": radius as never, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#d00", "circle-stroke-width": 3 },
    }, o.beforeLayer);
    o.map.addLayer({
      id: LABEL, type: "symbol", source: SOURCE, minzoom: 9,
      layout: {
        "text-field": ["concat", ["get", "name"], "\n", ["get", "label"]],
        "text-font": o.labelFont, "text-size": 10, "text-offset": [0, 1], "text-anchor": "top", "text-padding": 4,
      },
      paint: { "text-color": "#1c2733", "text-halo-color": "rgba(255,255,255,0.95)", "text-halo-width": 1.5 },
    });
    o.map.on("mouseenter", LAYER, () => (o.map.getCanvas().style.cursor = "pointer"));
    o.map.on("mouseleave", LAYER, () => (o.map.getCanvas().style.cursor = ""));
    render();
    return true;
  }

  /** 選んでいる指標の値で、値のある観測所を描き直す */
  function render() {
    const e = element();
    if (!data || !e) return;
    const colors = weatherColors(e);
    o.map.setPaintProperty(LAYER, "circle-color", (e.breaks.length
      ? ["step", ["get", "v"], colors[0], ...e.breaks.flatMap((b, k) => [b, colors[k + 1]])]
      : colors[0]) as never);
    const shown = data.stations.filter((s) => s.values[e.id] != null);
    (o.map.getSource(SOURCE) as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: shown.map((s) => ({
        type: "Feature",
        properties: { id: s.id, name: s.name, v: s.values[e.id], label: `${formatNumber(s.values[e.id], e.digits)}${e.unit}` },
        geometry: { type: "Point", coordinates: s.coord },
      })),
    } as never);
    const bins = weatherBins(e);
    o.legend.innerHTML =
      `${esc(e.name)}（${esc(data.periods[0]?.label ?? "")}、${formatNumber(shown.length, 0)}地点）。` +
      `地域の平均ではなく観測所1地点の値です。` +
      `<span class="land-bins">${colors.map((c, k) =>
        `<span><span class="sw" style="background:${c}"></span>${esc(bins[k])}</span>`).join("")}</span>`;
    const open = selectedId();
    if (open) showStation(open);
  }

  let selected: string | null = null;
  const selectedId = () => (o.panel.hidden ? null : selected);

  async function setVisible(on: boolean) {
    if (on && !(await load())) {
      o.toggle.checked = false;
      return;
    }
    o.select.hidden = !on;
    o.legend.hidden = !on && !!data;
    for (const id of [LAYER, SELECTED, LABEL]) {
      if (o.map.getLayer(id)) o.map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    }
    if (!on) showStation(null);
  }
  o.toggle.addEventListener("change", () => void setVisible(o.toggle.checked));
  o.select.addEventListener("change", () => {
    current = o.select.value;
    render();
  });

  function showStation(id: string | null) {
    selected = id;
    if (o.map.getLayer(SELECTED)) o.map.setFilter(SELECTED, ["==", ["get", "id"], id ?? ""]);
    const s = id ? byId.get(id) : undefined;
    const e = element();
    if (!s || !data || !e) {
      o.panel.hidden = true;
      o.panel.innerHTML = "";
      o.onPanel();
      return;
    }
    const els = data.elements.filter((x) => s.values[x.id] != null);
    const fmt = (x: WeatherElement, v: number | null | undefined) =>
      v == null ? "値なし" : `${formatNumber(v, x.digits)}${x.unit}`;
    // 30年に満たない期間から求めた値は、その期間を書く
    const short = els.filter((x) => s.years[x.id] && s.years[x.id][2] < 30)
      .map((x) => `${SHORT[x.id] ?? x.name}は${s.years[x.id][0]}〜${s.years[x.id][1]}年（${s.years[x.id][2]}年分）`);
    const missing = data.elements.filter((x) => s.values[x.id] == null).map((x) => SHORT[x.id] ?? x.name);
    const srcs = [...new Set(data.source_ids.map((sid) => o.sources.get(sid)?.attribution ?? sid))];
    o.panel.hidden = false;
    o.panel.innerHTML = `
      <button type="button" class="close" data-close aria-label="観測所の情報を閉じる">×</button>
      <p class="muted">${esc(o.municipalityName(s.municipality_id))}・気象庁の観測所${s.altitude_m != null ? `（標高${formatNumber(s.altitude_m, 0)}m）` : ""}</p>
      <h2>${esc(s.name)}</h2>
      <div>${esc(e.name)}（${esc(data.periods[0]?.label ?? "")}）</div>
      <div class="value">${fmt(e, s.values[e.id])}</div>
      <p class="small">${els.filter((x) => x.id !== e.id).map((x) => `${esc(x.name)} ${fmt(x, s.values[x.id])}`).join("・")}</p>
      ${missing.length ? `<p class="note small">${esc(missing.join("・"))}はこの観測所では観測していないか、平年値がありません（0ではありません）。</p>` : ""}
      ${short.length ? `<p class="note small">${esc(short.join("、"))}から求めた値です（30年に満たない期間）。</p>` : ""}
      <div class="trend-scroll"><table class="trend"><caption>月ごとの平年値</caption>
        <thead><tr><th>月</th>${els.map((x) => `<th class="num">${esc(SHORT[x.id] ?? x.name)}<br><span class="muted">${esc(x.unit)}</span></th>`).join("")}</tr></thead>
        <tbody>${MONTHS.map((m, k) => `<tr><td>${m}</td>${els.map((x) => {
          const v = s.monthly[x.id]?.[k];
          return `<td class="num">${v == null ? "−" : formatNumber(v, 0)}</td>`;
        }).join("")}</tr>`).join("")}</tbody></table></div>
      <p class="muted small">最深積雪の月の値はその月にいちばん深く積もったときの深さ、ほかは月の合計です。</p>
      <p class="muted small">${e.caveats.map(esc).join(" ")}</p>
      <p class="muted small">${srcs.map(esc).join("／")}</p>`;
    o.onPanel();
  }

  o.panel.addEventListener("click", (ev) => {
    if ((ev.target as HTMLElement).closest("[data-close]")) showStation(null);
  });

  // ?show=weather（&wx=<指標>）で開いたときは表示をオンにする（トップページの指標の一覧から）。
  // ?ws=<観測所ID> ならその観測所を選ぶ
  const params = new URLSearchParams(location.search);
  current = params.get("wx") ?? "";
  const station = params.get("ws");
  if (station || params.get("show")?.split(",").includes("weather")) {
    o.toggle.checked = true;
    void setVisible(true).then(() => {
      const s = station ? byId.get(station) : undefined;
      if (!s) return;
      o.map.jumpTo({ center: s.coord, zoom: Math.max(o.map.getZoom(), 10) });
      showStation(s.id);
    });
  }

  return {
    layer: LAYER,
    kind: "気象庁の観測所",
    visible: () => !!o.map.getLayer(LAYER) && o.toggle.checked,
    show: showStation,
    isOpen: () => !o.panel.hidden,
  };
}

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
