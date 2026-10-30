// 地図画面（/map/）のブラウザ側の処理。
// 読み込み順: 指標カタログ・市区町村境界 → 拡大時に町丁目境界 → 指標・時点を切り替えたら必要な値だけ
// （設計書 第9章「読み込みの順序」）。指標切替では地図を作り直さず feature-state と色だけ更新する。
import type * as MapLibre from "maplibre-gl";
import type { GeoJSONSource, LngLatBoundsLike, PointLike } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { colorsFor, fillColorExpression, NO_DATA_COLOR, textWidth, tickStep } from "../lib/classify";
import { bandLabel, compactNumber, formatBasis, formatFraction, formatNumber, formatValue, rankIfVaried } from "../lib/format";
import { AreaSearch, type SearchHit } from "../lib/search";
import { countIndicatorUse, type UsageHow } from "../lib/usage";
import type {
  AreasFile, Indicator, IndicatorCatalog, Level, LegendFile, Municipality, SearchIndex,
  SmallArea, SmallAreasFile, Source, ValueRow, ValuesFile,
} from "../lib/types";
import { type MapState, municipalityCodeOf, parseState, prefectureCodeOf, serializeState } from "../lib/urlstate";
import { initStations } from "./stations";
import { initSchools } from "./schools";
import { initLandPrices } from "./landprices";
import { initNurseries } from "./nurseries";
import { initWeather } from "./weather";
import { initLandUse, NARROW_MAP_PX } from "./landuse";
import { initTransport } from "./transport";
import { initFacilities } from "./facilities";
import { initShare, safeFileName, type BaseLegend, type LegendModel } from "./share";
import { RELIEF_STOPS, reliefAt } from "./relief";
import { registerSlopeProtocol, SLOPE_CLASSES, SLOPE_MAXZOOM, SLOPE_MINZOOM, SLOPE_TILES } from "./slope";
import { PHOTO_MASK_SIZE, PHOTO_MIN_SHARE, photoMask, photoSamples, photoShare } from "./photoEras";
import type { FocusPoint, PointLayer } from "./points";
import { genresFor } from "../lib/genres";
import { normalize } from "../lib/search";
import { balancedFits, growingTextSize, labelFit, mainPartBbox, type LabelItem } from "../lib/labels";
import { esc } from "../lib/html";

// 縮尺に合わせて、都道府県 → 市区町村 → 町丁目の値に切り替える（#52）
// 切り替えは、次の段階の地名がある程度読める縮尺まで待つ（市区町村名は MUNI_LABEL_ZOOM、町丁目名は AREA_LABEL_ZOOM から）
const PREF_ZOOM = 8; // これ未満では都道府県の値で色分けする（全国のデータのとき）
const AREA_ZOOM = 13; // これ以上で町丁目を表示
const FINE_MUNI_ZOOM = 8; // これ以上で市区町村界を都道府県ごとの細かい形に差し替える（初回は全国の粗い形）
const MAX_PREFS_PER_MOVE = 6;
const MAX_CHUNKS_PER_MOVE = 8;
// 色分けの単位で「町丁目」を選んだときは、自動より手前の縮尺から町丁目で塗る（全国の町丁目の境界は大きすぎて
// 一度に読めないので、これより縮小したときは市区町村で塗る）。一度に読む市区町村の数も増やす（#146）
const MANUAL_AREA_ZOOM = 10;
const MAX_CHUNKS_MANUAL = 40;
// 地名の文字。漢字・かなは端末のフォントで描き、数字などだけ地理院のフォントを読み込む
// （地理院の noto-jp にあるのは NotoSansCJKjp-Regular。NotoSansJP-Regular は 404 で、数字などが描けなかった）
const GLYPHS_URL = "https://maps.gsi.go.jp/xyz/noto-jp/{fontstack}/{range}.pbf";
const LABEL_FONT = ["NotoSansCJKjp-Regular"];
const LOCAL_FONT = '"Hiragino Sans", "Noto Sans JP", "Yu Gothic UI", "Meiryo", sans-serif';
const AREA_LABEL_ZOOM = AREA_ZOOM; // 町丁目名はこれ以上で表示（狭い範囲に多数あるため。町丁目を選んだときは MANUAL_AREA_ZOOM から）
const MUNI_LABEL_ZOOM = PREF_ZOOM; // 市区町村名はこれ以上で表示
const PLAY_INTERVAL_MS = 1600;
const PHOTO_PLAY_INTERVAL_MS = 2500; // 航空写真は読み込みに時間がかかるので、指標の再生より長めに見せる
// 色分けの濃さ。全国で共通の区切りで区分が多い（最大20、#145）ので、隣の区分の色の差が背景に埋もれないよう濃いめにする
const MUNI_OPACITY = 0.82;
const AREA_OPACITY = 0.78;
const TICK_FONT_PX = 11.5; // 凡例の区切りの値の文字の大きさ（.legend-ticks の 0.72rem）
const POPUP_MAX_PX = 420; // 地点の情報のポップアップの高さの上限
// ポップアップを地図の端からこれだけ離す（上は左上の背景の切替の下まで）
const POPUP_PAD = { top: 58, bottom: 24, side: 12 };
const GSI_ATTRIBUTION =
  '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noopener">地理院タイル</a>';
// 背景に切り替えられる地理院タイル（淡色地図はいつも下に敷き、写真が撮られていない場所や縮小時はそれが見える）。
// 年代別の空中写真は拡大しないと出ない（minzoom）。色別標高図は z15 まで。傾斜は標高タイルからブラウザで作る（slope.ts、#177）
const GSI_TILE = (path: string) => `https://cyberjapandata.gsi.go.jp/xyz/${path}/{z}/{x}/{y}`;
// 航空写真は撮影年代をスライドバーで選ぶ（古い順）。2007年度以降は年度ごとに撮影した地域の写真
// （年度別空中写真）で、どの年度も国土の一部だけ。1979〜1990年の国土画像情報も主に都市部だけ。
// 1991〜2006年は地理院タイルの写真がない
const NENDO_FIRST = 2007;
const NENDO_LAST = 2025;
export const PHOTO_ERAS = [
  { id: "photo1928", label: "1928年頃", path: "ort_1928", ext: "png", minzoom: 13, maxzoom: 18 },
  { id: "photo1936", label: "1936〜1942年頃", path: "ort_riku10", ext: "png", minzoom: 13, maxzoom: 18 },
  { id: "photo1945", label: "1945〜1950年", path: "ort_USA10", ext: "png", minzoom: 10, maxzoom: 17 },
  { id: "photo1961", label: "1961〜1969年", path: "ort_old10", ext: "png", minzoom: 10, maxzoom: 17 },
  { id: "photo1974", label: "1974〜1978年", path: "gazo1", ext: "jpg", minzoom: 10, maxzoom: 17 },
  { id: "photo1979", label: "1979〜1983年", path: "gazo2", ext: "jpg", minzoom: 10, maxzoom: 17 },
  { id: "photo1984", label: "1984〜1986年", path: "gazo3", ext: "jpg", minzoom: 10, maxzoom: 17 },
  { id: "photo1987", label: "1987〜1990年", path: "gazo4", ext: "jpg", minzoom: 10, maxzoom: 17 },
  ...Array.from({ length: NENDO_LAST - NENDO_FIRST + 1 }, (_, i) => NENDO_FIRST + i).map((y) => (
    { id: `photo${y}n`, label: `${y}年度`, path: `nendophoto${y}`, ext: "png", minzoom: 14, maxzoom: 18 })),
  { id: "photo", label: "最新", path: "seamlessphoto", ext: "jpg", minzoom: 2, maxzoom: 18 },
].map((e) => ({ ...e, tiles: GSI_TILE(e.path) + "." + e.ext }));
export const BASEMAPS = [
  ...PHOTO_ERAS,
  // 色別標高図は海域部に海上保安庁の資料を使っており、その旨の記載が必要
  { id: "relief", label: "標高（色別標高図）", tiles: GSI_TILE("relief") + ".png", minzoom: 5, maxzoom: 15,
    note: "（海域部は海上保安庁海洋情報部の資料を使用して作成）" },
  { id: "slope", label: "傾斜", tiles: SLOPE_TILES, minzoom: SLOPE_MINZOOM, maxzoom: SLOPE_MAXZOOM,
    note: "（標高タイルから傾斜を計算）" },
];
// 写真の写り方を覚えておくタイルの数の上限（超えたら忘れて読み直す）
const PHOTO_MASK_CACHE_MAX = 3000;

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

// 右の欄のリンクの印（サイト内のページは「›」、別のタブで開く外のサイトは矢印つきの四角）
const ICON_NEXT = '<svg class="icon" viewBox="0 0 16 16" aria-hidden="true"><path d="m6 3.5 4.5 4.5L6 12.5"/></svg>';
const ICON_EXTERNAL = '<svg class="icon" viewBox="0 0 16 16" aria-hidden="true">' +
  '<path d="M9.5 2.5h4v4M13.5 2.5 7.5 8.5M12 9.5v3.5a.5.5 0 0 1-.5.5h-8a.5.5 0 0 1-.5-.5v-8a.5.5 0 0 1 .5-.5H7"/></svg>';

const shortLabel = (label: string) => label.replace(/(\d+年).*/, "$1");
// 推移の表の時点。年度の指標は「2024年度」のまま（「2024年」と書くと暦年と取り違える）
const trendLabel = (label: string) => label.replace(/(\d+年度?).*/, "$1");

// 地名の文字の大きさに使う範囲（形のいちばん大きい部分）。境界を読み込んだときに入れる
const labelBoxes = new Map<string, [number, number, number, number]>();
const pointFeatures = (items: (LabelItem & { id: string; center: [number, number] })[], values?: Map<string, string>): FeatureCollection => {
  const boxed = items.map((a) => ({ ...a, bbox: labelBoxes.get(a.id) ?? a.bbox }));
  const fit = balancedFits(boxed.map((a) => labelFit(a, null)));
  const fitv = balancedFits(boxed.map((a) => labelFit(a, values?.get(a.id) ?? "")));
  return {
    type: "FeatureCollection",
    features: items.map((a, i) => ({
      type: "Feature",
      properties: { id: a.id, name: a.name, value: values?.get(a.id) ?? "", fit: fit[i], fitv: fitv[i] },
      geometry: { type: "Point", coordinates: a.center },
    })),
  };
};

