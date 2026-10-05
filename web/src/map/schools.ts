// 公立小中学校の点レイヤー（東京都教育委員会「東京都公立学校一覧」）。円の面積を最新年度の児童・生徒数に対応させる
// （設計書 第6章「駅と学校: 点レイヤーとポップアップ。人数を円の面積に対応させ、集計単位を明記」）。
// 「公立小中学校を表示」をオンにしたときに初めて places/school_enrollment.json を読み込み、学校の一覧は地図に映っている
// 都道府県の分だけ読む（createPrefLoader）。東京都以外は児童・生徒数の公開データがなく、国土数値情報の位置だけを小さな点で出す。
// 学校に通う子どもの数で、周辺に住む子どもの数ではないことを凡例と詳細に明記する。
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import { createPrefLoader, PLACES_MIN_ZOOM, type PointLayer } from "./points";
import { formatNumber } from "../lib/format";
import type { Source, SchoolsFile, School } from "../lib/types";

const LAYER = "school-circle";
const SELECTED = "school-selected";
const LABEL = "school-label";
// 塗り分け（青・緑・赤など）の上でも見分けられるよう、濃い橙と濃い紫にする
const COLOR = { elementary: "#d95f02", junior_high: "#5e3c99", compulsory: "#5e3c99" } as const;
// 文字は円より濃くして読みやすくする
const LABEL_COLOR = { elementary: "#9a3f00", junior_high: "#46287a" } as const;

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

export type SchoolLayer = PointLayer;

