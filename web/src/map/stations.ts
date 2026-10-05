// 駅の点レイヤー（国土数値情報 駅別乗降客数）。円の面積を最新年度の1日あたり乗降客数に対応させる
// （設計書 第6章「駅と学校: 点レイヤーとポップアップ。人数を円の面積に対応させ、集計単位を明記」）。
// 「駅を表示」をオンにしたときに初めて places/station_passengers.json を読み込み、駅の一覧は地図に映っている
// 都道府県の分だけ places/station_passengers/<都道府県>.json から読む（createPrefLoader）。
// 駅は事業者ごとに別の点。同じ駅の他の事業者の値は並べて表示し、合計しない。
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import { createPrefLoader, PLACES_MIN_ZOOM, type PointLayer } from "./points";
import { formatNumber, STATUS_LABEL } from "../lib/format";
import type { Source, StationsFile, Station } from "../lib/types";

const LAYER = "station-circle";
const SELECTED = "station-selected";
const LABEL = "station-label";
const MAX_LABEL_OPERATORS = 3; // ラベルに並べる事業者の数（多い駅は「ほかN社」）
const MISSING_TEXT: Record<string, string> = {
  not_applicable: "別の路線に含めて公表",
  suppressed: "非公開",
  missing: "値なし",
};

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

export type StationLayer = PointLayer;