// 最大は最小の1.3倍ほどまで（並んだ地名の大きさの差が目立たないように、#90）。
// 重なる地名は出せないので、たくさん出せるよう小さめにする（#96）
const PREF_TEXT: [number, number, number][] = [[4, 10, 11], [6, 11, 13], [8, 11, 14]];
const MUNI_TEXT: [number, number, number][] = [[8, 9, 11], [9, 10, 12], [12, 12, 15], [15, 14, 17], [18, 14, 17]];
const AREA_TEXT: [number, number, number][] = [[10, 9, 10], [13, 9, 11], [16, 11, 14], [18, 12, 15]];

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

  // 都道府県・市区町村の公式サイト（Wikidata から集めた URL、設計変更記録 #135）。初めて地域を選んだときに読む。
  // 開発用の架空データでは地名が実在しないので読まない（地図のページが data-official-sites を空にする）
  const sitesUrl = root.dataset.officialSites;
  let officialSites: Promise<Record<string, string>> | null = null;
  const officialSite = async (id: string): Promise<string | undefined> => {
    if (!sitesUrl) return undefined;
    officialSites ??= fetch(sitesUrl)
      .then((r) => (r.ok ? r.json() as Promise<{ sites?: Record<string, string> }> : null))
      .then((j) => j?.sites ?? {}, () => ({}));
    return (await officialSites)[id];
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
  const facetTypeWrap = $<HTMLElement>("#facet-type-wrap");
  const facetBasis = $<HTMLSelectElement>("#facet-basis");
  const facetBasisWrap = $<HTMLElement>("#facet-basis-wrap");
  const aggregateWrap = $("#aggregate-wrap");
  const aggregateToggle = $<HTMLInputElement>("#aggregate-toggle");
  const aggregateLabel = $("#aggregate-label");
  const periodField = periodRange.closest<HTMLElement>(".period")!;
  const colorsToggle = $<HTMLInputElement>("#colors-toggle");
  const scopeEl = $("#indicator-scope");
  const detailEl = $("#detail");

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
  const levelOf = (id: string): Level => (isPref(id) ? "prefecture" : munis.has(id) ? "municipality" : "small_area");
  // その時点にその粒度の値があるか（ない粒度のファイルは読みにいかない。読むと 404 になる）
  const hasLevel = (ind: Indicator, at: string, level: Level) =>
    !!ind.periods.find((p) => p.period === at)?.levels.includes(level);
  const smallAreas = new Map<string, SmallArea>();
  const loadedChunks = new Set<string>();
  const loadingChunks = new Map<string, Promise<void>>();
  const areaFeatures: FeatureCollection = { type: "FeatureCollection", features: [] };

  const initial = parseState(location.search);
  let indicator: Indicator = indicators.find((i) => i.id === initial.indicator) ?? indicators[0];
  let period = indicator.periods.find((p) => p.period === initial.period)?.period ?? indicator.default_period;
  let selected: string | null = null;
  // 色分けの単位: auto は縮尺に合わせて切り替え、ほかは手で選んだ単位（#146）
  type LevelMode = "auto" | Level;
  const LEVEL_MODES: LevelMode[] = ["auto", "prefecture", "municipality", "small_area"];
  let levelMode: LevelMode = LEVEL_MODES.find((m) => m !== "auto" && m === initial.level) ?? "auto";

  // --- 地図 ---------------------------------------------------------------------
  registerSlopeProtocol(maplibregl);
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
        ...Object.fromEntries(BASEMAPS.map((b) => [b.id, {
          type: "raster" as const, tileSize: 256, minzoom: b.minzoom, maxzoom: b.maxzoom,
          attribution: GSI_ATTRIBUTION + ("note" in b ? b.note : ""), tiles: [b.tiles],
        }])),
      },
      layers: [
        { id: "pale", type: "raster", source: "pale" },
        ...BASEMAPS.map((b) => ({ id: b.id, type: "raster" as const, source: b.id, layout: { visibility: "none" as const } })),
      ],
    },
    // 共有URLに地図の位置があればそこ（#175）。なければ、全国のデータがあるときは日本全体、
    // 東京都だけのとき（プレビュー用の公開版など）は区部・多摩
    ...(initial.view
      ? { center: [initial.view.lng, initial.view.lat] as [number, number], zoom: initial.view.zoom,
          bearing: initial.view.bearing ?? 0, pitch: initial.view.pitch ?? 0 }
      : { bounds: areas.prefectures.length > 1 ? PRESETS.japan : PRESETS.mainland }),
    maxZoom: 17,
    attributionControl: { compact: false },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
  // 現在地: ボタンを押したときだけ位置情報の許可を求め、現在地のマークと誤差の円を出す。
  // 歩くとマークが動き、地図を動かすと追従をやめる（マークは更新し続ける）。位置はブラウザ内だけで使う。
  const geolocate = new maplibregl.GeolocateControl({
    positionOptions: { enableHighAccuracy: true, timeout: 10000 },
    fitBoundsOptions: { maxZoom: 15 },
    trackUserLocation: true,
    showAccuracyCircle: true,
  });
  map.addControl(geolocate, "bottom-right");
  geolocate.on("error", (e) => {
    alert(e.code === 1 /* PERMISSION_DENIED */
      ? "位置情報の利用が許可されていません。ブラウザの設定でこのサイトの位置情報を許可してください。"
      : "現在地を取得できませんでした。");
  });
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
  for (const f of [...muniBoundaries.features, ...(prefBoundaries?.features ?? [])]) {
    const b = mainPartBbox(f.geometry as never);
    if (b) labelBoxes.set(f.properties.id, b);
  }
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
    paint: { "line-color": "#4a4a4a", "line-width": ["interpolate", ["linear"], ["zoom"], 4, 0.15, 7, 0.3, 9, 0.6, 13, 2] },
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
    ["case", ["==", ["get", "value"], ""], "", ["concat", "\n", ["get", "value"]]], { "font-scale": 0.85 }];
  const valuesToggle = $<HTMLInputElement>("#values-toggle");
  const labelText = () => (valuesToggle.checked ? nameWithValue : nameOnly);
  const fitProp = () => (valuesToggle.checked ? "fitv" : "fit");
  const LABEL_TEXT_SIZES = { "pref-label": PREF_TEXT, "muni-label": MUNI_TEXT, "area-label": AREA_TEXT } as const;
  const labelSize = (layer: keyof typeof LABEL_TEXT_SIZES) => growingTextSize(LABEL_TEXT_SIZES[layer], fitProp()) as never;
  // 中央に置けないときは、少し上下左右にずらして置く（重なって消える地名を減らす。#96）
  const SHIFTABLE: Pick<MapLibre.SymbolLayerSpecification["layout"] & object, "text-variable-anchor" | "text-radial-offset" | "text-justify"> = {
    "text-variable-anchor": ["center", "top", "bottom", "left", "right"], "text-radial-offset": 0.2, "text-justify": "auto",
  };
  const labelPaint = { "text-color": "#1f2328", "text-halo-color": "rgba(255,255,255,0.92)", "text-halo-width": 1.6 };
  map.addLayer({
    id: "area-label", type: "symbol", source: "area-labels", minzoom: AREA_LABEL_ZOOM,
    layout: {
      "text-field": labelText() as never, "text-font": LABEL_FONT,
      "text-size": labelSize("area-label"),
      "text-max-width": 6, "text-padding": 0, ...SHIFTABLE,
    },
    paint: labelPaint,
  });
  map.addLayer({
    id: "pref-label", type: "symbol", source: "pref-labels", maxzoom: PREF_ZOOM,
    layout: { "text-field": labelText() as never, "text-font": LABEL_FONT, "text-size": labelSize("pref-label"), "text-padding": 1 },
    paint: { ...labelPaint, "text-halo-width": 2 },
  });
  map.addLayer({
    id: "muni-label", type: "symbol", source: "muni-labels", minzoom: MUNI_LABEL_ZOOM,
    layout: {
      "text-field": labelText() as never, "text-font": LABEL_FONT,
      "text-size": labelSize("muni-label"),
      "text-padding": 1, ...SHIFTABLE,
    },
    paint: { ...labelPaint, "text-halo-width": 2,
             "text-opacity": ["interpolate", ["linear"], ["zoom"], AREA_LABEL_ZOOM, 1, AREA_LABEL_ZOOM + 1, 0.55] },
  });

  // いまの指標・時点の凡例（区切りと、単位ごとの値のある地域の数）
  let legend: LegendFile | null = null;
  // 色分けできる値があるか。値の行はあってもすべて欠測の単位もある（市区町村に秘匿があって合計できない
  // 都道府県など）ので、凡例の数で確かめる。凡例を読む前は、あるものとして扱う
  const hasValues = (l: Level) => !legend || (legend.levels[l]?.count ?? 0) > 0;
  // 市区町村だけの指標（昼間人口など）は、拡大しても市区町村の色分けのまま表示する
  const municipalityOnly = () => !periodInfo().levels.includes("small_area");
  // 都道府県の値がない指標（合計できない指標など）は、縮小しても市区町村の色分けのまま
  const prefLevel = () => nationwide && periodInfo().levels.includes("prefecture") && hasValues("prefecture");
  // 都道府県だけの指標（学力テストなど）は、拡大しても都道府県の色分けのまま表示する
  const prefectureOnly = () => prefLevel() && !periodInfo().levels.includes("municipality");
  // その時点に値のある単位（都道府県は全国の公開版だけ）
  const available = (l: Level) => periodInfo().levels.includes(l) && (l !== "prefecture" || nationwide) && hasValues(l);
  // 手で選んだ単位（この指標・時点に値がなければ、自動と同じにする）
  const chosenLevel = (): Level | null => (levelMode !== "auto" && available(levelMode) ? levelMode : null);
  const areaZoom = () => (chosenLevel() === "small_area" ? MANUAL_AREA_ZOOM : AREA_ZOOM);
  const levelNow = (): Level => {
    const z = map.getZoom();
    const chosen = chosenLevel();
    if (chosen === "small_area" && z < MANUAL_AREA_ZOOM) return available("municipality") ? "municipality" : "prefecture";
    if (chosen) return chosen;
    if (prefLevel() && (z < PREF_ZOOM || prefectureOnly())) return "prefecture";
    return z >= AREA_ZOOM && !municipalityOnly() ? "small_area" : "municipality";
  };
  const LEVEL_LABEL: Record<Level, string> = { prefecture: "都道府県", municipality: "市区町村", small_area: "町丁・字等" };
  const SHORT_LEVEL: Record<Level, string> = { prefecture: "都道府県", municipality: "市区町村", small_area: "町丁目" };
  // 単位のアイコン: 1マス（都道府県）・2×2（市区町村）・3×3（町丁目）
  const gridIcon = (k: number) => {
    const d = 12 / k;
    const lines = Array.from({ length: k - 1 }, (_, i) => `M${1 + d * (i + 1)} 1V13M1 ${1 + d * (i + 1)}H13`).join("");
    return `<svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true"><rect x="1" y="1" width="12" height="12" rx="1.5"/>${lines ? `<path d="${lines}"/>` : ""}</svg>`;
  };
  const LEVEL_ICON: Record<Level, string> = { prefecture: gridIcon(1), municipality: gridIcon(2), small_area: gridIcon(3) };

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

  // 値を読んでいる間に指標・時点が変わったか（変わっていたら、古い値で塗ったり一覧を書いたりしない）
  const shownKey = () => `${indicator.id}/${period}`;

  async function paintPrefectures() {
    if (!nationwide) return;
    const key = shownKey();
    const v = prefLevel() ? await loadValues("prefectures") : null;
    if (key !== shownKey()) return;
    applyRows("prefs", areas.prefectures.map((p) => p.id), v?.rows);
    refreshLabels("prefs");
  }

  async function paintMunicipalities() {
    const key = shownKey();
    const v = periodInfo().levels.includes("municipality") ? await loadValues("municipalities") : null;
    if (key !== shownKey()) return;
    applyRows("munis", munis.keys(), v?.rows);
    refreshLabels("munis");
  }

  async function paintChunk(code: string) {
    const key = shownKey();
    // 町丁目の値がない時点（国勢調査の外国人の2010年など）は、ないファイルを読みにいかない
    const v = hasLevel(indicator, period, "small_area") ? await loadValues(code.slice(0, 2)) : null;
    if (key !== shownKey()) return;
    const ids = areaFeatures.features
      .filter((f) => municipalityCodeOf(f.properties.id) === code)
      .map((f) => f.properties.id);
    applyRows("areas", ids, v?.rows);
    refreshLabels("areas");
  }

  // 地名と、その下に添える値。値は色分けしている単位の地名にだけ添える（都道府県で塗っているときに市区町村の値を
  // 出さない）。都道府県名は都道府県の色分けのとき、または単位を選んで全国を見ているとき（名前だけ）に出す
  // 町丁目を選んだときは、町丁目で塗る縮尺（MANUAL_AREA_ZOOM）から町丁目名と値を出し、市区町村名は名前だけにする
  // （それより縮小して市区町村で塗っている間は、市区町村名に値を添える。#148）
  function syncLabels() {
    const on = $<HTMLInputElement>("#labels-toggle").checked;
    const chosen = chosenLevel();
    const text = (level: Level) => (chosen && chosen !== level ? nameOnly : labelText()) as never;
    const muniText = chosen === "small_area" ? ["step", ["zoom"], labelText(), MANUAL_AREA_ZOOM, nameOnly] : text("municipality");
    const prefMax = chosen === "prefecture" || (!chosen && prefectureOnly()) ? 24 : PREF_ZOOM;
    map.setLayerZoomRange("pref-label", 0, prefMax);
    map.setLayoutProperty("pref-label", "visibility", on && nationwide && (!!chosen || prefLevel()) ? "visible" : "none");
    map.setLayoutProperty("muni-label", "visibility", on && (!!chosen || !prefectureOnly()) ? "visible" : "none");
    map.setLayoutProperty("area-label", "visibility", on ? "visible" : "none");
    map.setLayoutProperty("pref-label", "text-field", text("prefecture"));
    map.setLayoutProperty("muni-label", "text-field", muniText as never);
    map.setLayoutProperty("area-label", "text-field", text("small_area"));
    for (const layer of ["pref-label", "muni-label", "area-label"] as const) map.setLayoutProperty(layer, "text-size", labelSize(layer));
    map.setLayerZoomRange("area-label", areaZoom(), 24);
    // 町丁目名が出る縮尺からは、市区町村名を薄くする
    map.setPaintProperty("muni-label", "text-opacity", ["interpolate", ["linear"], ["zoom"], areaZoom(), 1, areaZoom() + 1, 0.55]);
  }

  // 塗る層と縮尺の範囲。自動では、都道府県の値がある指標は縮小すると都道府県・拡大すると市区町村（さらに町丁目）で塗る。
  // 単位を選んだときは、どの縮尺でもその単位で塗る（町丁目は MANUAL_AREA_ZOOM より縮小したら市区町村）
  function syncLayers() {
    const chosen = chosenLevel();
    type Range = [number, number] | null;
    let pref: Range, muni: Range, area: Range;
    if (chosen === "prefecture") [pref, muni, area] = [[0, 24], null, null];
    else if (chosen === "municipality") [pref, muni, area] = [null, [0, 24], null];
    else if (chosen === "small_area") [pref, muni, area] = [null, available("municipality") ? [0, MANUAL_AREA_ZOOM] : null, [MANUAL_AREA_ZOOM, 24]];
    else {
      pref = prefLevel() ? [0, prefectureOnly() ? 24 : PREF_ZOOM] : null;
      muni = prefectureOnly() ? null : [prefLevel() ? PREF_ZOOM : 0, municipalityOnly() ? 24 : AREA_ZOOM];
      area = municipalityOnly() ? null : [AREA_ZOOM, 24];
    }
    for (const [layer, range] of [["pref-fill", pref], ["muni-fill", muni], ["area-fill", area]] as const) {
      if (range) map.setLayerZoomRange(layer, range[0], range[1]);
      map.setLayoutProperty(layer, "visibility", range ? "visible" : "none");
    }
    // 市区町村界は市区町村で塗る縮尺から（都道府県で塗るときは、拡大したら位置の目安に出す）
    map.setLayerZoomRange("muni-line", muni ? muni[0] : PREF_ZOOM, 24);
    map.setLayerZoomRange("area-line", area ? area[0] : AREA_ZOOM, 24);
    syncLabels();
  }

  let colorsToken = 0;
  async function refreshColors() {
    // 凡例を読んでいる間に指標・時点が変わったら（続けて切り替えた・再生中など）、古い凡例で塗らない
    const token = ++colorsToken;
    const next = await fetchJSON<LegendFile>(`values/${indicator.id}/${period}/legend.json`);
    if (token !== colorsToken) return;
    legend = next;
    syncLayers();
    // 区切りは全国で1つ（市区町村も都道府県ごとには変えない。#145）
    for (const [layer, level] of [["pref-fill", "prefecture"], ["muni-fill", "municipality"], ["area-fill", "small_area"]] as const) {
      map.setPaintProperty(layer, "fill-color",
        fillColorExpression(legend.scheme, legend.levels[level]?.breaks ?? [], legend.zero_blank) as never);
    }
    await Promise.all([paintPrefectures(), paintMunicipalities(), ...[...loadedChunks].map(paintChunk)]);
    loadVisibleChunks();
    renderLegend();
    syncLevelButtons();
    renderDetail();
  }

  // --- 町丁目の追加読み込み -----------------------------------------------------------
  function ensureChunk(code: string): Promise<void> {
    if (loadedChunks.has(code)) return Promise.resolve();
    if (!loadingChunks.has(code)) {
      loadingChunks.set(code, (async () => {
        // 名前・範囲・代表点は境界の properties に入っている。地図の地物には id と名前だけを残す
        const gj = await fetchJSON<SmallAreasFile>(`boundaries/${areas.boundary_version}/${code}.geojson`);
        for (const f of gj.features) {
          const { bbox, center, ...rest } = f.properties;
          smallAreas.set(rest.id, { ...rest, bbox, center });
          f.properties = rest as never;
        }
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

  // 町丁目で塗る縮尺なら、地図の中心に近い市区町村から町丁目の境界を読む
  function loadVisibleChunks() {
    if (map.getZoom() < areaZoom() - 0.5) return;
    const c = map.getCenter();
    visibleMunicipalities()
      .sort((a, b) => dist(a.center, c) - dist(b.center, c))
      .slice(0, chosenLevel() === "small_area" ? MAX_CHUNKS_MANUAL : MAX_CHUNKS_PER_MOVE)
      .forEach((m) => void ensureChunk(m.id.slice(5)));
  }
  map.on("moveend", () => {
    if (map.getZoom() >= FINE_MUNI_ZOOM) {
      visiblePrefectures().slice(0, MAX_PREFS_PER_MOVE).forEach((p) => void ensureFineMunis(p.code));
    }
    loadVisibleChunks();
    renderLegend();
    syncLevelButtons();
    renderAreaChip();
  });
  const dist = (p: [number, number], c: { lng: number; lat: number }) => (p[0] - c.lng) ** 2 + (p[1] - c.lat) ** 2;

  // --- 選択 ---------------------------------------------------------------------
  function entityName(id: string): { name: string } {
    if (isPref(id)) return { name: prefName(prefectureCodeOf(id)) };
    const m = munis.get(id);
    if (m) return { name: m.name };
    return { name: smallAreas.get(id)?.name ?? id };
  }

  // 地域を選んだら、地点（駅・学校など）の情報は閉じる（点レイヤーの準備ができてから差し替える）
  let closePoints = () => {};
  async function select(id: string | null, fly = false) {
    // 共有URLの町丁目（まだ境界を読んでいない）は、その市区町村の境界を読んでから選ぶ。見つからないとき
    // （ない地域ID、境界の更新でなくなった町丁目）は、その市区町村か、選ばない状態にする
    if (id && !isPref(id) && !munis.has(id) && !smallAreas.has(id)) {
      const code = municipalityCodeOf(id);
      const muniId = code && munis.has(`muni-${code}`) ? `muni-${code}` : null;
      if (muniId) await ensureChunk(code!).catch(() => {});
      if (!smallAreas.has(id)) return select(muniId, fly);
    }
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
        const a = smallAreas.get(id);
        if (a) map.fitBounds(a.bbox, { padding: 60, maxZoom: 15, minZoom: AREA_ZOOM });
      }
    }
    updateUrl();
    renderLegend();
    renderDetail();
    renderAreaChip();
  }

  // 点レイヤー（駅・空港・港・学校・地価（地価公示・都道府県地価調査）・保育所・道の駅・文化財・天気の観測所）。オンにしたときだけ読み込む
  const pickEl = $("#pick-detail");
  // 地点の情報は、押した点から出る地図の上のポップアップに出す。右の欄は地域（色分け）の情報だけにする（#139）。
  // 中身（駅・学校などの情報の欄と、重なった地点の一覧）は各点レイヤーが書き、開いている1つだけが見える
  const popupEl = $("#point-popup");
  const popup = new maplibregl.Popup({
    closeButton: false, closeOnClick: false, focusAfterOpen: false, maxWidth: "none", offset: 12, className: "point-popup-wrap",
  });
  const pointOptions = (toggle: string, legendSel: string, panel: string) => ({
    map, fetchJSON, sources, beforeLayer: "area-label", labelFont: LABEL_FONT,
    toggle: $<HTMLInputElement>(toggle), legend: $(legendSel), panel: $(panel),
    municipalityName: (id: string) => munis.get(id)?.name ?? "",
    onPanel: () => syncPanels(),
    focus,
  });
  // 共有URLの地点（?s=<駅ID> など）を開いたときは、その地点へ動かす。URL に地図の位置が入っていれば、その位置のままにする
  const focus: FocusPoint = (center, minZoom) => {
    if (!initial.view) map.jumpTo({ center, zoom: Math.max(map.getZoom(), minZoom) });
  };
  const pointLayers: PointLayer[] = [
    initStations(pointOptions("#stations-toggle", "#stations-legend", "#station-detail")),
    initTransport({ kind: "airport", ...pointOptions("#airports-toggle", "#airports-legend", "#airport-detail") }),
    initTransport({ kind: "port", ...pointOptions("#ports-toggle", "#ports-legend", "#port-detail") }),
    initSchools(pointOptions("#schools-toggle", "#schools-legend", "#school-detail")),
    initLandPrices(pointOptions("#land-toggle", "#land-legend", "#land-detail")),
    initNurseries(pointOptions("#nursery-toggle", "#nursery-legend", "#nursery-detail")),
    initFacilities({ kind: "michi", ...pointOptions("#michi-toggle", "#michi-legend", "#michi-detail") }),
    initFacilities({ kind: "bunka", ...pointOptions("#bunka-toggle", "#bunka-legend", "#bunka-detail") }),
    initWeather({ select: $<HTMLSelectElement>("#weather-select"),
      ...pointOptions("#weather-toggle", "#weather-legend", "#weather-detail") }),
  ];
  // 各点レイヤーが情報の欄を受け取ってから、欄をまとめてポップアップに移す（移すとページの中からは探せなくなる）
  popup.setDOMContent(popupEl);
  popupEl.hidden = false;
  // 重なった地点の一覧を出す位置（押した所）
  let pickAt: [number, number] | null = null;
  // 地点の情報を開いた・閉じた・別の地点にしたときに、ポップアップを開く・動かす・閉じる。
  // 位置が分からない地点（住所から位置を求められなかった学校など）は地図の真ん中に出す
  function syncPanels() {
    updateUrl();
    const open = pointLayers.find((p) => p.isOpen());
    const at = open ? open.coord() ?? map.getCenter().toArray() : !pickEl.hidden ? pickAt : null;
    if (!at) {
      popup.remove();
      return;
    }
    popupEl.style.maxHeight = `${popupMaxHeight()}px`;
    popupEl.scrollTop = 0;
    popup.setLngLat(at);
    if (!popup.isOpen()) popup.addTo(map);
    fitPopup();
  }
  // ポップアップの高さの上限（長い推移の表などはポップアップの中でスクロールする）。地図の高さの6割まで
  function popupMaxHeight() {
    return Math.round(Math.min(POPUP_MAX_PX, map.getContainer().clientHeight * 0.6));
  }
  // ポップアップが地図からはみ出す（左上の背景の切替に重なる）ときは、収まるまで地図を動かす
  function fitPopup() {
    requestAnimationFrame(() => {
      if (!popup.isOpen()) return;
      const c = map.getContainer().getBoundingClientRect();
      const r = popup.getElement().getBoundingClientRect();
      const top = c.top + POPUP_PAD.top, bottom = c.bottom - POPUP_PAD.bottom;
      const left = c.left + POPUP_PAD.side, right = c.right - POPUP_PAD.side;
      const dx = r.left < left ? r.left - left : r.right > right ? r.right - right : 0;
      const dy = r.top < top ? r.top - top : r.bottom > bottom ? r.bottom - bottom : 0;
      if (dx || dy) map.panBy([dx, dy], { duration: 300 });
    });
  }
  map.on("resize", () => {
    if (popup.isOpen()) popupEl.style.maxHeight = `${popupMaxHeight()}px`;
  });
  // Esc キーで閉じる（指標の選択画面を開いているときは、そちらを閉じるだけにする）
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && popup.isOpen() && !root.querySelector("dialog[open]")) showPoint(null, null);
  });
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
  // 地図に重ねている点の凡例（地図の右上）。見出しのボタンで畳める。
  // 地図の幅が狭いとき（スマホ）は地図を隠しすぎないよう、畳んで始める（#139）
  const notesToggle = $<HTMLButtonElement>("#overlay-notes-toggle");
  if (map.getContainer().clientWidth <= NARROW_MAP_PX) notesToggle.setAttribute("aria-expanded", "false");
  notesToggle.addEventListener("click", () =>
    notesToggle.setAttribute("aria-expanded", String(notesToggle.getAttribute("aria-expanded") !== "true")));
  const PICK_PX = 4; // クリック位置の周りこのピクセル以内の点を拾う
  map.on("click", (e) => {
    const box: [PointLike, PointLike] = [[e.point.x - PICK_PX, e.point.y - PICK_PX], [e.point.x + PICK_PX, e.point.y + PICK_PX]];
    const seen = new Set<string>();
    const hits = pointLayers.filter((p) => p.visible()).flatMap((layer) =>
      map.queryRenderedFeatures(box, { layers: [layer.layer] }).map((f) => ({
        layer, id: String(f.properties.id), name: String(f.properties.pick ?? f.properties.name),
      }))).filter((h) => !seen.has(`${h.layer.kind}:${h.id}`) && !!seen.add(`${h.layer.kind}:${h.id}`));
    if (hits.length === 1) return showPoint(hits[0].layer, hits[0].id);
    if (hits.length > 1) {
      pickAt = [e.lngLat.lng, e.lngLat.lat];
      return showPicker(hits);
    }
    // 点のない所を押したら、地点の情報（ポップアップ）を閉じる
    if (popup.isOpen()) showPoint(null, null);
    const f = map.queryRenderedFeatures(e.point, { layers: ["pref-fill", "muni-fill", "area-fill"] })[0];
    if (f) void select(String(f.properties.id));
  });
  for (const layer of ["pref-fill", "muni-fill", "area-fill"]) {
    map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
  }

  // --- 表示 ---------------------------------------------------------------------
  // 市区町村の一覧・凡例で見る都道府県: 選んだ地域の都道府県、なければ地図の中心にいちばん近い市区町村の都道府県。
  // 選んだ地域の都道府県が画面から外れたら（地域を選んだまま他県へ動かしたとき）、地図の中心の都道府県にする
  // （凡例の区切りを、画面に見えている市区町村の塗り分けと合わせるため）
  function focusPrefecture(): string | undefined {
    const visible = visibleMunicipalities();
    const own = selected ? prefectureCodeOf(selected) : null;
    if (own && (!visible.length || visible.some((m) => m.prefecture === own))) return own;
    return visible.sort((a, b) => dist(a.center, map.getCenter()) - dist(b.center, map.getCenter()))[0]?.prefecture ||
      own || areas.prefectures[0]?.code;
  }

  // ロゴの横の都道府県名: 地域を選んでいればその都道府県、市区町村が見える縮尺まで拡大していれば地図の中心の都道府県。
  // 全国を見ているときは出さない。変わったときだけ書き換える（地図を動かすたびに書き換えてちらつかないように）
  const areaChip = document.getElementById("area-chip");
  function renderAreaChip() {
    if (!areaChip || !nationwide) return;
    const code = (selected && prefectureCodeOf(selected)) || (map.getZoom() >= PREF_ZOOM ? focusPrefecture() : undefined);
    const name = prefName(code);
    if (areaChip.textContent !== name) areaChip.textContent = name;
    if (areaChip.hidden !== !name) areaChip.hidden = !name;
  }

  // 凡例の中身。左の欄の凡例と、保存する画像の凡例（#153）で同じものを使う
  function legendModel(): LegendModel | null {
    const level = levelNow();
    const info = legend?.levels[level];
    if (!legend || !info) return null;
    // 区切りは全国で共通（都道府県ごとには変えない。#145）
    const breaks = info.breaks;
    const zeroBlank = !!legend.zero_blank;
    const colors = colorsFor(legend.scheme, breaks, zeroBlank);
    const fmt = (v: number) => formatNumber(v, indicator.digits);
    // 区分で公表された値（就学援助率など）は、色ごとに区分の名前を出す（値は区分の上の端）
    const band = indicator.legend.band;
    const bandValue = (i: number) => (i === 0 ? 0 : breaks[i - 1]);
    const labels = colors.map((_, i) => {
      if (band) return bandLabel(bandValue(i), band, indicator.unit);
      const lo = i === 0 ? null : breaks[i - 1];
      const hi = i === breaks.length ? null : breaks[i];
      return lo === null && hi === null ? (zeroBlank ? "0 より大きい" : "すべて")
        : lo === null ? (zeroBlank ? `0 より大きく ${fmt(hi!)} 未満` : `${fmt(hi!)} 未満`)
        : hi === null ? `${fmt(lo)} 以上` : `${fmt(lo)} 〜 ${fmt(hi)} 未満`;
    });
    const n = colors.length;
    const ticks = band
      ? colors.map((_, i) => ({ at: (i + 0.5) / n, text: i === 0 ? "0" : `〜${compactNumber(bandValue(i), indicator.digits)}` }))
      : breaks.slice(0, n - 1).map((b, k) => ({ at: (k + 1) / n, text: compactNumber(b, indicator.digits) }));
    return { unit: indicator.unit, levelLabel: LEVEL_LABEL[level], colors, labels, ticks, band: !!band, zeroBlank,
             noDataColor: NO_DATA_COLOR };
  }

  // 凡例: 指標名は選択欄、時点は時点のバーにあるので、ここは単位と何別かだけ書き、色は1本の帯で示す（#93）
  function renderLegend() {
    if (!legend) return;
    const levelLabel = LEVEL_LABEL[levelNow()];
    // 町丁目を選んで縮小しているときは、市区町村で塗っていることを書き添える
    const later = chosenLevel() === "small_area" && levelNow() !== "small_area"
      ? `<p class="muted small legend-note">町丁目は拡大すると色分けされます。</p>` : "";
    const m = legendModel();
    if (!m) {
      legendEl.innerHTML = `<p class="muted small">この時点の${levelLabel}別の値はありません。</p>` + later;
      return;
    }
    const head = `<p class="legend-head">${esc(m.unit)}<span class="muted">（${esc(m.levelLabel)}別）</span></p>`;
    const noData = `<span><i class="swatch" style="background:${m.noDataColor}"></i>値なし</span>`;
    const blank = `<span><i class="swatch blank"></i>0（色なし）</span>`;
    const cells = m.colors.map((c, i) => `<span style="background:${c}" title="${esc(m.labels[i])}"></span>`).join("");
    // 区切りの値は帯の境目に、上下2段に互い違いに出す（色にカーソルを合わせると範囲も出る）。
    // 区分が多くて文字が重なるときは、いくつかおきに値を出し、残りの境目は目盛りだけにする（#145）
    const rows = m.colors.length > 6 ? 2 : 1;
    const width = legendEl.clientWidth || 260;
    const step = tickStep(m.ticks.map((t) => t.at * width), m.ticks.map((t) => textWidth(t.text, TICK_FONT_PX)), rows);
    const ticks = m.ticks.map((t, k) => {
      const style = `left:${(t.at * 100).toFixed(2)}%`;
      if (k % step) return m.band ? "" : `<span class="bare" style="${style}"></span>`;
      return `<span class="${rows > 1 && (k / step) % 2 ? "low" : ""}" style="${style}">${esc(t.text)}</span>`;
    }).join("");
    legendEl.innerHTML = head +
      `<div class="legend-bar" role="img" aria-label="${esc(m.labels.join("、"))}">${cells}</div>` +
      `<div class="legend-ticks${rows > 1 ? " two" : ""}" aria-hidden="true">${ticks}</div>` +
      `<p class="legend-extra">${m.zeroBlank ? blank : ""}${noData}</p>` + later;
  }

  async function rowsFor(id: string, at = period): Promise<ValueRow[]> {
    if (!hasLevel(indicator, at, levelOf(id))) return [];
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
    // 区分で公表された値も、区分の端どうしの差は意味がないので出さない
    const withChange = indicator.kind !== "change" && !indicator.legend.band;
    // 差は表に出している桁にそろえた値どうしで取る（94.4% → 94.5% が「±0.0」にならないように）
    const shownValue = (x: number) => Number(x.toFixed(indicator.digits));
    const body = rows.map(({ p, row }) => {
      const v = row?.value ?? null;
      let change = "";
      if (withChange && v !== null && prev !== null) {
        const diff = shownValue(v) - shownValue(prev);
        // 表示の桁で0になる差は「±」にする（−0.00 と出さない）
        const shown = Number(Math.abs(diff).toFixed(indicator.digits));
        const sign = shown === 0 ? "±" : diff > 0 ? "+" : "−";
        const amount = `${sign}${formatNumber(Math.abs(diff), indicator.digits)}`;
        // 割合（%）は差（ポイント）、人数などは差と増減率
        // 欄が狭いときは増減率を次の行に回す（1920年からの人口など、桁の大きい差で表がはみ出さないように）
        change = indicator.unit === "%" ? esc(`${amount}ポイント`)
          : prev ? `<span>${esc(amount)}</span><wbr><span>（${sign}${formatNumber(Math.abs(diff / prev) * 100, 1)}%）</span>`
          : esc(amount);
      }
      prev = v;
      return `<tr${p.period === period ? ' aria-current="true"' : ""}><td>${esc(trendLabel(p.label))}</td>
        <td class="num">${esc(formatValue(row, indicator))}</td>${withChange ? `<td class="num change">${change}</td>` : ""}</tr>`;
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
      if (!hasLevel(o, period, levelOf(id))) return "";
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
    return body ? `<section class="detail-compare"><h3>あわせて見る<span>同じ時点</span></h3><ul>${body}</ul></section>` : "";
  }

  // 政令指定都市の区を選んだときは、市全体の値も出す（区の分子・分母または人数を合計。1区でも値がなければ出さない）
  function cityTotal(id: string, rows: ValueRow[]): string {
    const m = munis.get(id);
    if (!m?.region || !m.name.startsWith(m.region) || !m.region.endsWith("市")) return "";
    const wards = [...munis.values()].filter((w) => w.prefecture === m.prefecture && w.region === m.region);
    if (wards.length < 2) return "";
    const byId = new Map(rows.map((r) => [r.entity_id, r]));
    const got = wards.map((w) => byId.get(w.id));
    let row: ValueRow | null = null;
    if (got.every((r) => r && r.value !== null && r.numerator != null && r.denominator != null)) {
      const num = got.reduce((a, r) => a + r!.numerator!, 0);
      const den = got.reduce((a, r) => a + r!.denominator!, 0);
      if (den > 0) row = { entity_id: id, value: (num / den) * (indicator.scale ?? 1), status: "derived", numerator: num, denominator: den };
    } else if (indicator.kind === "count" && got.every((r) => r && r.value !== null)) {
      row = { entity_id: id, value: got.reduce((a, r) => a + r!.value!, 0), status: "derived" };
    }
    if (!row) return "";
    const fraction = formatFraction(row, indicator);
    return `<div class="city-total"><span class="muted small">${esc(m.region)}全体（${wards.length}区の合計）</span>
      <strong>${esc(formatValue(row, indicator))}</strong>${fraction ? `<span class="muted small">${esc(fraction)}</span>` : ""}</div>`;
  }

  // 値の内訳（例: 1,337,033 人のうち 168,599 人）と求め方を1〜2行で書く（#95）
  function calcHtml(row: ValueRow | undefined, fraction: string | null): string {
    const basis = formatBasis(row, !!fraction);
    return (fraction ? `<div class="muted">${esc(fraction)}</div>` : "") +
      (basis.text ? `<div class="muted small">${esc(basis.text)}</div>` : "") +
      (basis.note ? `<p class="note small">${esc(basis.note)}</p>` : "");
  }

  // 順位: 範囲ごとに「〇〇の市区町村 19のうち」と順位を1行ずつ並べた表にする
  // （横バーと丸の印は動かせるつまみに見えたので使わない。設計変更記録 #135）
  type Rank = { scope: string; rank: number; total: number };
  function rankHtml(ranks: Rank[]): string {
    if (!ranks.length) return "";
    const items = ranks.map(({ scope, rank, total }) => `<div>
      <dt>${esc(scope)}<span class="of">${total.toLocaleString("ja-JP")}のうち</span></dt>
      <dd><strong>${rank.toLocaleString("ja-JP")}</strong>位</dd></div>`).join("");
    return `<section class="rank" aria-label="順位"><h3>順位<span>値の大きい順</span></h3><dl>${items}</dl></section>`;
  }

  // 順位は都道府県は全国の中、市区町村は都道府県内と全国、町丁・字等は区市町村内・都道府県内・全国で数える。
  // 値が1つの都道府県だけにある指標（東京都だけの指標など）は、全国の順位は都道府県内と同じなので出さない
  async function ranksFor(id: string, rows: ValueRow[], row: ValueRow | undefined): Promise<Rank[]> {
    const pick = (scope: string, group: ValueRow[]) => {
      const r = rankIfVaried(group, id);
      return r ? [{ scope, ...r }] : [];
    };
    const prefCode = prefectureCodeOf(id);
    const spansPrefectures = (group: ValueRow[]) =>
      new Set(group.filter((r) => r.value !== null).map((r) => prefectureCodeOf(r.entity_id))).size > 1;
    if (isPref(id)) return pick("全国の都道府県", rows.filter((r) => isPref(r.entity_id)));
    if (munis.has(id)) {
      const all = rows.filter((r) => munis.has(r.entity_id));
      return [
        ...pick(`${prefName(prefCode)}の市区町村`, all.filter((r) => prefectureCodeOf(r.entity_id) === prefCode)),
        ...(spansPrefectures(all) ? pick("全国の市区町村", all) : []),
      ];
    }
    const areasInPref = rows.filter((r) => !munis.has(r.entity_id) && !isPref(r.entity_id));
    const muniCode = municipalityCodeOf(id);
    const ranks = [
      ...pick(`${entityName(`muni-${muniCode}`).name}の町丁・字等`,
        areasInPref.filter((r) => municipalityCodeOf(r.entity_id) === muniCode)),
      ...pick(`${prefName(prefCode)}の町丁・字等`, areasInPref),
    ];
    if (row?.national_rank != null) {
      try {
        const total = (await fetchJSON<LegendFile>(`values/${indicator.id}/${period}/legend.json`))
          .levels.small_area?.count;
        if (total) ranks.push({ scope: "全国の町丁・字等", rank: row.national_rank, total });
      } catch {
        // 凡例が読めなければ全国の順位は出さない
      }
    }
    return ranks;
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
    // 公式サイトは、町丁・字等ではその市区町村のもの
    const homeId = isPref(id) || munis.has(id) ? id : `muni-${municipalityCodeOf(id)}`;
    const [rows, trend, compare, site] = await Promise.all([rowsFor(id), trendHtml(id), compareHtml(id), officialSite(homeId)]);
    if (token !== detailToken) return;
    const row = rows.find((r) => r.entity_id === id);
    const { name } = entityName(id);
    const isMuni = munis.has(id);
    const pref = isPref(id);
    const ranks = await ranksFor(id, rows, row);
    if (token !== detailToken) return;
    const city = isMuni ? cityTotal(id, rows) : "";
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
    // 題名は、その地域のページ（都道府県・市区町村）へのリンク。町丁・字等はページがないのでリンクにしない
    const page = pref ? `/prefectures/${prefectureCodeOf(id)}/` : isMuni ? `/areas/${id}/` : null;
    const title = page
      ? `<a href="${esc(page)}" title="${esc(name)}のデータをまとめたページへ">${esc(name)}${ICON_NEXT}</a>`
      : esc(name);
    detailEl.innerHTML = `
      ${crumbsHtml(id)}
      <h2 class="detail-title">${title}</h2>
      <div class="detail-figure">
        <p class="detail-indicator">${esc(indicator.name)}<span>${esc(p.label)}</span></p>
        <div class="value">${esc(formatValue(row, indicator))}</div>
        ${calcHtml(row, fraction)}
      </div>
      ${city}
      ${within ? `<p class="note small">この指標は都道府県別の値だけです（${esc(entityName(within).name)}を含む${esc(name)}の値）。</p>` : ""}
      ${!pref && !covers(prefectureCodeOf(id)) ? `<p class="note small">この指標は${esc(indicator.prefectures!.map(prefName).join("・"))}だけの値です。</p>` : ""}
      ${rankHtml(ranks)}
      ${compare}
      ${trend}
      <ul class="detail-links">
        ${site ? `<li><a href="${esc(site)}" target="_blank" rel="noopener">
          <span>${esc(entityName(homeId).name)}の公式サイト<small>別のタブで開きます</small></span>${ICON_EXTERNAL}</a></li>` : ""}
        <li><a href="/indicators/${esc(indicator.id)}/"><span>「${esc(indicator.name)}」の意味と注意点</span>${ICON_NEXT}</a></li>
      </ul>
      <p class="detail-sources">${srcHtml}<span aria-hidden="true">・</span><a href="/sources/">出典の一覧</a></p>`;
  }

  // 題名の上の「都道府県 › 郡・市」。都道府県名は都道府県のページ、町丁・字等の市区町村名は市区町村のページへのリンク
  function crumbsHtml(id: string): string {
    if (isPref(id)) return `<p class="detail-crumbs">都道府県</p>`;
    const code = prefectureCodeOf(id)!;
    const items = [`<a href="/prefectures/${esc(code)}/">${esc(prefName(code))}</a>`];
    const m = munis.get(id);
    const parent = `muni-${municipalityCodeOf(id)}`;
    if (m?.region) items.push(esc(m.region));
    else if (!m && munis.has(parent)) items.push(`<a href="/areas/${esc(parent)}/">${esc(entityName(parent).name)}</a>`);
    return `<p class="detail-crumbs">${items.join('<span class="sep" aria-hidden="true">›</span>')}</p>`;
  }

  // URL に入れる状態（#175）: 指標・時点・選んだ地域・色分けの単位に加えて、背景（航空写真の年代・土地利用の年度）、
  // 重ねた点と選んだ地点、既定から変えた表示（色分け・地名・数値）。地図の位置はアドレス欄には入れず
  // （ご要望フォームにも送られるため）、共有の画面のリンクにだけ入れる
  function urlState(): MapState {
    const show: string[] = [];
    const hide: string[] = [];
    const points: Record<string, string> = {};
    for (const layer of pointLayers) {
      const u = layer.urlState();
      if (u.show) show.push(u.show);
      Object.assign(points, u.params);
    }
    // 色分けは、背景が地図のときは表示、航空写真・標高・傾斜・土地利用のときは消すのが既定
    if (colorsToggle.checked !== (baseMode === "pale")) (colorsToggle.checked ? show : hide).push("colors");
    for (const t of ["labels", "values"]) if (!$<HTMLInputElement>(`#${t}-toggle`).checked) hide.push(t);
    const year = baseMode === "landuse" ? landUse.year() : null;
    const base = baseMode === "photo" ? photoEraId : baseMode === "landuse" ? `landuse${year ?? ""}`
      : baseMode === "relief" || baseMode === "slope" ? baseMode : undefined;
    return { indicator: indicator.id, period, area: selected ?? undefined,
             level: levelMode === "auto" ? undefined : levelMode, base, show, hide, points };
  }
  function updateUrl() {
    history.replaceState(null, "", `${location.pathname}${serializeState(urlState())}`);
  }

  // --- 指標・時点の選択 ---------------------------------------------------------------
  // 犯罪のように family でまとめた指標は、選択肢を1つにして「種別」「基準」で切り替える
  const optionValue = (i: Indicator) => (i.family ? `family:${i.family}` : i.id);
  const familyMembers = (family: string) => indicators.filter((i) => i.family === family);
  // 組の選択肢は種別を外した名前にする（例: 「通勤・通学の交通手段（鉄道・電車）」→「通勤・通学の交通手段」）
  const optionLabel = (i: Indicator) => (i.family ? i.name.replace(/（[^（）]*）$/, "") : i.name);
  // 見られる単位（都道府県・市区町村・町丁目）と対象の都道府県。選択肢の名前の後ろと、選択欄の下に出す
  const LEVELS: Level[] = ["prefecture", "municipality", "small_area"];
  const levelsOf = (list: Indicator[], at?: string): Set<Level> => new Set(list.flatMap((i) =>
    i.periods.filter((p) => !at || p.period === at).flatMap((p) => p.levels))
    .filter((l) => nationwide || l !== "prefecture"));
  const prefsOf = (list: Indicator[]): string[] | null => {
    if (list.some((i) => !i.prefectures)) return null;
    const codes = [...new Set(list.flatMap((i) => i.prefectures!))].sort();
    return codes.length >= areas.prefectures.length ? null : codes;
  };
  const coverageLabel = (codes: string[]) =>
    (codes.length <= 2 ? `${codes.map(prefName).join("・")}のみ` : `${codes.length}都道府県`);
  const scopeTag = (list: Indicator[]) => {
    const lv = levelsOf(list);
    const finest = lv.has("small_area") ? "町丁目まで" : lv.has("municipality") ? "市区町村まで" : "都道府県のみ";
    const prefs = nationwide ? prefsOf(list) : null;
    // 選択欄では後ろが切れやすいので、対象の都道府県を先に書く
    return `［${prefs ? `${coverageLabel(prefs)}・` : ""}${finest}］`;
  };
  const membersOf = (i: Indicator) => (i.family ? indicators.filter((o) => o.family === i.family) : [i]);
  indicatorSelect.innerHTML = [...new Set(indicators.map((i) => i.category))]
    .map((c) => {
      const seen = new Set<string>();
      const opts = indicators.filter((i) => i.category === c && !seen.has(optionValue(i)) && seen.add(optionValue(i)))
        .map((i) => `<option value="${esc(optionValue(i))}">${esc(`${optionLabel(i)} ${scopeTag(membersOf(i))}`)}</option>`).join("");
      return `<optgroup label="${esc(c)}">${opts}</optgroup>`;
    })
    .join("");
  // 指標の選択画面（#95）: 分類（ジャンル→カテゴリ、アイコン付き）ごとに指標を並べ、名前で絞り込める。
  // 選ぶと上の select の値を変える。各カテゴリには、そのカテゴリの点レイヤー（駅など）の表示切替も並べる
  const pickerEl = $<HTMLDialogElement>("#indicator-picker");
  const pickerList = pickerEl.querySelector<HTMLElement>(".picker-list")!;
  const pickerNav = pickerEl.querySelector<HTMLElement>(".picker-nav")!;
  const pickerSearch = $<HTMLInputElement>("#picker-search");
  const openButton = $<HTMLButtonElement>("#indicator-open");
  const iconTemplate = root.querySelector<HTMLTemplateElement>("#category-icons");
  const catIcon = (c: string, bubble = true) => {
    const el = iconTemplate?.content.querySelector(`[data-category="${CSS.escape(c)}"]`);
    if (!el) return "";
    return bubble ? el.innerHTML : el.querySelector("svg")?.outerHTML ?? "";
  };
  const POINT_LAYERS = [
    { toggle: "#stations-toggle", category: "交通" },
    { toggle: "#airports-toggle", category: "交通" },
    { toggle: "#ports-toggle", category: "交通" },
    { toggle: "#schools-toggle", category: "教育" },
    { toggle: "#land-toggle", category: "地価" },
    { toggle: "#nursery-toggle", category: "子育て" },
    { toggle: "#michi-toggle", category: "観光" },
    { toggle: "#bunka-toggle", category: "観光" },
    { toggle: "#weather-toggle", category: "天気" },
  ].filter((p) => root.querySelector(p.toggle));
  // 選択画面の点の切替は、左の欄のアイコンと同じもの（説明つきの名前で出す）
  const pointLabel = (sel: string) => root.querySelector(sel)?.closest("label")?.title ?? "";
  const pickerItem = (i: Indicator) => {
    const members = membersOf(i);
    const lv = levelsOf(members);
    const prefs = nationwide ? prefsOf(members) : null;
    const levels = LEVELS.filter((l) => lv.has(l)).map((l) => `<span title="${LEVEL_LABEL[l]}別">${LEVEL_ICON[l]}</span>`).join("");
    const finest = lv.has("small_area") ? "町丁目まで" : lv.has("municipality") ? "市区町村まで" : "都道府県のみ";
    return `<button type="button" class="picker-item" data-value="${esc(optionValue(i))}" data-key="${esc(normalize(optionLabel(i) + members.map((m) => m.name).join(" ")))}">
      <span class="pi-name">${esc(optionLabel(i))}</span>
      <span class="pi-meta">${levels}<span>${finest}</span>${prefs ? `<span class="limited">${esc(coverageLabel(prefs))}</span>` : ""}</span></button>`;
  };
  const pickerCats = [...new Set([...indicators.map((i) => i.category), ...POINT_LAYERS.map((p) => p.category)])];
  const pickerGenres = genresFor(pickerCats);
  pickerNav.innerHTML = pickerGenres.map((g, k) =>
    `<button type="button" data-genre="${k}">${catIcon(g.categories[0], false)}${esc(g.title)}</button>`).join("");
  pickerList.innerHTML = pickerGenres.map((g, k) => `<section class="picker-genre" id="picker-genre-${k}"><h3>${esc(g.title)}</h3>` +
    g.categories.map((c) => {
      const seen = new Set<string>();
      const items = indicators.filter((i) => i.category === c && !seen.has(optionValue(i)) && seen.add(optionValue(i))).map(pickerItem).join("");
      const points = POINT_LAYERS.filter((p) => p.category === c).map((p) =>
        `<label><input type="checkbox" data-toggle="${p.toggle}" /> ${esc(pointLabel(p.toggle))}</label>`).join("");
      return `<div class="picker-cat"><h4>${catIcon(c)}${esc(c)}</h4>` +
        (items ? `<div class="picker-grid">${items}</div>` : "") +
        (points ? `<div class="picker-points"><span class="muted">地図に点で重ねる:</span>${points}</div>` : "") + `</div>`;
    }).join("") + `</section>`).join("") + `<p class="picker-empty" hidden>見つかりませんでした。</p>`;
  function syncPicker() {
    const v = optionValue(indicator);
    for (const b of pickerList.querySelectorAll<HTMLElement>(".picker-item")) b.setAttribute("aria-current", String(b.dataset.value === v));
    for (const c of pickerList.querySelectorAll<HTMLInputElement>("input[data-toggle]")) c.checked = $<HTMLInputElement>(c.dataset.toggle!).checked;
    openButton.querySelector(".io-icon")!.innerHTML = catIcon(indicator.category, false);
    openButton.querySelector(".io-name")!.textContent = optionLabel(indicator);
    openButton.title = `指標を変える（今は「${optionLabel(indicator)}」）`;
  }
  function filterPicker() {
    const q = normalize(pickerSearch.value.trim());
    let any = false;
    for (const b of pickerList.querySelectorAll<HTMLElement>(".picker-item")) {
      const hit = !q || b.dataset.key!.includes(q);
      b.hidden = !hit;
      any ||= hit;
    }
    // 探しているときは、点の切替と、当てはまる指標のないカテゴリ・ジャンルを隠す
    for (const p of pickerList.querySelectorAll<HTMLElement>(".picker-points")) p.hidden = !!q;
    for (const c of pickerList.querySelectorAll<HTMLElement>(".picker-cat")) c.hidden = !!q && !c.querySelector(".picker-item:not([hidden])");
    for (const g of pickerList.querySelectorAll<HTMLElement>(".picker-genre")) g.hidden = !!q && !g.querySelector(".picker-cat:not([hidden])");
    pickerList.querySelector<HTMLElement>(".picker-empty")!.hidden = any;
  }
  openButton.addEventListener("click", () => {
    syncPicker();
    pickerSearch.value = "";
    filterPicker();
    pickerEl.showModal();
    // 今の指標が見えるところまで送る
    pickerList.querySelector<HTMLElement>('.picker-item[aria-current="true"]')?.scrollIntoView({ block: "center" });
    if (matchMedia("(min-width: 721px)").matches) pickerSearch.focus();
  });
  pickerEl.querySelector(".picker-close")!.addEventListener("click", () => pickerEl.close());
  // 選択画面の外（暗いところ）を押すと閉じる
  pickerEl.addEventListener("click", (e) => { if (e.target === pickerEl) pickerEl.close(); });
  pickerSearch.addEventListener("input", filterPicker);
  pickerNav.addEventListener("click", (e) => {
    const b = (e.target as HTMLElement).closest<HTMLElement>("button[data-genre]");
    if (b) pickerList.querySelector(`#picker-genre-${b.dataset.genre}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
  });
  pickerList.addEventListener("click", (e) => {
    const b = (e.target as HTMLElement).closest<HTMLElement>(".picker-item");
    if (!b) return;
    pickerEl.close();
    if (b.dataset.value !== indicatorSelect.value) {
      indicatorSelect.value = b.dataset.value!;
      indicatorSelect.dispatchEvent(new Event("change"));
    }
  });
  pickerList.addEventListener("change", (e) => {
    const c = e.target as HTMLInputElement;
    if (!c.dataset.toggle) return;
    const real = $<HTMLInputElement>(c.dataset.toggle);
    real.checked = c.checked;
    real.dispatchEvent(new Event("change"));
  });

  const unique = (xs: string[]) => [...new Set(xs)];
  // 色分けの単位（自動・都道府県・市区町村・町丁目）の切替と、対象の都道府県（#146）。
  // 単位はアイコン（区切りが細かいほどマス目が多い）付きのボタン。どの時点にも値のない単位は出さない（#93）
  function renderScope() {
    const all = levelsOf([indicator]);
    const buttons = [
      `<button type="button" data-level="auto" title="縮尺に合わせて切り替えます（縮小すると都道府県、拡大すると市区町村・町丁目）">自動</button>`,
      ...LEVELS.filter((l) => all.has(l)).map((l) =>
        `<button type="button" data-level="${l}">${LEVEL_ICON[l]}${SHORT_LEVEL[l]}</button>`),
    ].join("");
    const prefs = nationwide ? prefsOf([indicator]) : null;
    const area = prefs ? coverageLabel(prefs) : "全国";
    scopeEl.innerHTML = `<div class="scope-head"><span id="scope-label">色分けの単位</span>` +
      `<span class="scope-area${prefs ? " limited" : ""}" title="${prefs ? `対象: ${esc(area)}（ほかの地域は値なし）` : "対象: 全国"}">${esc(area)}</span></div>` +
      `<div class="scope-levels" role="group" aria-labelledby="scope-label">${buttons}</div>`;
    syncLevelButtons();
  }
  // 町丁目は、町丁目で塗れる縮尺（MANUAL_AREA_ZOOM）まで拡大したときだけ押せる（#148）
  const zoomedForAreas = () => map.getZoom() >= MANUAL_AREA_ZOOM;
  const selectable = (l: Level) => available(l) && (l !== "small_area" || zoomedForAreas());
  // 単位のボタンの説明（この時点に値のない単位と、縮小しているときの町丁目は押せない）
  const levelTitle = (l: Level) =>
    !periodInfo().levels.includes(l) ? `${LEVEL_LABEL[l]}別は、ほかの時点で見られます（この時点は値なし）`
      : !available(l) ? `この時点の${LEVEL_LABEL[l]}別の値はありません`
      : l !== "small_area" ? `どの縮尺でも${LEVEL_LABEL[l]}で色分けします`
      : zoomedForAreas() ? "町丁目で色分けします（縮小すると市区町村）"
      : chosenLevel() === "small_area" ? "地図を拡大すると町丁目で色分けします（いまは市区町村）"
      : "地図を拡大すると選べます";
  // 押されているボタン（選んだ単位、選んでいなければ「自動」）と、今塗っている単位の印（自動のとき、
  // または町丁目を選んで縮小しているとき）
  function syncLevelButtons() {
    const chosen = chosenLevel();
    const shown = levelNow();
    for (const b of scopeEl.querySelectorAll<HTMLButtonElement>("button[data-level]")) {
      const mode = b.dataset.level as LevelMode;
      if (mode !== "auto") {
        b.disabled = !selectable(mode);
        b.title = levelTitle(mode);
      }
      b.setAttribute("aria-pressed", String(mode === (chosen ?? "auto")));
      b.classList.toggle("shown", mode === shown && mode !== chosen);
    }
  }
  scopeEl.addEventListener("click", (e) => {
    const b = (e.target as HTMLElement).closest<HTMLButtonElement>("button[data-level]");
    if (!b || b.disabled) return;
    setLevelMode(b.dataset.level as LevelMode);
  });
  function setLevelMode(mode: LevelMode) {
    levelMode = mode;
    syncLayers();
    loadVisibleChunks();
    renderLegend();
    syncLevelButtons();
    updateUrl();
  }
  function syncIndicatorControls() {
    indicatorSelect.value = optionValue(indicator);
    syncPicker();
    facetsEl.hidden = !indicator.family;
    if (!indicator.family || !indicator.facets) return;
    const members = familyMembers(indicator.family);
    const { type, basis } = indicator.facets;
    facetType.innerHTML = unique(members.map((m) => m.facets!.type))
      .map((t) => `<option${t === type ? " selected" : ""}>${esc(t)}</option>`).join("");
    facetBasis.innerHTML = unique(members.filter((m) => m.facets!.type === type).map((m) => m.facets!.basis))
      .map((b) => `<option${b === basis ? " selected" : ""}>${esc(b)}</option>`).join("");
    // 種別・基準が1つしかない組（交通事故の種別ごとの組など）は、選べないので欄ごと隠す
    facetTypeWrap.hidden = unique(members.map((m) => m.facets!.type)).length < 2;
    facetBasisWrap.hidden = unique(members.map((m) => m.facets!.basis)).length < 2;
    facetsEl.hidden = facetTypeWrap.hidden && facetBasisWrap.hidden;
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
      // 時点が多いとき（犯罪の年ごとなど）は「’19」のように短くして1行に収める。
      // さらに多いとき（1920年からの人口など）は間引いて、端と一定間隔の時点だけ文字を出す
      .map((p, i) => {
        const step = ps.length > 12 ? Math.ceil(ps.length / 6) : 1;
        const shown = i === ps.length - 1 || (i % step === 0 && ps.length - 1 - i >= step / 2);
        const text = ps.length > 4 ? shortLabel(p.label).replace(/^\d{2}(\d{2})年$/, "’$1") : shortLabel(p.label);
        return `<span data-i="${i}"${p.period === period ? ' aria-current="true"' : ""} title="${esc(p.label)}">${
          shown ? esc(step > 1 ? shortLabel(p.label).replace(/年$/, "") : text) : ""}</span>`;
      })
      .join("");
    periodLabel.value = periodInfo().label;
    periodNote.hidden = ps.length > 1;
    periodNote.textContent = ps.length > 1 ? "" : "この指標は1時点のみです。";
    periodField.classList.toggle("aggregate", onAggregate);
    aggregateWrap.hidden = !agg;
    aggregateToggle.checked = onAggregate;
    renderScope();
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
    // 合計を最初に出す指標（町丁目の値が合計にだけある指標）では、外したときに最新の年へ
    const annual = annualPeriods();
    const latestAnnual = annual[annual.length - 1]?.period;
    period = aggregateToggle.checked && agg ? agg.period
      : indicator.default_period === agg?.period && latestAnnual ? latestAnnual : indicator.default_period;
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
  // 背景（地図・航空写真・標高・傾斜・土地利用）は地図の左上の切替でどれか1つを選ぶ（#128・#177）。航空写真の撮影年代・土地利用の年度の
  // スライドバーと標高・傾斜の色の見本は地図の上のパネルに置き、見ている年代・年度が地図と一緒に分かるようにする
  const baseButtons = [...root.querySelectorAll<HTMLButtonElement>(".base-switch button")];
  const photoPanel = $<HTMLElement>("#photo-panel");
  const photoRange = $<HTMLInputElement>("#photo-era-range");
  const photoLabel = $<HTMLOutputElement>("#photo-era-label");
  const photoEnds = $<HTMLElement>("#photo-era-ends");
  const photoPlay = $<HTMLButtonElement>("#photo-era-play");
  const photoNote = $<HTMLElement>("#photo-note");
  const reliefPanel = $<HTMLElement>("#relief-panel");
  const reliefNote = $<HTMLElement>("#relief-note");
  const slopePanel = $<HTMLElement>("#slope-panel");
  const slopeNote = $<HTMLElement>("#slope-note");
  // 土地利用図（#123）。土地利用図のない公開版では切替を出さない
  const landUseSource = sourcesFile.sources.find((s) => s.dataset_key === "land_use_tiles");
  baseButtons.find((b) => b.dataset.basemap === "landuse")!.hidden = !landUseSource;
  const landUse = initLandUse({
    maplibregl, map, base, fetchJSON, source: landUseSource,
    panel: $("#landuse-panel"), range: $<HTMLInputElement>("#landuse-year"), label: $<HTMLOutputElement>("#landuse-year-label"),
    ticks: $("#landuse-year-ticks"), play: $<HTMLButtonElement>("#landuse-play"),
    legend: $("#landuse-legend"), legendToggle: $<HTMLButtonElement>("#landuse-legend-toggle"),
    note: $("#landuse-note"),
    onYear: () => updateUrl(),
    // 背景の地図のすぐ上（境界の塗り・線・地名より下）
    beforeLayer: () => map.getStyle().layers.find((l) => l.id !== "pale" && !BASEMAPS.some((b) => b.id === l.id))?.id,
  });
  let baseMode: "pale" | "photo" | "relief" | "slope" | "landuse" = "pale";
  // 写真・標高・傾斜・土地利用図を出すときは色分けを消して背景を見やすくし、閉じたら元に戻す
  let colorsBeforeBase: boolean | null = null;
  function setBaseMode(next: typeof baseMode) {
    if (next === baseMode) return;
    stopPhotoPlay();
    if (baseMode === "pale" && next !== "pale") {
      colorsBeforeBase = colorsToggle.checked;
      if (colorsToggle.checked) { colorsToggle.checked = false; colorsToggle.dispatchEvent(new Event("change")); }
    } else if (next === "pale" && colorsBeforeBase !== null) {
      if (colorsToggle.checked !== colorsBeforeBase) {
        colorsToggle.checked = colorsBeforeBase;
        colorsToggle.dispatchEvent(new Event("change"));
      }
      colorsBeforeBase = null;
    }
    baseMode = next;
    syncBasemap();
    refreshPhotoEras();
  }
  // 地図の中央に写っている年代だけをスライドバーに並べる（#162）。表示する縮尺に近いタイルの画像を縮めて読み、
  // 中央の範囲の半分以上が写っているかで判断する（photoEras.ts）。タイルごとの写り方は覚えておく
  const photoMasks = new Map<string, Promise<Uint8Array | null>>();
  const maskCanvas = document.createElement("canvas");
  maskCanvas.width = maskCanvas.height = PHOTO_MASK_SIZE;
  const maskContext = maskCanvas.getContext("2d", { willReadFrequently: true });
  let photoEras: typeof PHOTO_ERAS = PHOTO_ERAS.filter((e) => e.id === "photo");
  let photoEraId = "photo";
  let photoChecked = false;   // 縮小したまま航空写真を出したときは、拡大するまで確かめない
  async function readPhotoMask(blob: Blob): Promise<Uint8Array | null> {
    if (!maskContext) return null;
    const image = await createImageBitmap(blob);
    // 描いてから読むまでの間に await を挟まない（ほかのタイルと canvas を取り合わないように）
    maskContext.clearRect(0, 0, PHOTO_MASK_SIZE, PHOTO_MASK_SIZE);
    maskContext.drawImage(image, 0, 0, PHOTO_MASK_SIZE, PHOTO_MASK_SIZE);
    image.close();
    return photoMask(maskContext.getImageData(0, 0, PHOTO_MASK_SIZE, PHOTO_MASK_SIZE).data);
  }
  function photoTileMask(era: (typeof PHOTO_ERAS)[number], z: number, x: number, y: number): Promise<Uint8Array | null> {
    const key = `${era.path}/${z}/${x}/${y}`;
    let p = photoMasks.get(key);
    if (!p) {
      if (photoMasks.size >= PHOTO_MASK_CACHE_MAX) photoMasks.clear();
      const url = era.tiles.replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y));
      // タイルがない（404）・画像が読めないときは写っていないとする。通信の失敗は覚えず、次に確かめるときに読み直す
      p = fetch(url).then(
        (r) => (r.ok ? r.blob().then(readPhotoMask).catch(() => null) : null),
        () => { photoMasks.delete(key); return null; },
      );
      photoMasks.set(key, p);
    }
    return p;
  }
  async function photoEraShare(era: (typeof PHOTO_ERAS)[number]): Promise<number> {
    const container = map.getContainer();
    const { z, samples } = photoSamples(map.getCenter(), map.getZoom(), container.clientWidth, container.clientHeight, era);
    const tiles = [...new Set(samples.map((s) => `${s.x}/${s.y}`))];
    const masks = await Promise.all(tiles.map((t) => {
      const [x, y] = t.split("/").map(Number);
      return photoTileMask(era, z, x, y);
    }));
    return photoShare(samples, new Map(tiles.map((t, i) => [t, masks[i]])));
  }
  let photoCheck = 0;
  async function refreshPhotoEras() {
    if (baseMode !== "photo" || map.getZoom() < 10) return;   // 縮小しているときは前の結果のまま
    const check = ++photoCheck;
    const shares = await Promise.all(PHOTO_ERAS.map((e) => e.id === "photo" ? 1 : photoEraShare(e)));
    if (check !== photoCheck || baseMode !== "photo") return;   // 確かめている間に地図が動いた
    photoEras = PHOTO_ERAS.filter((_, i) => shares[i] >= PHOTO_MIN_SHARE);
    photoChecked = true;
    // 選んでいた年代がこの場所にないときは、いちばん近い年代にする
    if (!photoEras.some((e) => e.id === photoEraId)) {
      const want = PHOTO_ERAS.findIndex((e) => e.id === photoEraId);
      photoEraId = photoEras.reduce((best, e) => Math.abs(PHOTO_ERAS.indexOf(e) - want)
        < Math.abs(PHOTO_ERAS.indexOf(best) - want) ? e : best).id;
    }
    syncBasemap();
  }
  function chosenBasemap() {
    return baseMode === "photo" ? PHOTO_ERAS.find((e) => e.id === photoEraId)
      : baseMode === "relief" || baseMode === "slope" ? BASEMAPS.find((b) => b.id === baseMode) : undefined;
  }
  function syncBasemap() {
    updateUrl();
    const chosen = chosenBasemap();
    for (const b of BASEMAPS) map.setLayoutProperty(b.id, "visibility", b === chosen ? "visible" : "none");
    const photo = baseMode === "photo";
    for (const b of baseButtons) b.setAttribute("aria-pressed", String(b.dataset.basemap === baseMode));
    photoPanel.hidden = !photo;
    reliefPanel.hidden = baseMode !== "relief";
    slopePanel.hidden = baseMode !== "slope";
    void landUse.setVisible(baseMode === "landuse");
    // 256px のタイルは「地図の縮尺 + 1」を丸めたズームのタイルで描かれ（MapLibre の raster）、それが minzoom 未満だと何も出ない
    const zoomIn = chosen && Math.round(map.getZoom() + 1) < chosen.minzoom;
    for (const note of [reliefNote, slopeNote]) {
      note.hidden = !zoomIn;
      note.textContent = zoomIn ? "拡大すると表示されます。" : "";
    }
    if (!photo || !chosen) return;
    photoRange.max = String(photoEras.length - 1);
    photoRange.value = String(Math.max(0, photoEras.findIndex((e) => e.id === photoEraId)));
    photoRange.disabled = photoEras.length < 2;
    photoPlay.disabled = photoEras.length < 2;
    photoLabel.value = chosen.id === "photo" ? "最新の写真" : `${chosen.label}の写真`;
    photoEnds.hidden = photoEras.length < 2;
    photoEnds.innerHTML = photoEras.length < 2 ? ""
      : `<span>${esc(photoEras[0].label)}</span><span>${esc(photoEras[photoEras.length - 1].label)}</span>`;
    // 年代別の写真は拡大したときだけ出る。撮られていない地域もあり、そこは淡色地図のまま
    photoNote.textContent = zoomIn ? "拡大すると表示されます。"
      : photoEras.length > 1 ? "地図の中央に写っている年代だけを並べています。"
      : photoChecked ? "この場所の昔の写真は見つかりませんでした。"
      : map.getZoom() < 10 ? "拡大すると、昔の写真を年代を選んで見られます。" : "この場所の写真の年代を確かめています。";
  }
  for (const b of baseButtons) b.addEventListener("click", () => setBaseMode(b.dataset.basemap as typeof baseMode));
  // パネルの × は地図（淡色地図）に戻す
  for (const b of root.querySelectorAll<HTMLButtonElement>(".base-close")) b.addEventListener("click", () => setBaseMode("pale"));
  photoRange.addEventListener("input", () => {
    stopPhotoPlay();
    photoEraId = photoEras[Number(photoRange.value)]?.id ?? "photo";
    syncBasemap();
  });
  // 再生: 地図の中央に写っている年代を古い順に送り、最新まで来たら止める（途中で地図を動かしてもよい）
  // 途中で止めたときは、次の再生をその年代から続ける。最新の写真のときだけ最初の年代から
  let photoTimer: number | undefined;
  function stopPhotoPlay() {
    clearInterval(photoTimer);
    photoTimer = undefined;
    photoPlay.setAttribute("aria-pressed", "false");
    photoPlay.textContent = "▶";
  }
  photoPlay.addEventListener("click", () => {
    if (photoTimer !== undefined) return stopPhotoPlay();
    photoPlay.setAttribute("aria-pressed", "true");
    photoPlay.textContent = "■";
    const at = photoEras.findIndex((e) => e.id === photoEraId);
    if (at < 0 || at === photoEras.length - 1) {
      photoEraId = photoEras[0].id;
      syncBasemap();
    }
    photoTimer = window.setInterval(() => {
      const next = photoEras[photoEras.findIndex((e) => e.id === photoEraId) + 1];
      if (!next) return stopPhotoPlay();
      photoEraId = next.id;
      syncBasemap();
    }, PHOTO_PLAY_INTERVAL_MS);
  });
  map.on("zoomend", () => { if (baseMode !== "pale") syncBasemap(); });
  map.on("moveend", () => refreshPhotoEras());
  // 色分けを消して、背景地図と地名・数値だけで見る（地域のクリックはそのまま使える）
  colorsToggle.addEventListener("change", () => {
    const on = colorsToggle.checked;
    map.setPaintProperty("muni-fill", "fill-opacity", on ? MUNI_OPACITY : 0);
    map.setPaintProperty("pref-fill", "fill-opacity", on ? MUNI_OPACITY : 0);
    map.setPaintProperty("area-fill", "fill-opacity", on ? AREA_OPACITY : 0);
    legendEl.classList.toggle("dimmed", !on);
    // 色分けを消したときは背景地図の彩度を落とし、駅・学校などの点や文字と混ざらないようにする。
    // 航空写真・標高は色そのものが見るもので、出すと色分けが消えるので、彩度は落とさない（#127）
    map.setPaintProperty("pale", "raster-saturation", on ? 0 : -1);
    map.setPaintProperty("pale", "raster-contrast", on ? 0 : -0.15);
  });
  const labelsToggle = $<HTMLInputElement>("#labels-toggle");
  labelsToggle.addEventListener("change", syncLabels);
  valuesToggle.addEventListener("change", syncLabels);
  // 表示・重ねる点の切替や天気の指標を変えたら、URL も変える（それぞれの処理のあとに動くよう、地図の画面全体で受ける）
  root.addEventListener("change", (e) => {
    if ((e.target as HTMLElement).matches("input[type=checkbox], select")) updateUrl();
  });
  // 範囲: 全国・都道府県（都道府県コードの順。東京都は島しょも、沖縄県の次に南西諸島）。
  // 都道府県の範囲は離島を含むので、県庁所在地側に寄らないこともある
  const regionJump = $<HTMLSelectElement>("#region-jump");
  const regionOptions = (p: { code: string; name: string }) =>
    p.code === "13" ? '<option value="mainland">東京都（区部・多摩）</option><option value="izu">東京都（伊豆諸島）</option>' +
      '<option value="ogasawara">東京都（小笠原諸島）</option>'
    : `<option value="pref:${esc(p.code)}">${esc(p.name)}</option>` +
      (p.code === "47" ? '<option value="okinawa">沖縄・南西諸島</option>' : "");
  regionJump.innerHTML = (areas.prefectures.length > 1 ? '<option value="japan">全国</option>' : "") +
    [...areas.prefectures].sort((a, b) => a.code.localeCompare(b.code)).map(regionOptions).join("");
  regionJump.value = areas.prefectures.length > 1 ? "japan" : "mainland";
  regionJump.addEventListener("change", () => {
    const v = regionJump.value;
    const bounds = v.startsWith("pref:") ? prefectures.get(v.slice(5))?.bbox : PRESETS[v];
    if (bounds) map.fitBounds(bounds as LngLatBoundsLike, { padding: 20 });
  });
  // 条件の欄の「現在地へ移動」も地図の現在地ボタンと同じ動き（マークを出して移動する）
  $<HTMLButtonElement>("#locate").addEventListener("click", () => {
    if (!navigator.geolocation) return alert("このブラウザでは現在地を使えません。");
    geolocate.trigger();
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
    // 都道府県ごとの町丁・字等の索引は、1つずつ待たずにまとめて読む（加える順はこれまでどおり）
    const files = await Promise.all([...new Set(wanted)].map((code) => {
      searchedPrefs.add(code);
      return fetchJSON<SearchIndex>(`search-index/${code}.json`).catch(() => null); // 町丁・字等の索引がない都道府県
    }));
    for (const f of files) if (f) searcher.add(f);
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

  // --- 画像の保存・共有（#153） -------------------------------------------------------
  // 画像の題名・凡例・出典は、いま地図に出しているもの（色分けを消しているときは背景の名前）にする
  const BASE_TITLE = { pale: "地図", photo: "航空写真", relief: "標高（色別標高図）", slope: "傾斜（標高から計算）",
                       landuse: "土地利用（100m四方のマス）" };
  const attributionEl = root.querySelector<HTMLElement>(".maplibregl-ctrl-attrib-inner");
  // 出典の表記は「出典：」で始まるものが多いので、行の見出し（「統計の出典:」など）と重ならないように外す
  const attributions = (ids: string[]) =>
    [...new Set(ids.map((id) => (sources.get(id)?.attribution ?? id).replace(/^出典[：:]\s*/, "")))].join("／");
  // 背景の凡例（色分けを消して土地利用・標高・傾斜を見ているとき）
  const baseLegend = (): BaseLegend | null =>
    baseMode === "landuse" && landUse.legend().length
      ? { title: "土地利用の区分", items: landUse.legend().map((c) => ({ color: c.color, label: c.name })) }
      : baseMode === "relief"
        ? { title: "標高", gradient: { stops: RELIEF_STOPS.map((st, i) => ({ at: reliefAt(i), color: st.color })),
                                     ticks: RELIEF_STOPS.flatMap((st, i) => (st.tick ? [{ at: reliefAt(i), text: st.tick }] : [])) } }
        : baseMode === "slope"
          ? { title: "傾斜（3度未満は色なし）",
              items: SLOPE_CLASSES.flatMap((c) => (c.color ? [{ color: c.color, label: c.label }] : [])) }
          : null;
  initShare({
    map, root, font: LOCAL_FONT,
    // 共有用のリンクは、アドレス欄と同じ状態に地図の位置と縮尺を足したもの（#175）
    link: (withView) => {
      const c = map.getCenter();
      const view = withView ? { zoom: map.getZoom(), lat: c.lat, lng: c.lng, bearing: map.getBearing(), pitch: map.getPitch() } : undefined;
      return `${location.origin}${location.pathname}${serializeState({ ...urlState(), view })}`;
    },
    view: () => {
      const colorsOn = colorsToggle.checked;
      // 色分けを消していても、地名の下に数値を出しているときは、何の数値かと出典を書く
      const valuesShown = $<HTMLInputElement>("#labels-toggle").checked && valuesToggle.checked;
      const p = periodInfo();
      const area = selected ? entityName(selected).name : "";
      const lm = colorsOn ? legendModel() : null;
      const baseLabel = baseMode === "photo" ? photoLabel.textContent ?? ""
        : baseMode === "landuse" ? $<HTMLOutputElement>("#landuse-year-label").textContent ?? "" : "";
      const title = colorsOn ? indicator.name : BASE_TITLE[baseMode];
      const when = colorsOn ? p.label : baseLabel;
      // 色分けの下に航空写真などを出しているときは、背景が何かも書く
      const era = baseMode === "photo" ? chosenBasemap() : undefined;
      const underneath = !colorsOn || baseMode === "pale" ? ""
        : baseMode === "photo" ? `背景は${era?.id === "photo" ? "最新" : era?.label ?? ""}の航空写真`
        : baseMode === "landuse" ? `背景は${baseLabel}` : baseMode === "slope" ? "背景は傾斜" : "背景は色別標高図";
      const subtitle = [when, lm ? `${lm.levelLabel}別` : "",
        !colorsOn && valuesShown ? `数値は${indicator.name}（${p.label}）` : "", area ? `赤い枠は${area}` : "", underneath]
        .filter(Boolean).join("・");
      const pointIds = pointLayers.filter((l) => l.visible()).flatMap((l) => l.sourceIds());
      const credits = [
        (colorsOn || valuesShown) && p.source_ids.length ? `統計の出典: ${attributions(p.source_ids)}` : "",
        pointIds.length ? `地点の出典: ${attributions(pointIds)}` : "",
        `背景地図: ${attributionEl?.textContent?.trim() || "地理院タイル"}`,
      ].filter(Boolean);
      return { title, subtitle, legend: lm, base: colorsOn ? null : baseLegend(), credits,
               fileName: safeFileName(`データさんぽ_${[title, when, area].filter(Boolean).join("_")}.png`) };
    },
  });

  // --- 初期表示 -------------------------------------------------------------------
  // 共有URLの背景（?b=photo1945・relief・slope・landuse2021 など。#175）。?show=landuse で開いたときも土地利用図を出す
  // （トップページの指標の一覧から。ほかの重ねる層の ?show= と同じ）
  const initialBase = initial.base ?? (initial.show?.includes("landuse") ? "landuse" : undefined);
  if (initialBase && PHOTO_ERAS.some((e) => e.id === initialBase)) {
    photoEraId = initialBase;
    setBaseMode("photo");
  } else if (initialBase === "relief" || initialBase === "slope") {
    setBaseMode(initialBase);
  } else if (landUseSource && initialBase && /^landuse(\d{4})?$/.test(initialBase)) {
    if (initialBase.length > 7) landUse.chooseYear(Number(initialBase.slice(7)));
    setBaseMode("landuse");
  }
  // 既定から変えた表示（?show=colors・?hide=colors,labels,values）。色分けは背景に合わせた既定（setBaseMode）から変える
  const colorsWanted = initial.show?.includes("colors") ? true : initial.hide?.includes("colors") ? false : colorsToggle.checked;
  if (colorsToggle.checked !== colorsWanted) {
    colorsToggle.checked = colorsWanted;
    colorsToggle.dispatchEvent(new Event("change"));
  }
  if (initial.hide?.includes("labels")) labelsToggle.checked = false;
  if (initial.hide?.includes("values")) valuesToggle.checked = false;
  await refreshColors();
  if (initial.area && (munis.has(initial.area) || municipalityCodeOf(initial.area) ||
      (isPref(initial.area) && prefectures.has(prefectureCodeOf(initial.area)!)))) {
    // 地図の位置が URL にあるときは、地域を選ぶだけで地図は動かさない
    await select(initial.area, !initial.view);
  } else {
    updateUrl();
  }
}
