// 地価の点レイヤー。地価公示（国土数値情報「地価公示データ」、1月1日時点の標準地）と都道府県地価調査
// （「都道府県地価調査データ」、7月1日時点の基準地）の2つを同じ作りで出す（LAND_KINDS）。
// 地点ごとの最新の価格（円/㎡）で円を塗り分ける。
// 表示をオンにしたときに初めて places/<指標>.json を読み込み、地点の一覧は地図に映っている
// 都道府県の分だけ読む（createPrefLoader）。
// 地域の平均ではなく選ばれた1地点の価格であることを凡例と詳細に明記する。
// 価格は住宅地の数万円から都心の商業地の数千万円まで桁が違うので、切りのよい桁ごとの区切りで色を分ける。
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import { createPrefLoader, PLACES_MIN_ZOOM, type PointLayer } from "./points";
import { formatNumber } from "../lib/format";
import type { Source, LandPriceFile, LandPoint } from "../lib/types";

/** 地価の点の種類ごとの名前・URL の引数。地価調査の円は四角い縁取りにせず、縁の色で見分ける */
export const LAND_KINDS = {
  land_price: {
    name: "地価公示", point: "標準地", date: "1月1日", prefix: "land", param: "lp", show: "land",
    stroke: "#ffffff", idPattern: /^land-(\d\d)/,
  },
  land_survey_price: {
    name: "都道府県地価調査", point: "基準地", date: "7月1日", prefix: "landsv", param: "ls", show: "landsurvey",
    stroke: "#1c2733", idPattern: /^landsv-(\d\d)/,
  },
} as const;
export type LandKind = keyof typeof LAND_KINDS;
// 区切り（円/㎡）と色。塗り分け（青・緑・赤など）の上でも見分けられるよう、紫〜黄の配色に白い縁取りをつける
export const LAND_BREAKS = [100_000, 200_000, 300_000, 500_000, 1_000_000, 3_000_000, 10_000_000];
export const LAND_COLORS = ["#2c115f", "#5a167e", "#862781", "#b5367a", "#e04f67", "#f8765c", "#fdac78", "#fde3a1"];

