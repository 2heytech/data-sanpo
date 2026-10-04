// 地図画面（/map/）のブラウザ側の処理。
// 読み込み順: 指標カタログ・市区町村境界 → 拡大時に町丁目境界 → 指標・時点を切り替えたら必要な値だけ
// （設計書 第9章「読み込みの順序」）。指標切替では地図を作り直さず feature-state と色だけ更新する。
import type * as MapLibre from "maplibre-gl";
import type { GeoJSONSource, LngLatBoundsLike, PointLike } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { colorsFor, fillColorExpression, NO_DATA_COLOR } from "../lib/classify";
import { formatFraction, formatNumber, formatValue, rankOf, STATUS_LABEL } from "../lib/format";
import { AreaSearch, type SearchHit } from "../lib/search";
import { countIndicatorUse, type UsageHow } from "../lib/usage";
import type {
  AreasFile, Indicator, IndicatorCatalog, Level, LegendFile, Municipality, SearchIndex,
  SmallArea, SmallAreasFile, Source, ValueRow, ValuesFile,
} from "../lib/types";
import { municipalityCodeOf, parseState, prefectureCodeOf, serializeState } from "../lib/urlstate";
import { initStations } from "./stations";
import { initSchools } from "./schools";
import { initLandPrices } from "./landprices";
import { initNurseries } from "./nurseries";
import type { PointLayer } from "./points";

// 縮尺に合わせて、都道府県 → 市区町村 → 町丁目の値に切り替える（#52）
// 切り替えは、次の段階の地名がある程度読める縮尺まで待つ（市区町村名は MUNI_LABEL_ZOOM、町丁目名は AREA_LABEL_ZOOM から）
const PREF_ZOOM = 8; // これ未満では都道府県の値で色分けする（全国のデータのとき）
const AREA_ZOOM = 13; // これ以上で町丁目を表示
const FINE_MUNI_ZOOM = 8; // これ以上で市区町村界を都道府県ごとの細かい形に差し替える（初回は全国の粗い形）
const MAX_PREFS_PER_MOVE = 6;
const MAX_CHUNKS_PER_MOVE = 8;
// 地名の文字。漢字・かなは端末のフォントで描き、数字などだけ地理院のフォントを読み込む
const GLYPHS_URL = "https://maps.gsi.go.jp/xyz/noto-jp/{fontstack}/{range}.pbf";
const LABEL_FONT = ["NotoSansJP-Regular"];
const LOCAL_FONT = '"Hiragino Sans", "Noto Sans JP", "Yu Gothic UI", "Meiryo", sans-serif';
const AREA_LABEL_ZOOM = AREA_ZOOM; // 町丁目名はこれ以上で表示（狭い範囲に多数あるため）
const MUNI_LABEL_ZOOM = PREF_ZOOM; // 市区町村名はこれ以上で表示
const PLAY_INTERVAL_MS = 1600;
const MUNI_OPACITY = 0.72;
const AREA_OPACITY = 0.68;
const GSI_ATTRIBUTION =
  '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noopener">地理院タイル</a>';

const PRESETS: Record<string, LngLatBoundsLike> = {
  japan: [128.0, 30.0, 146.0, 45.6],
  okinawa: [122.9, 24.0, 131.4, 27.9],
  mainland: [138.94, 35.48, 139.93, 35.9],
  izu: [139.1, 32.4, 140.0, 34.85],
  ogasawara: [141.1, 26.5, 142.35, 27.8],
};

interface FeatureCollection {
  type: "FeatureCollection";
  features: { type: "Feature"; properties: { id: string; name: string; value?: string }; geometry: unknown }[];
}

const shortLabel = (label: string) => label.replace(/(\d+年).*/, "$1");

const pointFeatures = (items: { id: string; name: string; center: [number, number] }[],
                       values?: Map<string, string>): FeatureCollection => ({
  type: "FeatureCollection",
  features: items.map((a) => ({
    type: "Feature", properties: { id: a.id, name: a.name, value: values?.get(a.id) ?? "" },
    geometry: { type: "Point", coordinates: a.center },
  })),
});