export function initStations(o: Options): StationLayer {
  let data: StationsFile | null = null;
  let stations: Station[] = [];
  let byId = new Map<string, Station>();
  const latest = () => (data ? data.periods.length - 1 : 0);
  const loader = createPrefLoader<Station>({
    map: o.map, fetchJSON: o.fetchJSON, id: "station_passengers", key: "stations",
    active: () => o.toggle.checked,
    onChange: (items) => render(items),
  });

  async function load(): Promise<boolean> {
    if (data) return true;
    try {
      data = await o.fetchJSON<StationsFile>("places/station_passengers.json");
    } catch {
      o.legend.hidden = false;
      o.legend.textContent = "この公開版には駅のデータがありません。";
      return false;
    }
    loader.init(data);
    const empty = { type: "FeatureCollection", features: [] } as never;
    o.map.addSource("stations", { type: "geojson", data: empty });
    const v = ["get", "v"];
    const size = (k: number, min: number) => ["case", ["<", v, 0], min, ["max", min, ["*", ["sqrt", v], k]]];
    o.map.addLayer({
      id: LAYER, type: "circle", source: "stations",
      layout: { "circle-sort-key": ["-", 0, v] as never },
      paint: {
        // 面積が人数に比例するよう半径は平方根。拡大するほど大きく描く
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, size(0.006, 1.5), 12, size(0.016, 2.5), 15, size(0.04, 4)] as never,
        // 塗り分けの色（青・赤など）と区別できるよう、円は濃い灰色の半透明にする
        "circle-color": ["case", ["<", v, 0], "#ffffff", "#262626"] as never,
        "circle-opacity": ["case", ["<", v, 0], 0.9, 0.42] as never,
        "circle-stroke-color": ["case", ["<", v, 0], "#555555", "#ffffff"] as never,
        "circle-stroke-width": 1.2,
      },
    }, o.beforeLayer);
    o.map.addLayer({
      id: SELECTED, type: "circle", source: "stations", filter: ["==", ["get", "id"], ""],
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, size(0.006, 1.5), 12, size(0.016, 2.5), 15, size(0.04, 4)] as never,
        "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#d00", "circle-stroke-width": 3,
      },
    }, o.beforeLayer);
    o.map.addSource("station-labels", { type: "geojson", data: empty });
    o.map.addLayer({
      id: LABEL, type: "symbol", source: "station-labels", minzoom: 13.5,
      layout: {
        "text-field": ["format", ["get", "name"], {}, "\n", {}, ["get", "count"], { "font-scale": 0.85 }] as never,
        "text-font": o.labelFont,
        "text-size": 11, "text-offset": [0, 1.1], "text-anchor": "top",
        "symbol-sort-key": ["-", 0, v] as never, "text-padding": 4,
      },
      // 町丁目名（黒）と混ざらないよう、駅は紺の文字にする
      paint: { "text-color": "#163f7f", "text-halo-color": "rgba(255,255,255,0.95)", "text-halo-width": 1.6 },
    });
    o.map.on("mouseenter", LAYER, () => (o.map.getCanvas().style.cursor = "pointer"));
    o.map.on("mouseleave", LAYER, () => (o.map.getCanvas().style.cursor = ""));
    o.map.on("zoomend", updateLegend);
    if (data.stations) render(data.stations);   // 古い公開版（1ファイルに全件）
    updateLegend();
    return true;
  }

  function updateLegend() {
    if (!data) return;
    o.legend.innerHTML = `円の面積は${esc(data.periods[latest()].label)}の1日あたり乗降客数（事業者ごと）。` +
      `白い円は値がない駅。` + (loader.tooFar() ? "駅は地図を拡大すると表示します。" : "");
  }

  /** 読み込んだ駅（都道府県の分が増えるたびに全体）を地図に描き直す */
  function render(items: Station[]) {
    stations = items;
    byId = new Map(items.map((s) => [s.id, s]));
    const i = latest();
    // 最新年度に駅がない（廃止された）駅は描かない
    const live = items.filter((s) => s.status[i] !== null);
    (o.map.getSource("stations") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: live.map((s) => ({
        type: "Feature",
        properties: { id: s.id, name: s.name, v: s.values[i] ?? -1 },
        geometry: { type: "Point", coordinates: s.coord },
      })),
    } as never);
    // 駅名と乗降客数は拡大したときだけ。同じ駅（グループ）には1つのラベルにまとめ、
    // 事業者が複数あるときは事業者ごとの人数を並べる（乗り換え客が重複するので合計しない）
    const groups = new Map<string, Station[]>();
    for (const st of live) groups.set(st.group, [...(groups.get(st.group) ?? []), st]);
    const people = (st: Station) => (st.values[i] != null ? `${formatNumber(st.values[i]!, 0)}人` : "値なし");
    (o.map.getSource("station-labels") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: [...groups.values()].map((list) => {
        list.sort((a, b) => (b.values[i] ?? -1) - (a.values[i] ?? -1));
        const top = list[0];
        const shown = list.slice(0, MAX_LABEL_OPERATORS);
        const rest = list.length - shown.length;
        const counts = list.length === 1 ? people(top)
          : shown.map((st) => `${st.operator} ${people(st)}`).join("\n") + (rest > 0 ? `\nほか${rest}社` : "");
        return {
          type: "Feature", properties: { name: `${top.name}駅`, count: counts, v: top.values[i] ?? -1 },
          geometry: { type: "Point", coordinates: top.coord },
        };
      }),
    } as never);
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
    if (!on) showStation(null);
    else void loader.refresh();
  }
  o.toggle.addEventListener("change", () => void setVisible(o.toggle.checked));

  const valueText = (s: Station, i: number) => {
    const v = s.values[i];
    if (v !== null && v !== undefined) return `${formatNumber(v, 0)}人`;
    return MISSING_TEXT[s.status[i] ?? ""] ?? "駅なし";
  };

  /** 駅を選んだときの処理（クリック・一覧から）。表示は右の欄の駅の情報にまとめる */
  function showStation(id: string | null) {
    if (o.map.getLayer(SELECTED)) o.map.setFilter(SELECTED, ["==", ["get", "id"], id ?? ""]);
    const s = id ? byId.get(id) : undefined;
    if (!s || !data) {
      o.panel.hidden = true;
      o.panel.innerHTML = "";
      o.onPanel();
      return;
    }
    const i = latest();
    const p = data.periods;
    const note = s.notes?.[String(i)];
    let prev: number | null = null;
    const trend = p.map((per, k) => {
      const v = s.values[k];
      let change = "";
      if (v !== null && prev !== null && prev > 0) {
        const r = ((v - prev) / prev) * 100;
        change = `${r >= 0.05 ? "+" : r <= -0.05 ? "−" : "±"}${formatNumber(Math.abs(r), 1)}%`;
      }
      if (v !== null) prev = v;
      if (s.status[k] === null && v === null) return "";
      return `<tr${k === i ? ' aria-current="true"' : ""}><td>${esc(per.label)}</td>
        <td class="num">${esc(valueText(s, k))}</td><td class="num">${change}</td></tr>`;
    }).join("");
    // 路線別の内訳は、最新年度に2路線以上の値があるときだけ
    const byLine = Object.entries(s.by_line ?? {}).filter(([, vals]) => vals[i] != null);
    const lines = byLine.length > 1
      ? `<p class="small">路線別（${esc(p[i].label)}）: ${byLine
          .map(([name, vals]) => `${esc(name)} ${formatNumber(vals[i]!, 0)}人`).join("、")}</p>`
      : "";
    // 同じ駅（300m以内の同名駅）の他の事業者。乗り換え客が重複するので合計しない
    const others = stations.filter((x) => x.group === s.group && x.id !== s.id);
    const otherHtml = others.length
      ? `<div class="compare-with"><p class="small">同じ駅の他の事業者（${esc(p[i].label)}、合計はしていません）</p>
         <ul class="small">${others.map((x) => `<li><a href="#" data-station="${esc(x.id)}">${esc(x.operator)}</a>
         <strong>${esc(valueText(x, i))}</strong></li>`).join("")}</ul></div>`
      : "";
    const srcs = [...new Set(data.source_ids.map((id) => o.sources.get(id)?.attribution ?? id))];
    o.panel.hidden = false;
    o.panel.innerHTML = `
      <button type="button" class="close" data-close aria-label="駅の情報を閉じる">×</button>
      <p class="muted">${esc(o.municipalityName(s.municipality_id))}・${esc(s.operator)}</p>
      <h2>${esc(s.name)}駅</h2>
      <p class="muted small">${s.lines.map(esc).join("・")}</p>
      <div>${esc(data.name)}（${esc(p[i].label)}）</div>
      <div class="value">${esc(valueText(s, i))}</div>
      ${s.values[i] != null && s.status[i] && STATUS_LABEL[s.status[i]!] ? `<div class="muted">${esc(STATUS_LABEL[s.status[i]!])}</div>` : ""}
      ${note ? `<p class="note small">${esc(note)}</p>` : ""}
      ${lines}
      ${otherHtml}
      <table class="trend"><caption>推移</caption>
        <thead><tr><th>年度</th><th class="num">乗降客数</th><th class="num">前年度から</th></tr></thead>
        <tbody>${trend}</tbody></table>
      <p class="muted small">${data.caveats.map(esc).join(" ")}</p>
      <p class="muted small">${srcs.map(esc).join("／")}</p>`;
    o.onPanel();
  }

  o.panel.addEventListener("click", (e) => {
    const t = e.target as HTMLElement;
    if (t.closest("[data-close]")) return showStation(null);
    const a = t.closest<HTMLAnchorElement>("a[data-station]");
    if (a) {
      e.preventDefault();
      showStation(a.dataset.station!);
    }
  });

  // ?s=<駅ID> で開いたときは駅を表示してその駅を選ぶ
  const initial = new URLSearchParams(location.search).get("s");
  if (initial) {
    o.toggle.checked = true;
    void setVisible(true).then(async () => {
      const s = await loader.find((x) => x.id === initial);
      if (!s) return;
      o.map.jumpTo({ center: s.coord, zoom: Math.max(o.map.getZoom(), 14, PLACES_MIN_ZOOM) });
      showStation(initial);
    });
  }

  // ?show=stations で開いたときは表示をオンにする（トップページの指標の一覧から）
  if (!initial && new URLSearchParams(location.search).get("show")?.split(",").includes("stations")) {
    o.toggle.checked = true;
    void setVisible(true);
  }

  return {
    layer: LAYER,
    kind: "駅",
    visible: () => !!o.map.getLayer(LAYER) && o.toggle.checked,
    show: showStation,
    isOpen: () => !o.panel.hidden,
  };
}

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