interface Options {
  kind: LandKind;
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

export type LandPriceLayer = PointLayer;

/** 価格の区切りの表示（例: 10万円、1,000万円） */
export function yenLabel(v: number): string {
  return v >= 10_000 ? `${formatNumber(v / 10_000, 0)}万円` : `${formatNumber(v, 0)}円`;
}

/** 凡例の各区分の文言（例: 「10万円未満」「10万〜20万円」「1,000万円以上」） */
export function landBins(): string[] {
  const b = LAND_BREAKS.map((v) => yenLabel(v));
  return [
    `${b[0]}未満`,
    ...b.slice(1).map((label, k) => `${b[k].replace(/円$/, "")}〜${label}`),
    `${b[b.length - 1]}以上`,
  ];
}

export function initLandPrices(o: Options): LandPriceLayer {
  const k = LAND_KINDS[o.kind];
  const LAYER = `${k.prefix}-circle`;
  const SELECTED = `${k.prefix}-selected`;
  const LABEL = `${k.prefix}-label`;
  const SOURCE = `${k.prefix}-points`;
  // 推移の表の年の見出し（「2025年1月1日現在」→「2025年」）
  const yearOnly = (label: string) => label.replace(/\d+月\d+日.*$/, "");
  let data: LandPriceFile | null = null;
  let byId = new Map<string, LandPoint>();
  let shownCount = 0;
  const latest = () => (data ? data.periods.length - 1 : 0);
  const loader = createPrefLoader<LandPoint>({
    map: o.map, fetchJSON: o.fetchJSON, id: o.kind, key: "points",
    active: () => o.toggle.checked,
    onChange: (items) => render(items),
  });

  async function load(): Promise<boolean> {
    if (data) return true;
    try {
      data = await o.fetchJSON<LandPriceFile>(`places/${o.kind}.json`);
    } catch {
      o.legend.hidden = false;
      o.legend.textContent = `この公開版には${k.name}のデータがありません。`;
      return false;
    }
    loader.init(data);
    o.map.addSource(SOURCE, { type: "geojson", data: { type: "FeatureCollection", features: [] } as never });
    const v = ["get", "v"];
    const color = ["step", v, LAND_COLORS[0], ...LAND_BREAKS.flatMap((b, k) => [b, LAND_COLORS[k + 1]])];
    const radius = ["interpolate", ["linear"], ["zoom"], 9, 2.5, 12, 4.5, 15, 7];
    o.map.addLayer({
      id: LAYER, type: "circle", source: SOURCE,
      layout: { "circle-sort-key": v as never },
      paint: {
        "circle-radius": radius as never,
        "circle-color": color as never,
        "circle-stroke-color": k.stroke,
        "circle-stroke-width": 1.2,
      },
    }, o.beforeLayer);
    o.map.addLayer({
      id: SELECTED, type: "circle", source: SOURCE, filter: ["==", ["get", "id"], ""],
      paint: { "circle-radius": radius as never, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#d00", "circle-stroke-width": 3 },
    }, o.beforeLayer);
    o.map.addLayer({
      id: LABEL, type: "symbol", source: SOURCE, minzoom: 14.5,
      layout: {
        "text-field": ["concat", ["get", "name"], "\n", ["to-string", ["round", ["/", v, 10000]]], "万円"],
        "text-font": o.labelFont, "text-size": 10, "text-offset": [0, 1], "text-anchor": "top", "text-padding": 4,
        "symbol-sort-key": ["-", 0, v] as never,
      },
      paint: { "text-color": "#3a1450", "text-halo-color": "rgba(255,255,255,0.95)", "text-halo-width": 1.5 },
    });
    o.map.on("mouseenter", LAYER, () => (o.map.getCanvas().style.cursor = "pointer"));
    o.map.on("mouseleave", LAYER, () => (o.map.getCanvas().style.cursor = ""));
    o.map.on("zoomend", updateLegend);
    if (data.points) render(data.points);   // 古い公開版（1ファイルに全件）
    updateLegend();
    return true;
  }

  function updateLegend() {
    if (!data) return;
    const bins = landBins();
    o.legend.innerHTML =
      `${esc(data.periods[latest()].label)}の${k.point}の価格（1㎡あたり${shownCount ? `、読み込んだ${formatNumber(shownCount, 0)}地点` : ""}）。` +
      `地域の平均ではなく1地点の価格です。` + (loader.tooFar() ? `${k.point}は地図を拡大すると表示します。` : "") +
      `<span class="land-bins">${LAND_COLORS.map((c, k) =>
        `<span><span class="sw" style="background:${c}"></span>${esc(bins[k])}</span>`).join("")}</span>`;
  }

  /** 読み込んだ地点（都道府県の分が増えるたびに全体）を地図に描き直す */
  function render(items: LandPoint[]) {
    byId = new Map(items.map((p) => [p.id, p]));
    const i = latest();
    const shown = items.filter((p) => p.values[i] != null);
    shownCount = shown.length;
    (o.map.getSource(SOURCE) as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: shown.map((p) => ({
        type: "Feature",
        properties: { id: p.id, name: p.name, v: p.values[i] },
        geometry: { type: "Point", coordinates: p.coord },
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
    const per = data.periods;
    const i = latest();
    let prev: number | null = null;
    const rows: string[] = [];
    per.forEach((x, k) => {
      const v = p.values[k];
      if (v == null) {
        prev = null;
        return;
      }
      let change = "";
      if (prev !== null && prev > 0) {
        const r = ((v - prev) / prev) * 100;
        change = `${r >= 0.05 ? "+" : r <= -0.05 ? "−" : "±"}${formatNumber(Math.abs(r), 1)}%`;
      }
      prev = v;
      rows.push(`<tr${k === i ? ' aria-current="true"' : ""}><td>${esc(yearOnly(x.label))}</td>
        <td class="num">${formatNumber(v, 0)}円</td><td class="num">${change}</td></tr>`);
    });
    const first = p.values.findIndex((v) => v != null);
    const facts = [
      p.use_label,
      p.current_use ? `利用現況: ${p.current_use}` : "",
      p.area_m2 ? `地積 ${formatNumber(p.area_m2, 0)}㎡` : "",
      p.zoning ? `用途地域: ${p.zoning}` : "",
      p.station ? `最寄駅: ${p.station}${p.station_distance_m ? `（${formatNumber(p.station_distance_m, 0)}m）` : ""}` : "",
    ].filter(Boolean);
    const srcs = [...new Set(data.source_ids.map((sid) => o.sources.get(sid)?.attribution ?? sid))];
    o.panel.hidden = false;
    o.panel.innerHTML = `
      <button type="button" class="close" data-close aria-label="${k.name}の情報を閉じる">×</button>
      <p class="muted">${esc(o.municipalityName(p.municipality_id))}・${k.name}の${k.point}</p>
      <h2>${esc(p.name)}</h2>
      <p class="muted small">${esc(p.address ?? "")}${p.residential_address ? `（住居表示 ${esc(p.residential_address)}）` : ""}</p>
      <div>${esc(data.name)}（${esc(per[i].label)}、1㎡あたり）</div>
      <div class="value">${p.values[i] != null ? `${formatNumber(p.values[i]!, 0)}円` : "値なし"}</div>
      ${p.change_rate != null ? `<p class="small">前年から ${p.change_rate >= 0 ? "+" : "−"}${formatNumber(Math.abs(p.change_rate), 1)}%</p>` : ""}
      <p class="small">${facts.map(esc).join("・")}</p>
      ${first > 0 ? `<p class="note small">${esc(yearOnly(per[first].label))}から${k.point}です。それより前は値がありません。</p>` : ""}
      <div class="trend-scroll"><table class="trend"><caption>推移（各年${k.date}）</caption>
        <thead><tr><th>年</th><th class="num">価格（円/㎡）</th><th class="num">前年から</th></tr></thead>
        <tbody>${rows.reverse().join("")}</tbody></table></div>
      <p class="muted small">${data.caveats.map(esc).join(" ")}</p>
      <p class="muted small">${srcs.map(esc).join("／")}</p>`;
    o.onPanel();
  }

  o.panel.addEventListener("click", (e) => {
    if ((e.target as HTMLElement).closest("[data-close]")) showPoint(null);
  });

  // ?lp=<標準地ID>（地価調査は ?ls=<基準地ID>）で開いたときは表示をオンにしてその地点を選ぶ
  const initial = new URLSearchParams(location.search).get(k.param);
  if (initial) {
    o.toggle.checked = true;
    void setVisible(true).then(async () => {
      // 地点のIDは land-<市区町村コード>-…（地価調査は landsv-…）なので、都道府県が分かる
      const p = await loader.find((x) => x.id === initial, k.idPattern.exec(initial)?.[1]);
      if (!p) return;
      o.map.jumpTo({ center: p.coord, zoom: Math.max(o.map.getZoom(), 14.5, PLACES_MIN_ZOOM) });
      showPoint(initial);
    });
  }

  // ?show=land（地価調査は landsurvey）で開いたときは表示をオンにする（トップページの指標の一覧から）
  if (!initial && new URLSearchParams(location.search).get("show")?.split(",").includes(k.show)) {
    o.toggle.checked = true;
    void setVisible(true);
  }

  return {
    layer: LAYER,
    kind: k.name,
    visible: () => !!o.map.getLayer(LAYER) && o.toggle.checked,
    show: showPoint,
    isOpen: () => !o.panel.hidden,
  };
}

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