export async function initMapApp(root: HTMLElement, base: string, maplibreUrl: string): Promise<void> {
  // MapLibre は public/vendor から読み込む（Worker を同じ場所から読み込ませるため）
  const maplibregl = (await import(/* @vite-ignore */ maplibreUrl)) as typeof MapLibre;
  const cache = new Map<string, Promise<unknown>>();
  const fetchJSON = <T>(rel: string): Promise<T> => {
    if (!cache.has(rel)) {
      cache.set(rel, fetch(`${base}/${rel}`).then((r) => {
        if (!r.ok) throw new Error(`${rel}: ${r.status}`);
        return r.json();
      }));
    }
    return cache.get(rel) as Promise<T>;
  };

  const $ = <T extends HTMLElement>(sel: string) => root.querySelector<T>(sel)!;
  const indicatorSelect = $<HTMLSelectElement>("#indicator-select");
  const periodRange = $<HTMLInputElement>("#period-range");
  const periodLabel = $<HTMLOutputElement>("#period-label");
  const periodTicks = $("#period-ticks");
  const periodNote = $("#period-note");
  const playButton = $<HTMLButtonElement>("#period-play");
  const legendEl = $("#legend");
  const facetsEl = $("#facets");
  const facetType = $<HTMLSelectElement>("#facet-type");
  const facetBasis = $<HTMLSelectElement>("#facet-basis");
  const aggregateWrap = $("#aggregate-wrap");
  const aggregateToggle = $<HTMLInputElement>("#aggregate-toggle");
  const aggregateLabel = $("#aggregate-label");
  const periodField = periodRange.closest<HTMLElement>(".period")!;
  const colorsToggle = $<HTMLInputElement>("#colors-toggle");
  const detailEl = $("#detail");
  const listEl = $("#list");

  const [catalog, areas, sourcesFile] = await Promise.all([
    fetchJSON<IndicatorCatalog>("indicators.json"),
    fetchJSON<AreasFile>("areas.json"),
    fetchJSON<{ sources: Source[] }>("sources.json"),
  ]);
  const indicators = catalog.indicators;
  const sources = new Map(sourcesFile.sources.map((s) => [s.source_id, s]));
  const munis = new Map(areas.municipalities.map((m) => [m.id, m]));
  const prefectures = new Map(areas.prefectures.map((p) => [p.code, p]));
  const prefName = (code: string | null | undefined) => (code && prefectures.get(code)?.name) || "";
  const isPref = (id: string) => id.startsWith("pref-");
  // 都道府県の色分けは、複数の都道府県があるとき（全国の公開版）だけ使う
  const nationwide = areas.prefectures.length > 1;
  // 値のファイル: 都道府県・市区町村は全国で1つずつ、町丁・字等は都道府県ごと
  const chunkOf = (id: string) =>
    (isPref(id) ? "prefectures" : munis.has(id) ? "municipalities" : prefectureCodeOf(id)!);
  const smallAreas = new Map<string, SmallArea>();
  const loadedChunks = new Set<string>();
  const loadingChunks = new Map<string, Promise<void>>();
  const areaFeatures: FeatureCollection = { type: "FeatureCollection", features: [] };

  const initial = parseState(location.search);
  let indicator: Indicator = indicators.find((i) => i.id === initial.indicator) ?? indicators[0];
  let period = indicator.periods.find((p) => p.period === initial.period)?.period ?? indicator.default_period;
  let selected: string | null = null;

  // --- 地図 ---------------------------------------------------------------------
  const map = new maplibregl.Map({
    container: $("#map"),
    localIdeographFontFamily: LOCAL_FONT,
    style: {
      version: 8,
      glyphs: GLYPHS_URL,
      sources: {
        pale: {
          type: "raster", tileSize: 256, maxzoom: 18, attribution: GSI_ATTRIBUTION,
          tiles: ["https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png"],
        },
        photo: {
          type: "raster", tileSize: 256, maxzoom: 18, attribution: GSI_ATTRIBUTION,
          tiles: ["https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg"],
        },
      },
      layers: [
        { id: "pale", type: "raster", source: "pale" },
        { id: "photo", type: "raster", source: "photo", layout: { visibility: "none" } },
      ],
    },
    // 全国のデータがあるときは日本全体、東京都だけのとき（プレビュー用の公開版など）は区部・多摩
    bounds: areas.prefectures.length > 1 ? PRESETS.japan : PRESETS.mainland,
    maxZoom: 17,
    attributionControl: { compact: false },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
  map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
  await new Promise<void>((resolve) => map.once("load", () => resolve()));

  const muniBoundaries = await fetchJSON<FeatureCollection>(
    `boundaries/${areas.boundary_version}/municipalities.geojson`,
  );
  map.addSource("munis", { type: "geojson", data: muniBoundaries as never, promoteId: "id" });
  // 市区町村界は全国の粗い形で始め、拡大したら表示範囲の都道府県の細かい形に差し替える
  const muniFeatures = new Map(muniBoundaries.features.map((f) => [f.properties.id, f]));
  map.addSource("areas", { type: "geojson", data: areaFeatures as never, promoteId: "id" });
  // 都道府県界: 縮小したときに都道府県の値で色分けする（市区町村の形を合わせたもの）
  const prefBoundaries = nationwide
    ? await fetchJSON<FeatureCollection>(`boundaries/${areas.boundary_version}/prefectures.geojson`).catch(() => null)
    : null;
  map.addSource("prefs", {
    type: "geojson", promoteId: "id",
    data: (prefBoundaries ?? { type: "FeatureCollection", features: [] }) as never,
  });
  map.addLayer({
    id: "muni-fill", type: "fill", source: "munis", maxzoom: AREA_ZOOM,
    paint: { "fill-color": NO_DATA_COLOR, "fill-opacity": MUNI_OPACITY },
  });
  map.addLayer({
    id: "pref-fill", type: "fill", source: "prefs", maxzoom: PREF_ZOOM,
    paint: { "fill-color": NO_DATA_COLOR, "fill-opacity": MUNI_OPACITY },
  });
  map.addLayer({
    id: "area-fill", type: "fill", source: "areas", minzoom: AREA_ZOOM,
    paint: { "fill-color": NO_DATA_COLOR, "fill-opacity": AREA_OPACITY },
  });
  map.addLayer({
    id: "area-line", type: "line", source: "areas", minzoom: AREA_ZOOM,
    paint: { "line-color": "#ffffff", "line-width": 0.6 },
  });
  map.addLayer({
    id: "muni-line", type: "line", source: "munis",
    paint: { "line-color": "#4a4a4a", "line-width": ["interpolate", ["linear"], ["zoom"], 9, 0.6, 13, 2] },
  });
  map.addLayer({
    id: "pref-line", type: "line", source: "prefs",
    paint: { "line-color": "#333", "line-width": ["interpolate", ["linear"], ["zoom"], 4, 0.8, 9, 1.6, 13, 2.6] },
  });
  for (const src of ["prefs", "munis", "areas"]) {
    map.addLayer({
      id: `${src}-selected`, type: "line", source: src, filter: ["==", ["get", "id"], ""],
      paint: { "line-color": "#d00", "line-width": 3 },
    });
  }

  // 地名: 市区町村名は常に、町丁目名は拡大したときに表示する（位置は地域の内側の代表点）
  map.addSource("pref-labels", { type: "geojson", data: pointFeatures(nationwide ? areas.prefectures : []) as never });
  map.addSource("muni-labels", { type: "geojson", data: pointFeatures(areas.municipalities) as never });
  map.addSource("area-labels", { type: "geojson", data: pointFeatures([]) as never });
  // 地名の下に、表示中の指標の値を小さく添える（値がない地域は地名だけ）
  const labelValues = new Map<string, string>();
  const nameOnly = ["get", "name"];
  const nameWithValue = ["format", ["get", "name"], {},
    ["case", ["==", ["get", "value"], ""], "", ["concat", "\n", ["get", "value"]]], { "font-scale": 0.9 }];
  const valuesToggle = $<HTMLInputElement>("#values-toggle");
  const labelText = () => (valuesToggle.checked ? nameWithValue : nameOnly);
  const labelPaint = { "text-color": "#1f2328", "text-halo-color": "rgba(255,255,255,0.92)", "text-halo-width": 1.6 };
  map.addLayer({
    id: "area-label", type: "symbol", source: "area-labels", minzoom: AREA_LABEL_ZOOM,
    layout: {
      "text-field": labelText() as never, "text-font": LABEL_FONT,
      "text-size": ["interpolate", ["linear"], ["zoom"], AREA_LABEL_ZOOM, 10, 16, 13],
      "text-max-width": 6, "text-padding": 1,
    },
    paint: labelPaint,
  });
  map.addLayer({
    id: "pref-label", type: "symbol", source: "pref-labels", maxzoom: PREF_ZOOM,
    layout: { "text-field": labelText() as never, "text-font": LABEL_FONT, "text-size": 12, "text-padding": 2 },
    paint: { ...labelPaint, "text-halo-width": 2 },
  });
  map.addLayer({
    id: "muni-label", type: "symbol", source: "muni-labels", minzoom: MUNI_LABEL_ZOOM,
    layout: {
      "text-field": labelText() as never, "text-font": LABEL_FONT,
      "text-size": ["interpolate", ["linear"], ["zoom"], 9, 11, 12, 15, 15, 17],
      "text-padding": 2,
    },
    paint: { ...labelPaint, "text-halo-width": 2,
             "text-opacity": ["interpolate", ["linear"], ["zoom"], AREA_LABEL_ZOOM, 1, AREA_LABEL_ZOOM + 1, 0.55] },
  });

  // 市区町村だけの指標（昼間人口など）は、拡大しても市区町村の色分けのまま表示する
  const municipalityOnly = () => !periodInfo().levels.includes("small_area");
  // 都道府県の値がない指標（合計できない指標など）は、縮小しても市区町村の色分けのまま
  const prefLevel = () => nationwide && periodInfo().levels.includes("prefecture");
  // 都道府県だけの指標（学力テストなど）は、拡大しても都道府県の色分けのまま表示する
  const prefectureOnly = () => prefLevel() && !periodInfo().levels.includes("municipality");
  const levelNow = (): Level => {
    const z = map.getZoom();
    if (prefLevel() && (z < PREF_ZOOM || prefectureOnly())) return "prefecture";
    return z >= AREA_ZOOM && !municipalityOnly() ? "small_area" : "municipality";
  };
  const LEVEL_LABEL: Record<Level, string> = { prefecture: "都道府県", municipality: "市区町村", small_area: "町丁・字等" };

  // --- 値の読み込みと色分け ---------------------------------------------------------
  const valuesPath = (chunk: string) => `values/${indicator.id}/${period}/${chunk}.json`;
  const periodInfo = () => indicator.periods.find((p) => p.period === period)!;
  // 年ごとの時点（スライドバーに並べる）と、複数年の合計（「直近5年の合計」のチェックで選ぶ）
  const annualPeriods = () => indicator.periods.filter((p) => !p.aggregate);
  const aggregatePeriod = () => indicator.periods.find((p) => p.aggregate);

  // 東京都だけの指標（都の機関のデータ）など、値のない都道府県のファイルは読みにいかない
  const covers = (code: string | null) => !code || !indicator.prefectures || indicator.prefectures.includes(code);
  async function loadValues(chunk: string): Promise<ValuesFile | null> {
    if (chunk !== "municipalities" && chunk !== "prefectures" && !covers(chunk)) return null;
    try {
      return await fetchJSON<ValuesFile>(valuesPath(chunk));
    } catch {
      return null; // この時点・粒度の値がない
    }
  }

  function applyRows(source: "prefs" | "munis" | "areas", ids: Iterable<string>, rows: ValueRow[] | undefined) {
    const byId = new Map((rows ?? []).map((r) => [r.entity_id, r]));
    for (const id of ids) {
      const r = byId.get(id);
      map.setFeatureState({ source, id }, { v: r?.value ?? null, s: r?.status ?? "missing" });
      labelValues.set(id, r && r.value !== null ? formatValue(r, indicator) : "");
    }
  }

  function refreshLabels(source: "prefs" | "munis" | "areas") {
    if (source === "prefs") {
      (map.getSource("pref-labels") as GeoJSONSource).setData(pointFeatures(areas.prefectures, labelValues) as never);
    } else if (source === "munis") {
      (map.getSource("muni-labels") as GeoJSONSource).setData(pointFeatures(areas.municipalities, labelValues) as never);
    } else {
      (map.getSource("area-labels") as GeoJSONSource).setData(pointFeatures([...smallAreas.values()], labelValues) as never);
    }
  }

  async function paintPrefectures() {
    if (!nationwide) return;
    const v = prefLevel() ? await loadValues("prefectures") : null;
    applyRows("prefs", areas.prefectures.map((p) => p.id), v?.rows);
    refreshLabels("prefs");
  }

  async function paintMunicipalities() {
    const v = await loadValues("municipalities");
    applyRows("munis", munis.keys(), v?.rows);
    refreshLabels("munis");
  }

  async function paintChunk(code: string) {
    const v = await loadValues(code.slice(0, 2));
    const ids = areaFeatures.features
      .filter((f) => municipalityCodeOf(f.properties.id) === code)
      .map((f) => f.properties.id);
    applyRows("areas", ids, v?.rows);
    refreshLabels("areas");
  }

  // 都道府県名は都道府県の色分けのときだけ（「地名を表示」を外したときは出さない）
  function syncPrefLabels() {
    const on = prefLevel() && $<HTMLInputElement>("#labels-toggle").checked;
    map.setLayoutProperty("pref-label", "visibility", on ? "visible" : "none");
  }

  let legend: LegendFile | null = null;
  async function refreshColors() {
    legend = await fetchJSON<LegendFile>(`values/${indicator.id}/${period}/legend.json`);
    // 都道府県の値がある指標は、縮小すると都道府県・拡大すると市区町村（さらに町丁目）で塗る
    const muniFrom = prefLevel() ? PREF_ZOOM : 0;
    const prefMax = prefectureOnly() ? 24 : PREF_ZOOM;
    map.setLayerZoomRange("muni-fill", muniFrom, municipalityOnly() ? 24 : AREA_ZOOM);
    map.setLayerZoomRange("muni-line", muniFrom, 24);
    map.setLayerZoomRange("pref-fill", 0, prefMax);
    map.setLayerZoomRange("pref-label", 0, prefMax);
    map.setLayoutProperty("muni-fill", "visibility", prefectureOnly() ? "none" : "visible");
    map.setLayoutProperty("muni-label", "visibility",
      !prefectureOnly() && $<HTMLInputElement>("#labels-toggle").checked ? "visible" : "none");
    map.setLayoutProperty("pref-fill", "visibility", prefLevel() ? "visible" : "none");
    syncPrefLabels();
    map.setLayoutProperty("area-fill", "visibility", municipalityOnly() ? "none" : "visible");
    for (const [layer, level] of [["pref-fill", "prefecture"], ["muni-fill", "municipality"], ["area-fill", "small_area"]] as const) {
      const info = legend.levels[level];
      // 市区町村は都道府県ごとの区切りで塗る（id は muni-<都道府県2桁><市区町村3桁>）
      const byGroup = level === "municipality" && info?.by_prefecture
        ? { key: ["slice", ["get", "id"], 5, 7], breaks: info.by_prefecture } : undefined;
      map.setPaintProperty(layer, "fill-color",
        fillColorExpression(legend.scheme, info?.breaks ?? [], legend.zero_blank, byGroup) as never);
    }
    await Promise.all([paintPrefectures(), paintMunicipalities(), ...[...loadedChunks].map(paintChunk)]);
    renderLegend();
    renderDetail();
    renderList();
  }

  // --- 町丁目の追加読み込み -----------------------------------------------------------
  function ensureChunk(code: string): Promise<void> {
    if (loadedChunks.has(code)) return Promise.resolve();
    if (!loadingChunks.has(code)) {
      loadingChunks.set(code, (async () => {
        const [gj, meta] = await Promise.all([
          fetchJSON<FeatureCollection>(`boundaries/${areas.boundary_version}/${code}.geojson`),
          fetchJSON<SmallAreasFile>(`areas/${code}.json`),
        ]);
        for (const a of meta.areas) smallAreas.set(a.id, a);
        areaFeatures.features.push(...gj.features);
        (map.getSource("areas") as GeoJSONSource).setData(areaFeatures as never);
        loadedChunks.add(code);
        // setData 後は全チャンクの feature-state を付け直す
        await Promise.all([...loadedChunks].map(paintChunk));
      })());
    }
    return loadingChunks.get(code)!;
  }

  function visibleMunicipalities(): Municipality[] {
    const b = map.getBounds();
    return areas.municipalities.filter(
      (m) => m.bbox[0] <= b.getEast() && m.bbox[2] >= b.getWest() && m.bbox[1] <= b.getNorth() && m.bbox[3] >= b.getSouth(),
    );
  }

  // --- 市区町村界（細かい形）の追加読み込み ------------------------------------------------
  const finePrefs = new Map<string, Promise<void>>();
  function ensureFineMunis(code: string): Promise<void> {
    if (!finePrefs.has(code)) {
      finePrefs.set(code, (async () => {
        const gj = await fetchJSON<FeatureCollection>(`boundaries/${areas.boundary_version}/municipalities/${code}.geojson`);
        for (const f of gj.features) muniFeatures.set(f.properties.id, f);
        (map.getSource("munis") as GeoJSONSource).setData(
          { type: "FeatureCollection", features: [...muniFeatures.values()] } as never);
        await paintMunicipalities();
      })().catch(() => {}));
    }
    return finePrefs.get(code)!;
  }

  function visiblePrefectures() {
    const b = map.getBounds();
    const c = map.getCenter();
    const mid = (p: { bbox: number[] }) => ((p.bbox[0] + p.bbox[2]) / 2 - c.lng) ** 2 + ((p.bbox[1] + p.bbox[3]) / 2 - c.lat) ** 2;
    return areas.prefectures
      .filter((p) => p.bbox[0] <= b.getEast() && p.bbox[2] >= b.getWest() && p.bbox[1] <= b.getNorth() && p.bbox[3] >= b.getSouth())
      .sort((a, z) => mid(a) - mid(z));
  }

  map.on("moveend", () => {
    if (map.getZoom() >= FINE_MUNI_ZOOM) {
      visiblePrefectures().slice(0, MAX_PREFS_PER_MOVE).forEach((p) => void ensureFineMunis(p.code));
    }
    if (map.getZoom() >= AREA_ZOOM - 0.5) {
      const c = map.getCenter();
      visibleMunicipalities()
        .sort((a, b) => dist(a.center, c) - dist(b.center, c))
        .slice(0, MAX_CHUNKS_PER_MOVE)
        .forEach((m) => void ensureChunk(m.id.slice(5)).then(renderList));
    }
    renderLegend();
    renderList();
  });
  const dist = (p: [number, number], c: { lng: number; lat: number }) => (p[0] - c.lng) ** 2 + (p[1] - c.lat) ** 2;

  // --- 選択 ---------------------------------------------------------------------
  function entityName(id: string): { name: string; context: string } {
    if (isPref(id)) return { name: prefName(prefectureCodeOf(id)), context: "都道府県" };
    const m = munis.get(id);
    if (m) return { name: m.name, context: [prefName(m.prefecture), m.region].filter(Boolean).join("・") };
    const a = smallAreas.get(id);
    const parent = munis.get(`muni-${municipalityCodeOf(id)}`);
    return { name: a?.name ?? id, context: parent?.name ?? "" };
  }

  // 地域を選んだら、地点（駅・学校など）の情報は閉じる（点レイヤーの準備ができてから差し替える）
  let closePoints = () => {};
  async function select(id: string | null, fly = false) {
    selected = id;
    if (id) closePoints();
    map.setFilter("prefs-selected", ["==", ["get", "id"], id && isPref(id) ? id : ""]);
    map.setFilter("munis-selected", ["==", ["get", "id"], id && munis.has(id) ? id : ""]);
    map.setFilter("areas-selected", ["==", ["get", "id"], id && !munis.has(id) && !isPref(id) ? id : ""]);
    if (id && fly) {
      const m = munis.get(id);
      const pref = isPref(id) ? prefectures.get(prefectureCodeOf(id)!) : undefined;
      if (pref) {
        // 東京都は離島まで入れると本土が小さくなるので、区部・多摩に寄せる
        map.fitBounds(pref.code === "13" ? PRESETS.mainland : pref.bbox, { padding: 20 });
      } else if (m) {
        map.fitBounds(m.bbox, { padding: 40, maxZoom: AREA_ZOOM - 0.5 });
      } else {
        const code = municipalityCodeOf(id);
        if (code) await ensureChunk(code);
        const a = smallAreas.get(id);
        if (a) map.fitBounds(a.bbox, { padding: 60, maxZoom: 15, minZoom: AREA_ZOOM });
      }
    }
    updateUrl();
    renderLegend();
    renderDetail();
    renderList();
  }

  // 点レイヤー（駅・学校・地価公示・認可保育所）。オンにしたときだけ読み込む
  const pickEl = $("#pick-detail");
  const pointOptions = (toggle: string, legendSel: string, panel: string) => ({
    map, fetchJSON, sources, beforeLayer: "area-label", labelFont: LABEL_FONT,
    toggle: $<HTMLInputElement>(toggle), legend: $(legendSel), panel: $(panel),
    municipalityName: (id: string) => munis.get(id)?.name ?? "",
    onPanel: () => syncPanels(),
  });
  const pointLayers: PointLayer[] = [
    initStations(pointOptions("#stations-toggle", "#stations-legend", "#station-detail")),
    initSchools(pointOptions("#schools-toggle", "#schools-legend", "#school-detail")),
    initLandPrices(pointOptions("#land-toggle", "#land-legend", "#land-detail")),
    initNurseries(pointOptions("#nursery-toggle", "#nursery-legend", "#nursery-detail")),
  ];
  // 地点の情報を出している間は、地域の情報を隠す（直前にクリックしたものだけを出す）
  function syncPanels() {
    detailEl.hidden = pointLayers.some((p) => p.isOpen()) || !pickEl.hidden;
  }
  function showPoint(target: PointLayer | null, id: string | null) {
    pickEl.hidden = true;
    pickEl.innerHTML = "";
    for (const p of pointLayers) if (p !== target) p.show(null);
    if (target) target.show(id);
    syncPanels();
  }
  // 重なっている地点（同じ敷地の小学校と中学校など）は、一覧から選んでもらう
  function showPicker(hits: { layer: PointLayer; id: string; name: string }[]) {
    showPoint(null, null);
    pickEl.innerHTML = `
      <button type="button" class="close" data-close aria-label="一覧を閉じる">×</button>
      <h2>この場所の地点</h2>
      <p class="muted small">重なっている地点が${hits.length}つあります。見たい地点を選んでください。</p>
      <ul class="pick-list">${hits.map((h, k) => `<li><button type="button" data-pick="${k}">
        <span class="muted small">${esc(h.layer.kind)}</span> ${esc(h.name)}</button></li>`).join("")}</ul>`;
    pickEl.hidden = false;
    syncPanels();
    pickEl.onclick = (e) => {
      const t = e.target as HTMLElement;
      if (t.closest("[data-close]")) return showPoint(null, null);
      const b = t.closest<HTMLElement>("[data-pick]");
      if (b) {
        const h = hits[Number(b.dataset.pick)];
        showPoint(h.layer, h.id);
      }
    };
  }
  closePoints = () => showPoint(null, null);
  const PICK_PX = 4; // クリック位置の周りこのピクセル以内の点を拾う
  map.on("click", (e) => {
    const box: [PointLike, PointLike] = [[e.point.x - PICK_PX, e.point.y - PICK_PX], [e.point.x + PICK_PX, e.point.y + PICK_PX]];
    const seen = new Set<string>();
    const hits = pointLayers.filter((p) => p.visible()).flatMap((layer) =>
      map.queryRenderedFeatures(box, { layers: [layer.layer] }).map((f) => ({
        layer, id: String(f.properties.id), name: String(f.properties.name),
      }))).filter((h) => !seen.has(`${h.layer.kind}:${h.id}`) && !!seen.add(`${h.layer.kind}:${h.id}`));
    if (hits.length === 1) return showPoint(hits[0].layer, hits[0].id);
    if (hits.length > 1) return showPicker(hits);
    const f = map.queryRenderedFeatures(e.point, { layers: ["pref-fill", "muni-fill", "area-fill"] })[0];
    if (f) void select(String(f.properties.id));
  });
  for (const layer of ["pref-fill", "muni-fill", "area-fill"]) {
    map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
  }

  // --- 表示 ---------------------------------------------------------------------
  // 市区町村の一覧・凡例で見る都道府県: 選んだ地域の都道府県、なければ地図の中心にいちばん近い市区町村の都道府県
  function focusPrefecture(): string | undefined {
    return (selected && prefectureCodeOf(selected)) ||
      visibleMunicipalities().sort((a, b) => dist(a.center, map.getCenter()) - dist(b.center, map.getCenter()))[0]?.prefecture ||
      areas.prefectures[0]?.code;
  }

  function renderLegend() {
    if (!legend) return;
    const level = levelNow();
    const info = legend.levels[level];
    let levelLabel = LEVEL_LABEL[level];
    if (!info) {
      legendEl.innerHTML = `<strong>${esc(indicator.name)}</strong><p class="muted">この時点の${levelLabel}別の値はありません。</p>`;
      return;
    }
    // 市区町村の区切りは都道府県ごと。凡例は地図の中心（選んだ地域）の都道府県の区切りを出す
    let breaks = info.breaks;
    const pref = level === "municipality" && info.by_prefecture ? focusPrefecture() : undefined;
    if (pref && info.by_prefecture![pref]) {
      breaks = info.by_prefecture![pref];
      levelLabel = `${prefName(pref)}の${levelLabel}`;
    }
    const zeroBlank = !!legend.zero_blank;
    const colors = colorsFor(legend.scheme, breaks, zeroBlank);
    const fmt = (v: number) => formatNumber(v, indicator.digits);
    const items = colors.map((c, i) => {
      const lo = i === 0 ? null : breaks[i - 1];
      const hi = i === breaks.length ? null : breaks[i];
      const label = lo === null && hi === null ? (zeroBlank ? "0 より大きい" : "すべて")
        : lo === null ? (zeroBlank ? `0 より大きく ${fmt(hi!)} 未満` : `${fmt(hi!)} 未満`)
        : hi === null ? `${fmt(lo)} 以上` : `${fmt(lo)} 〜 ${fmt(hi)} 未満`;
      return `<li><span class="swatch" style="background:${c}"></span>${label}</li>`;
    });
    if (zeroBlank) items.unshift(`<li><span class="swatch blank"></span>0（色なし）</li>`);
    items.push(`<li><span class="swatch" style="background:${NO_DATA_COLOR}"></span>値なし（秘匿・欠測など）</li>`);
    legendEl.innerHTML =
      `<strong>${esc(indicator.name)}</strong>（${esc(indicator.unit)}、${esc(levelLabel)}別・${esc(periodInfo().label)}）` +
      `<ul>${items.join("")}</ul>` +
      (pref ? `<p class="muted small">市区町村の色の区切りは都道府県ごとに決めています。</p>` : "");
  }

  async function rowsFor(id: string, at = period): Promise<ValueRow[]> {
    if (!munis.has(id) && !isPref(id) && !covers(prefectureCodeOf(id))) return [];
    try {
      return (await fetchJSON<ValuesFile>(`values/${indicator.id}/${at}/${chunkOf(id)}.json`)).rows;
    } catch {
      return [];
    }
  }

  // 選んだ地域の全時点の値（推移の表）
  async function trendHtml(id: string): Promise<string> {
    const annual = annualPeriods();
    if (annual.length < 2) return "";
    const rows = await Promise.all(annual.map(async (p) => ({
      p, row: (await rowsFor(id, p.period)).find((r) => r.entity_id === id),
    })));
    let prev: number | null = null;
    // 増減率はそれ自体が前回からの変化なので、さらに差を取る列は出さない
    const withChange = indicator.kind !== "change";
    const body = rows.map(({ p, row }) => {
      const v = row?.value ?? null;
      let change = "";
      if (withChange && v !== null && prev !== null) {
        const diff = v - prev;
        // 表示の桁で0になる差は「±」にする（−0.00 と出さない）
        const shown = Number(Math.abs(diff).toFixed(indicator.digits));
        const sign = shown === 0 ? "±" : diff > 0 ? "+" : "−";
        const amount = `${sign}${formatNumber(Math.abs(diff), indicator.digits)}`;
        // 割合（%）は差（ポイント）、人数などは差と増減率
        const text = indicator.unit === "%" ? `${amount}ポイント`
          : prev ? `${amount}（${sign}${formatNumber(Math.abs(diff / prev) * 100, 1)}%）` : amount;
        change = esc(text);
      }
      prev = v;
      return `<tr${p.period === period ? ' aria-current="true"' : ""}><td>${esc(shortLabel(p.label))}</td>
        <td class="num">${esc(formatValue(row, indicator))}</td>${withChange ? `<td class="num">${change}</td>` : ""}</tr>`;
    }).join("");
    const note = rows.find(({ row }) => row?.status === "not_applicable")?.row?.note;
    return `<table class="trend"><caption>推移</caption>
      <thead><tr><th>時点</th><th class="num">${esc(indicator.name)}</th>${withChange ? '<th class="num">前回から</th>' : ""}</tr></thead>
      <tbody>${body}</tbody></table>${note ? `<p class="muted small">${esc(note)}</p>` : ""}`;
  }

  // 並べて見る指標（compare_with）の同じ時点・同じ地域の値
  async function compareHtml(id: string): Promise<string> {
    const others = (indicator.compare_with ?? [])
      .map((cid) => indicators.find((i) => i.id === cid))
      .filter((o): o is Indicator => !!o && o.periods.some((p) => p.period === period));
    if (!others.length) return "";
    const items = await Promise.all(others.map(async (o) => {
      let row: ValueRow | undefined;
      if (!munis.has(id) && !isPref(id) && o.prefectures && !o.prefectures.includes(prefectureCodeOf(id)!)) return "";
      try {
        row = (await fetchJSON<ValuesFile>(`values/${o.id}/${period}/${chunkOf(id)}.json`)).rows
          .find((r) => r.entity_id === id);
      } catch {
        return "";
      }
      if (!row) return "";
      return `<li><a href="?i=${esc(o.id)}&p=${esc(period)}&a=${esc(id)}" data-indicator="${esc(o.id)}">${esc(o.name)}</a>
        <strong>${esc(formatValue(row, o))}</strong></li>`;
    }));
    const body = items.filter(Boolean).join("");
    return body ? `<div class="compare-with"><p class="small">あわせて見る（同じ時点）</p><ul class="small">${body}</ul></div>` : "";
  }

  let detailToken = 0;
  async function renderDetail() {
    const token = ++detailToken;
    if (!selected) {
      detailEl.innerHTML = `<p class="muted">地図をクリックするか、地域名で検索してください。</p>`;
      return;
    }
    // 都道府県だけの指標では、市区町村・町丁目を選んでもその都道府県の値を出す
    const within = prefectureOnly() && !isPref(selected) && prefectureCodeOf(selected) ? selected : null;
    const id = within ? `pref-${prefectureCodeOf(within)}` : selected;
    const [rows, trend, compare] = await Promise.all([rowsFor(id), trendHtml(id), compareHtml(id)]);
    if (token !== detailToken) return;
    const row = rows.find((r) => r.entity_id === id);
    const { name, context } = entityName(id);
    const isMuni = munis.has(id);
    const pref = isPref(id);
    // 順位は都道府県は全国の中、市区町村は同じ都道府県の中、町丁・字等は同じ市区町村の中で数える
    const sameGroup = (other: string) => (pref ? isPref(other)
      : (isMuni ? prefectureCodeOf(other) === prefectureCodeOf(id)
        : municipalityCodeOf(other) === municipalityCodeOf(id)) && munis.has(other) === isMuni);
    const rank = rankOf(rows.filter((r) => sameGroup(r.entity_id)), id);
    const fraction = formatFraction(row, indicator);
    const p = periodInfo();
    // 出典は元のページ（URL があれば）へのリンクにする（別のタブで開く）
    const srcs = new Map<string, string | null>();
    for (const sid of p.source_ids) {
      const s = sources.get(sid);
      const text = s?.attribution ?? sid;
      if (!srcs.get(text)) srcs.set(text, s?.url ?? null);
    }
    const srcHtml = [...srcs].map(([text, url]) => (url
      ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text))).join("／");
    const parentId = pref ? null : isMuni ? id : `muni-${municipalityCodeOf(id)}`;
    const rankScope = pref ? "全国の都道府県" : isMuni ? `${prefName(prefectureCodeOf(id))}の市区町村`
      : `${entityName(parentId!).name}内の地域`;
    detailEl.innerHTML = `
      <p class="muted">${esc(context)}</p>
      <h2>${esc(name)}</h2>
      <div>${esc(indicator.name)}（${esc(p.label)}）</div>
      <div class="value">${esc(formatValue(row, indicator))}</div>
      ${fraction ? `<div class="muted">${esc(fraction)}</div>` : ""}
      ${row?.value != null && STATUS_LABEL[row.status] ? `<div class="muted">${esc(STATUS_LABEL[row.status])}</div>` : ""}
      ${row?.note ? `<p class="note small">${esc(row.note)}</p>` : ""}
      ${within ? `<p class="note small">この指標は都道府県別の値だけです（${esc(entityName(within).name)}を含む${esc(name)}の値）。</p>` : ""}
      ${!pref && !covers(prefectureCodeOf(id)) ? `<p class="note small">この指標は${esc(indicator.prefectures!.map(prefName).join("・"))}だけの値です。</p>` : ""}
      ${compare}
      ${trend}
      ${rank ? `<p>${esc(rankScope)} ${rank.total} のうち <strong>${rank.rank}位</strong></p>` : ""}
      <p class="small"><a href="/indicators/${esc(indicator.id)}/">この指標の意味と注意点</a>
        ${parentId ? `・<a href="/areas/${esc(parentId)}/">${esc(entityName(parentId).name)}のページ</a>` : ""}</p>
      <p class="muted small sources">${srcHtml}（<a href="/sources/">出典の一覧</a>）</p>`;
  }

  async function renderList() {
    const level = levelNow();
    let ids: string[];
    let title: string;
    let rows: ValueRow[];
    if (level === "prefecture") {
      ids = areas.prefectures.map((p) => p.id);
      rows = (await loadValues("prefectures"))?.rows ?? [];
      title = "都道府県";
    } else if (level === "municipality") {
      // 全国の市区町村を並べると長すぎるので、選んだ地域（なければ地図の中心）の都道府県だけにする
      const pref = focusPrefecture();
      ids = areas.municipalities.filter((m) => m.prefecture === pref).map((m) => m.id);
      rows = (await loadValues("municipalities"))?.rows ?? [];
      title = `${prefName(pref)}の市区町村`;
    } else {
      const code = (selected && municipalityCodeOf(selected)) ||
        visibleMunicipalities().sort((a, b) => dist(a.center, map.getCenter()) - dist(b.center, map.getCenter()))[0]?.id.slice(5);
      if (!code || !loadedChunks.has(code)) {
        listEl.innerHTML = `<p class="muted">読み込み中…</p>`;
        return;
      }
      ids = [...smallAreas.keys()].filter((id) => municipalityCodeOf(id) === code);
      rows = (await loadValues(code.slice(0, 2)))?.rows ?? [];
      title = `${munis.get(`muni-${code}`)?.name ?? ""}の町丁・字等`;
    }
    const byId = new Map(rows.map((r) => [r.entity_id, r]));
    const sorted = ids
      .map((id) => ({ id, row: byId.get(id) }))
      .sort((a, b) => (b.row?.value ?? -Infinity) - (a.row?.value ?? -Infinity));
    listEl.innerHTML = `<p class="small"><strong>${esc(title)}</strong>（値の大きい順）</p>
      <table><thead><tr><th>地域</th><th class="num">${esc(indicator.name)}</th></tr></thead><tbody>
      ${sorted.map(({ id, row }) => `<tr${id === selected ? ' aria-current="true"' : ""}>
        <td><a href="?a=${esc(id)}" data-select="${esc(id)}">${esc(entityName(id).name)}</a></td>
        <td class="num">${esc(formatValue(row, indicator))}</td></tr>`).join("")}
      </tbody></table>`;
  }

  listEl.addEventListener("click", (e) => {
    const a = (e.target as HTMLElement).closest<HTMLAnchorElement>("a[data-select]");
    if (a) {
      e.preventDefault();
      void select(a.dataset.select!, true);
    }
  });

  function updateUrl() {
    const qs = serializeState({ indicator: indicator.id, period, area: selected ?? undefined });
    history.replaceState(null, "", `${location.pathname}${qs}`);
  }

  // --- 指標・時点の選択 ---------------------------------------------------------------
  // 犯罪のように family でまとめた指標は、選択肢を1つにして「種別」「基準」で切り替える
  const optionValue = (i: Indicator) => (i.family ? `family:${i.family}` : i.id);
  const familyMembers = (family: string) => indicators.filter((i) => i.family === family);
  // 組の選択肢は種別を外した名前にする（例: 「通勤・通学の交通手段（鉄道・電車）」→「通勤・通学の交通手段」）
  const optionLabel = (i: Indicator) => (i.family ? i.name.replace(/（[^（）]*）$/, "") : i.name);
  indicatorSelect.innerHTML = [...new Set(indicators.map((i) => i.category))]
    .map((c) => {
      const seen = new Set<string>();
      const opts = indicators.filter((i) => i.category === c && !seen.has(optionValue(i)) && seen.add(optionValue(i)))
        .map((i) => `<option value="${esc(optionValue(i))}">${esc(optionLabel(i))}</option>`).join("");
      return `<optgroup label="${esc(c)}">${opts}</optgroup>`;
    })
    .join("");
  const unique = (xs: string[]) => [...new Set(xs)];
  function syncIndicatorControls() {
    indicatorSelect.value = optionValue(indicator);
    facetsEl.hidden = !indicator.family;
    if (!indicator.family || !indicator.facets) return;
    const members = familyMembers(indicator.family);
    const { type, basis } = indicator.facets;
    facetType.innerHTML = unique(members.map((m) => m.facets!.type))
      .map((t) => `<option${t === type ? " selected" : ""}>${esc(t)}</option>`).join("");
    facetBasis.innerHTML = unique(members.filter((m) => m.facets!.type === type).map((m) => m.facets!.basis))
      .map((b) => `<option${b === basis ? " selected" : ""}>${esc(b)}</option>`).join("");
  }
  function setIndicator(next: Indicator, how: UsageHow | null) {
    stopPlay();
    indicator = next;
    if (how) countIndicatorUse(indicator.id, how);
    if (!indicator.periods.some((p) => p.period === period)) period = indicator.default_period;
    syncIndicatorControls();
    fillPeriods();
    updateUrl();
    void refreshColors();
  }
  // 時点はスライドバーで選ぶ（古い順）。再生ボタンで順に切り替えて変化を追える。
  // 複数年の合計はスライドバーに並べず、「直近5年の合計で見る」のチェックで切り替える
  function fillPeriods() {
    const ps = annualPeriods();
    const agg = aggregatePeriod();
    const onAggregate = !!periodInfo().aggregate;
    periodRange.max = String(ps.length - 1);
    periodRange.value = String(Math.max(0, ps.findIndex((p) => p.period === period)));
    periodRange.disabled = ps.length < 2;
    playButton.disabled = ps.length < 2;
    periodTicks.innerHTML = ps.length < 2 ? "" : ps
      // 時点が多いとき（犯罪の年ごとなど）は「’19」のように短くして1行に収める
      .map((p, i) => `<span data-i="${i}"${p.period === period ? ' aria-current="true"' : ""} title="${esc(p.label)}">${
        esc(ps.length > 4 ? shortLabel(p.label).replace(/^\d{2}(\d{2})年$/, "’$1") : shortLabel(p.label))}</span>`)
      .join("");
    periodLabel.value = periodInfo().label;
    periodNote.hidden = ps.length > 1;
    periodNote.textContent = ps.length > 1 ? "" : "この指標は1時点のみです。";
    periodField.classList.toggle("aggregate", onAggregate);
    aggregateWrap.hidden = !agg;
    aggregateToggle.checked = onAggregate;
    if (agg) {
      const [from, to] = agg.period.split("-").map(Number);
      aggregateLabel.textContent = `直近${to - from + 1}年の合計で見る（${from}〜${to}年）`;
    }
  }
  function setPeriod(i: number) {
    const p = annualPeriods()[i];
    if (!p || p.period === period) return;
    period = p.period;
    fillPeriods();
    updateUrl();
    void refreshColors();
  }
  let playTimer: number | undefined;
  function stopPlay() {
    clearInterval(playTimer);
    playTimer = undefined;
    playButton.setAttribute("aria-pressed", "false");
    playButton.textContent = "▶";
  }
  playButton.addEventListener("click", () => {
    if (playTimer !== undefined) return stopPlay();
    playButton.setAttribute("aria-pressed", "true");
    playButton.textContent = "■";
    let i = 0;
    setPeriod(i);
    playTimer = window.setInterval(() => {
      i += 1;
      if (i >= annualPeriods().length) return stopPlay();
      setPeriod(i);
    }, PLAY_INTERVAL_MS);
  });
  aggregateToggle.addEventListener("change", () => {
    stopPlay();
    const agg = aggregatePeriod();
    period = aggregateToggle.checked && agg ? agg.period : indicator.default_period;
    fillPeriods();
    updateUrl();
    void refreshColors();
  });
  syncIndicatorControls();
  fillPeriods();
  countIndicatorUse(indicator.id, "open");
  indicatorSelect.addEventListener("change", () => {
    const v = indicatorSelect.value;
    const next = v.startsWith("family:") ? familyMembers(v.slice(7))[0] : indicators.find((i) => i.id === v);
    if (next) setIndicator(next, "switch");
  });
  // 種別・基準を変えたら、組の中で両方が合う指標に切り替える（なければ種別だけ合うもの）
  function onFacetChange() {
    const members = familyMembers(indicator.family!);
    const type = facetType.value, basis = facetBasis.value;
    const next = members.find((m) => m.facets!.type === type && m.facets!.basis === basis)
      ?? members.find((m) => m.facets!.type === type);
    if (next && next !== indicator) setIndicator(next, "switch");
  }
  facetType.addEventListener("change", onFacetChange);
  facetBasis.addEventListener("change", onFacetChange);
  // 「あわせて見る」の指標名で、その指標に切り替える
  detailEl.addEventListener("click", (e) => {
    const a = (e.target as HTMLElement).closest<HTMLAnchorElement>("a[data-indicator]");
    if (!a) return;
    e.preventDefault();
    const next = indicators.find((i) => i.id === a.dataset.indicator);
    if (next) setIndicator(next, "switch");
  });
  periodRange.addEventListener("input", () => {
    stopPlay();
    setPeriod(Number(periodRange.value));
  });
  periodTicks.addEventListener("click", (e) => {
    const t = (e.target as HTMLElement).closest<HTMLElement>("span[data-i]");
    if (t) {
      stopPlay();
      setPeriod(Number(t.dataset.i));
    }
  });

  // --- 左右の欄の表示・非表示 -----------------------------------------------------------
  for (const btn of root.querySelectorAll<HTMLButtonElement>(".panel-toggle")) {
    btn.addEventListener("click", () => {
      const side = btn.dataset.panel as "left" | "right";
      const hidden = root.classList.toggle(`hide-${side}`);
      const what = side === "left" ? "条件" : "情報";
      btn.setAttribute("aria-pressed", String(hidden));
      btn.textContent = (side === "left") === hidden ? "›" : "‹";
      btn.title = btn.ariaLabel = `${what}の欄を${hidden ? "表示" : "隠す"}`;
      map.resize();
    });
  }

  // --- 背景・範囲・現在地 -------------------------------------------------------------
  const baseToggle = $<HTMLInputElement>("#basemap-toggle");
  baseToggle.addEventListener("change", () => {
    const photo = baseToggle.checked;
    map.setLayoutProperty("photo", "visibility", photo ? "visible" : "none");
    map.setLayoutProperty("pale", "visibility", photo ? "none" : "visible");
  });
  // 色分けを消して、背景地図と地名・数値だけで見る（地域のクリックはそのまま使える）
  colorsToggle.addEventListener("change", () => {
    const on = colorsToggle.checked;
    map.setPaintProperty("muni-fill", "fill-opacity", on ? MUNI_OPACITY : 0);
    map.setPaintProperty("pref-fill", "fill-opacity", on ? MUNI_OPACITY : 0);
    map.setPaintProperty("area-fill", "fill-opacity", on ? AREA_OPACITY : 0);
    legendEl.classList.toggle("dimmed", !on);
    // 色分けを消したときは背景地図の彩度を落とし、駅・学校などの点や文字と混ざらないようにする
    map.setPaintProperty("pale", "raster-saturation", on ? 0 : -1);
    map.setPaintProperty("pale", "raster-contrast", on ? 0 : -0.15);
    map.setPaintProperty("photo", "raster-saturation", on ? 0 : -0.8);
  });
  const labelsToggle = $<HTMLInputElement>("#labels-toggle");
  labelsToggle.addEventListener("change", () => {
    map.setLayoutProperty("muni-label", "visibility", labelsToggle.checked && !prefectureOnly() ? "visible" : "none");
    map.setLayoutProperty("area-label", "visibility", labelsToggle.checked ? "visible" : "none");
    syncPrefLabels();
  });
  valuesToggle.addEventListener("change", () => {
    for (const layer of ["pref-label", "muni-label", "area-label"]) map.setLayoutProperty(layer, "text-field", labelText() as never);
  });
  // 範囲: 全国・都道府県（東京都は島しょも）。都道府県の範囲は離島を含むので、県庁所在地側に寄らないこともある
  const regionJump = $<HTMLSelectElement>("#region-jump");
  const tokyoIslands = prefectures.has("13")
    ? '<option value="mainland">東京都（区部・多摩）</option><option value="izu">東京都（伊豆諸島）</option>' +
      '<option value="ogasawara">東京都（小笠原諸島）</option>' : "";
  regionJump.innerHTML = (areas.prefectures.length > 1 ? '<option value="japan">全国</option><option value="okinawa">沖縄・南西諸島</option>' : "") +
    areas.prefectures.filter((p) => p.code !== "13")
      .map((p) => `<option value="pref:${esc(p.code)}">${esc(p.name)}</option>`).join("") + tokyoIslands;
  regionJump.value = areas.prefectures.length > 1 ? "japan" : "mainland";
  regionJump.addEventListener("change", () => {
    const v = regionJump.value;
    const bounds = v.startsWith("pref:") ? prefectures.get(v.slice(5))?.bbox : PRESETS[v];
    if (bounds) map.fitBounds(bounds as LngLatBoundsLike, { padding: 20 });
  });
  $<HTMLButtonElement>("#locate").addEventListener("click", () => {
    // 利用者が押したときだけ位置情報の許可を求める。位置は送信・保存しない。
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => map.flyTo({ center: [pos.coords.longitude, pos.coords.latitude], zoom: 14 }),
      () => alert("現在地を取得できませんでした。"),
      { enableHighAccuracy: false, timeout: 10000 },
    );
  });

  // --- 検索 ---------------------------------------------------------------------
  const searchInput = $<HTMLInputElement>("#search-input");
  const resultsEl = $<HTMLUListElement>("#search-results");
  let searcher: AreaSearch | null = null;
  let hits: SearchHit[] = [];
  let active = -1;
  // 市区町村は全国から、町丁・字等は表示中（または選んだ地域）の都道府県から探す
  const searchedPrefs = new Set<string>();
  const getSearcher = async () => {
    searcher ??= new AreaSearch(await fetchJSON<SearchIndex>("search-index.json"));
    const wanted = [selected && prefectureCodeOf(selected), ...visiblePrefectures().slice(0, MAX_PREFS_PER_MOVE).map((p) => p.code)]
      .filter((c): c is string => !!c && !searchedPrefs.has(c));
    for (const code of new Set(wanted)) {
      searchedPrefs.add(code);
      try {
        searcher.add(await fetchJSON<SearchIndex>(`search-index/${code}.json`));
      } catch {
        // 町丁・字等の索引がない都道府県
      }
    }
    return searcher;
  };

  function showHits() {
    resultsEl.hidden = hits.length === 0;
    searchInput.setAttribute("aria-expanded", String(hits.length > 0));
    resultsEl.innerHTML = hits.map((h, i) =>
      `<li role="option" id="hit-${i}" data-i="${i}" aria-selected="${i === active}">${esc(h.name)}
        <span class="muted small">${esc(h.context)}</span></li>`).join("");
  }
  function choose(i: number) {
    const h = hits[i];
    if (!h) return;
    searchInput.value = h.name;
    hits = [];
    showHits();
    void select(h.id, true);
  }
  searchInput.addEventListener("input", async () => {
    hits = (await getSearcher()).search(searchInput.value);
    active = hits.length ? 0 : -1;
    showHits();
  });
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      active = Math.max(0, Math.min(hits.length - 1, active + (e.key === "ArrowDown" ? 1 : -1)));
      showHits();
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(active);
    } else if (e.key === "Escape") {
      hits = [];
      showHits();
    }
  });
  resultsEl.addEventListener("mousedown", (e) => {
    const li = (e.target as HTMLElement).closest<HTMLLIElement>("li[data-i]");
    if (li) choose(Number(li.dataset.i));
  });
  searchInput.addEventListener("blur", () => setTimeout(() => { hits = []; showHits(); }, 150));

  // --- 初期表示 -------------------------------------------------------------------
  await refreshColors();
  if (initial.area && (munis.has(initial.area) || municipalityCodeOf(initial.area) ||
      (isPref(initial.area) && prefectures.has(prefectureCodeOf(initial.area)!)))) {
    await select(initial.area, true);
  } else {
    updateUrl();
  }
}

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