export function initSchools(o: Options): SchoolLayer {
  let data: SchoolsFile | null = null;
  let byId = new Map<string, School>();
  let unlocated = 0;
  const latest = () => (data ? data.periods.length - 1 : 0);
  const loader = createPrefLoader<School>({
    map: o.map, fetchJSON: o.fetchJSON, id: "school_enrollment", key: "schools",
    active: () => o.toggle.checked,
    onChange: (items) => render(items),
  });
  // 最新年度の一覧にない（閉校した）学校は描かない。位置だけの学校（東京都以外）は値がなくても描く
  const current = (s: School) => s.location_only || s.status[latest()] !== null;

  async function load(): Promise<boolean> {
    if (data) return true;
    try {
      data = await o.fetchJSON<SchoolsFile>("places/school_enrollment.json");
    } catch {
      o.legend.hidden = false;
      o.legend.textContent = "この公開版には学校のデータがありません。";
      return false;
    }
    loader.init(data);
    o.map.addSource("schools", { type: "geojson", data: { type: "FeatureCollection", features: [] } as never });
    const v = ["get", "v"];
    const size = (k: number, min: number) => ["case", ["<", v, 0], min, ["max", min, ["*", ["sqrt", v], k]]];
    const radius = ["interpolate", ["linear"], ["zoom"], 9, size(0.05, 1.5), 12, size(0.16, 2.5), 15, size(0.48, 4)];
    const color = ["match", ["get", "t"], "elementary", COLOR.elementary, COLOR.junior_high];
    o.map.addLayer({
      id: LAYER, type: "circle", source: "schools",
      layout: { "circle-sort-key": ["-", 0, v] as never },
      paint: {
        // 面積が人数に比例するよう半径は平方根
        "circle-radius": radius as never,
        "circle-color": color as never,
        "circle-opacity": 0.75,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 1.5,
      },
    }, o.beforeLayer);
    o.map.addLayer({
      id: SELECTED, type: "circle", source: "schools", filter: ["==", ["get", "id"], ""],
      paint: { "circle-radius": radius as never, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#d00", "circle-stroke-width": 3 },
    }, o.beforeLayer);
    // 学校名と児童・生徒数。町丁目名（黒）と混ざらないよう、円と同じ系統の色（小=橙・中=紫）の文字にする
    o.map.addLayer({
      id: LABEL, type: "symbol", source: "schools", minzoom: 14,
      layout: {
        "text-field": ["format", ["get", "name"], {}, "\n", {},
          ["get", "n"], { "font-scale": 0.9 }] as never,
        "text-font": o.labelFont,
        "text-size": 10.5, "text-offset": [0, 1], "text-anchor": "top", "text-padding": 4,
        "symbol-sort-key": ["-", 0, v] as never,
      },
      paint: {
        "text-color": ["match", ["get", "t"], "elementary", LABEL_COLOR.elementary, LABEL_COLOR.junior_high] as never,
        "text-halo-color": "rgba(255,255,255,0.95)", "text-halo-width": 1.6,
      },
    });
    o.map.on("mouseenter", LAYER, () => (o.map.getCanvas().style.cursor = "pointer"));
    o.map.on("mouseleave", LAYER, () => (o.map.getCanvas().style.cursor = ""));
    o.map.on("moveend", updateLegend);
    if (data.schools) render(data.schools);   // 古い公開版（1ファイルに全件）
    updateLegend();
    return true;
  }

  function updateLegend() {
    if (!data) return;
    const only = loader.locationOnlyInView().length > 0;
    o.legend.innerHTML =
      `円の面積は${esc(data.periods[latest()].label)}の児童・生徒数（学校に通う人数）。` +
      `<span style="color:${COLOR.elementary}">●</span>小学校 <span style="color:${COLOR.junior_high}">●</span>中学校・義務教育学校。` +
      (unlocated ? `住所から位置を求められなかった${unlocated}校は表示していません。` : "") +
      (only ? "児童・生徒数は東京都だけです。ほかの道府県は学校の位置だけを小さな点で表示しています。" : "") +
      (loader.tooFar() ? "学校は地図を拡大すると表示します。" : "");
  }

  /** 読み込んだ学校（都道府県の分が増えるたびに全体）を地図に描き直す */
  function render(items: School[]) {
    byId = new Map(items.map((s) => [s.id, s]));
    const i = latest();
    // 位置を求められなかった学校は描かない
    const shown = items.filter((s) => s.coord && current(s));
    unlocated = items.filter((s) => !s.coord && current(s)).length;
    (o.map.getSource("schools") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: shown.map((s) => ({
        type: "Feature",
        properties: {
          id: s.id, name: s.name, t: s.school_type, v: s.values[i] ?? -1,
          n: s.values[i] != null ? `${formatNumber(s.values[i]!, 0)}人` : "",
        },
        geometry: { type: "Point", coordinates: s.coord },
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
    if (!on) showSchool(null);
    else void loader.refresh();
  }
  o.toggle.addEventListener("change", () => void setVisible(o.toggle.checked));

  const valueText = (s: School, i: number) => {
    const v = s.values[i];
    return v !== null && v !== undefined ? `${formatNumber(v, 0)}人` : "一覧になし";
  };

  function showSchool(id: string | null) {
    if (o.map.getLayer(SELECTED)) o.map.setFilter(SELECTED, ["==", ["get", "id"], id ?? ""]);
    const s = id ? byId.get(id) : undefined;
    if (!s || !data) {
      o.panel.hidden = true;
      o.panel.innerHTML = "";
      o.onPanel();
      return;
    }
    const p = data.periods;
    if (s.location_only) return showLocationOnly(s);
    // 最新年度に一覧にない学校は、最後に載っていた年度を表示する
    let i = latest();
    while (i > 0 && s.values[i] == null) i--;
    let prev: number | null = null;
    const trend = p.map((per, k) => {
      const v = s.values[k];
      let change = "";
      if (v !== null && prev !== null && prev > 0) {
        const r = ((v - prev) / prev) * 100;
        change = `${r >= 0.05 ? "+" : r <= -0.05 ? "−" : "±"}${formatNumber(Math.abs(r), 1)}%`;
      }
      if (v !== null) prev = v;
      if (v === null) return "";
      return `<tr${k === i ? ' aria-current="true"' : ""}><td>${esc(per.label.replace("現在", ""))}</td>
        <td class="num">${esc(valueText(s, k))}</td><td class="num">${change}</td></tr>`;
    }).join("");
    const grades = Object.entries(s.by_grade ?? {}).filter(([, vals]) => vals[i] != null);
    const gradeHtml = grades.length
      ? `<p class="small">学年別: ${grades.map(([g, vals]) => `${esc(g)} ${formatNumber(vals[i]!, 0)}人`).join("、")}</p>`
      : "";
    const where = !s.coord
      ? "住所から位置を求められなかったため、地図には表示していません。"
      : s.precision === "町丁目"
        ? "住所の街区が見つからないため、町丁目の代表点に表示しています。"
        : "";
    const srcs = [...new Set(data.source_ids.map((id) => o.sources.get(id)?.attribution ?? id))];
    o.panel.hidden = false;
    o.panel.innerHTML = `
      <button type="button" class="close" data-close aria-label="学校の情報を閉じる">×</button>
      <p class="muted">${esc(o.municipalityName(s.municipality_id))}・${esc(founderText(s))}</p>
      <h2>${esc(s.name)}</h2>
      <p class="muted small">${esc(s.type_label)}${s.address ? `・${esc(s.address)}` : ""}</p>
      <div>${esc(data.name)}（${esc(p[i].label)}）</div>
      <div class="value">${esc(valueText(s, i))}</div>
      ${i !== latest() ? `<p class="note small">${esc(p[latest()].label)}の一覧には載っていません（閉校・統合など）。</p>` : ""}
      ${gradeHtml}
      ${where ? `<p class="note small">${esc(where)}</p>` : ""}
      <table class="trend"><caption>推移</caption>
        <thead><tr><th>時点</th><th class="num">児童・生徒数</th><th class="num">前年から</th></tr></thead>
        <tbody>${trend}</tbody></table>
      <p class="muted small">${data.caveats.map(esc).join(" ")}</p>
      <p class="muted small">${srcs.map(esc).join("／")}</p>`;
    o.onPanel();
  }

  /** 東京都以外の学校（国土数値情報の位置だけ。児童・生徒数の公開データがない） */
  function showLocationOnly(s: School) {
    const srcs = [...new Set(data!.source_ids.map((id) => o.sources.get(id)?.attribution ?? id))];
    o.panel.hidden = false;
    o.panel.innerHTML = `
      <button type="button" class="close" data-close aria-label="学校の情報を閉じる">×</button>
      <p class="muted">${esc(o.municipalityName(s.municipality_id))}・${esc(founderText(s))}</p>
      <h2>${esc(s.name)}</h2>
      <p class="muted small">${esc(s.type_label)}${s.address ? `・${esc(s.address)}` : ""}</p>
      <div>${esc(data!.name)}</div>
      <div class="value">公開データなし</div>
      <p class="note small">児童・生徒数は東京都の学校だけです。ほかの道府県は、国土数値情報「学校データ」（${esc(s.as_of ?? "")}）の学校の位置だけを表示しています。</p>
      <p class="muted small">${srcs.map(esc).join("／")}</p>`;
    o.onPanel();
  }

  o.panel.addEventListener("click", (e) => {
    if ((e.target as HTMLElement).closest("[data-close]")) showSchool(null);
  });

  // ?sc=<学校ID> で開いたときは学校を表示してその学校を選ぶ
  const initial = new URLSearchParams(location.search).get("sc");
  if (initial) {
    o.toggle.checked = true;
    void setVisible(true).then(async () => {
      // 国土数値情報の学校コード（例: B113210200138）は3〜4文字目が都道府県。都教委の学校番号は東京都
      const s = await loader.find((x) => x.id === initial, /^school-[A-Z]\d(\d\d)/.exec(initial)?.[1] ?? "13");
      if (!s) return;
      if (s.coord) o.map.jumpTo({ center: s.coord, zoom: Math.max(o.map.getZoom(), 14.5, PLACES_MIN_ZOOM) });
      showSchool(initial);
    });
  }

  // ?show=schools で開いたときは表示をオンにする（トップページの指標の一覧から）
  if (!initial && new URLSearchParams(location.search).get("show")?.split(",").includes("schools")) {
    o.toggle.checked = true;
    void setVisible(true);
  }

  return {
    layer: LAYER,
    kind: "学校",
    visible: () => !!o.map.getLayer(LAYER) && o.toggle.checked,
    show: showSchool,
    isOpen: () => !o.panel.hidden,
  };
}

/** 設置者（東京都は「千代田区」など → 「千代田区立」。国土数値情報は「市区町村立」「都道府県立」） */
function founderText(s: School): string {
  return s.founder.endsWith("立") ? s.founder : `${s.founder}立`;
}

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
