// 地価の点レイヤー。地価公示（国土数値情報「地価公示データ」、1月1日時点の標準地）と都道府県地価調査
// （「都道府県地価調査データ」、7月1日時点の基準地）を、1つの「地価」の表示にまとめて出す（docs/design-changes.md #134）。
// 地点ごとの最新の価格（円/㎡）で円を塗り分け、地価調査の基準地は縁の色で見分ける。
// 同じ土地を両方で調べている地点（共通地点）は1つの点にし、ポップアップに両方の価格を時点の順に並べる（pairLandPoints）。
// 表示をオンにしたときに初めて places/<指標>.json を読み込み、地点の一覧は地図に映っている
// 都道府県の分だけ読む（createPrefLoader）。
// 地域の平均ではなく選ばれた1地点の価格であることを凡例と詳細に明記する。
// 価格は住宅地の数万円から都心の商業地の数千万円まで桁が違うので、切りのよい桁ごとの区切りで色を分ける。
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import { createPrefLoader, PLACES_MIN_ZOOM, type PointLayer, sourcesHtml } from "./points";
import { formatNumber } from "../lib/format";
import type { Source, LandPriceFile, LandPoint } from "../lib/types";
import { esc } from "../lib/html";

/** 地価の点の種類ごとの名前・URL の引数。地価調査の円は縁の色（墨色）で見分ける */
export const LAND_KINDS = {
  land_price: {
    name: "地価公示", short: "公示", point: "標準地", date: "1月1日", param: "lp", show: "land",
    stroke: "#ffffff", idPattern: /^land-(\d\d)/,
  },
  land_survey_price: {
    name: "都道府県地価調査", short: "調査", point: "基準地", date: "7月1日", param: "ls", show: "landsurvey",
    stroke: "#1c2733", idPattern: /^landsv-(\d\d)/,
  },
} as const;
export type LandKind = keyof typeof LAND_KINDS;
const KINDS = Object.keys(LAND_KINDS) as LandKind[];
// 区切り（円/㎡）と色。塗り分け（青・緑・赤など）の上でも見分けられるよう、紫〜黄の配色に白い縁取りをつける
export const LAND_BREAKS = [100_000, 200_000, 300_000, 500_000, 1_000_000, 3_000_000, 10_000_000];
export const LAND_COLORS = ["#2c115f", "#5a167e", "#862781", "#b5367a", "#e04f67", "#f8765c", "#fdac78", "#fde3a1"];

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

const KANJI_DIGITS: Record<string, number> = { 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };
/** 「二十三」→ 23（丁目の番号だけなので九十九まで） */
function kanjiNumber(s: string): number {
  const [tens, ones] = s.includes("十") ? s.split("十") : ["", s];
  return (s.includes("十") ? (tens ? KANJI_DIGITS[tens] : 1) * 10 : 0) + (ones ? KANJI_DIGITS[ones] ?? 0 : 0);
}

/**
 * 所在地を比べるための形にする。地価調査は「新富一丁目５番１」、地価公示は「新富１丁目５番１」のように
 * 丁目の書き方が違うことがあるので、数字を半角にし、漢数字の丁目を数字にし、空白を除く。
 */
export function normalizeLandAddress(a: string | null): string {
  if (!a) return "";
  return a.replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
    .replace(/[\s　]/g, "")
    .replace(/([一二三四五六七八九十]+)丁目/g, (_, n: string) => `${kanjiNumber(n)}丁目`);
}

/** 2地点の距離（m、近い地点どうしの比較用の近似） */
function distanceM(a: [number, number], b: [number, number]): number {
  const dx = (a[0] - b[0]) * Math.cos((a[1] * Math.PI) / 180) * 111_320;
  const dy = (a[1] - b[1]) * 110_540;
  return Math.hypot(dx, dy);
}

/** 同じ所在地でも、これより離れていれば別の地点とみなす（m） */
const PAIR_MAX_M = 100;

/**
 * 地価公示の標準地と同じ土地を調べている地価調査の基準地（共通地点）を探し、基準地のID → 標準地のID を返す。
 * 公開データに共通地点の印がないので、位置が同じか、所在地が同じで100m以内のものを同じ土地とみなす
 * （2026年の公示・2025年の調査で全国約1,600地点。国土交通省の公表する共通地点の数とほぼ同じ）。
 */
export function pairLandPoints(publics: LandPoint[], surveys: LandPoint[]): Map<string, string> {
  const byCoord = new Map(publics.map((p) => [p.coord.join(","), p]));
  const byAddress = new Map<string, LandPoint[]>();
  for (const p of publics) {
    const a = normalizeLandAddress(p.address);
    if (a) byAddress.set(a, [...(byAddress.get(a) ?? []), p]);
  }
  const used = new Set<string>();
  const out = new Map<string, string>();
  for (const s of surveys) {
    const hit = [byCoord.get(s.coord.join(",")), ...(byAddress.get(normalizeLandAddress(s.address)) ?? [])
      .filter((p) => distanceM(p.coord, s.coord) <= PAIR_MAX_M)
      .sort((a, b) => distanceM(a.coord, s.coord) - distanceM(b.coord, s.coord))]
      .find((p) => p && !used.has(p.id));
    if (!hit) continue;
    used.add(hit.id);
    out.set(s.id, hit.id);
  }
  return out;
}

/** 地図の1つの点（共通地点は標準地と基準地の両方を持つ） */
interface Spot {
  land_price?: LandPoint;
  land_survey_price?: LandPoint;
}

/** 推移の表の1行 */
export interface LandRow {
  period: string;
  kind: LandKind;
  value: number;
}

/** 月の差（"2025-07-01" と "2026-01-01" → 6） */
function monthsBetween(a: string, b: string): number {
  const [ya, ma] = a.split("-").map(Number);
  const [yb, mb] = b.split("-").map(Number);
  return (yb - ya) * 12 + (mb - ma);
}

/**
 * 推移の表の行に、1つ前の行からの変化率（%）を付ける。行は古い順。
 * 1年より前の行とは比べない（その間に値のない年があったとき）。共通地点では地価公示と地価調査の行が
 * 半年ごとに交互に並ぶので、半年間の変化になる（国土交通省も共通地点で半年ごとの変動率を出している）。
 */
export function withChanges(rows: LandRow[]): (LandRow & { change: number | null })[] {
  return rows.map((r, k) => {
    const prev = rows[k - 1];
    const ok = prev && prev.value > 0 && monthsBetween(prev.period, r.period) <= 12;
    return { ...r, change: ok ? ((r.value - prev.value) / prev.value) * 100 : null };
  });
}

/** 変化率の表記（+1.2%、−0.5%、±0.0%） */
const changeLabel = (r: number) => `${r >= 0.05 ? "+" : r <= -0.05 ? "−" : "±"}${formatNumber(Math.abs(r), 1)}%`;

export function initLandPrices(o: Options): LandPriceLayer {
  const LAYER = "land-circle";
  const SELECTED = "land-selected";
  const LABEL = "land-label";
  const SOURCE = "land-points";
  // 推移の表の年の見出し（「2025年1月1日現在」→「2025年」）
  const yearOnly = (label: string) => label.replace(/\d+月\d+日.*$/, "");
  const files: Partial<Record<LandKind, LandPriceFile>> = {};
  const legacy: Partial<Record<LandKind, LandPoint[]>> = {};   // 古い公開版（1ファイルに全件）
  let loaded = false;
  let byId = new Map<string, Spot>();
  let shownCount = 0;
  const latest = (kind: LandKind) => (files[kind] ? files[kind]!.periods.length - 1 : 0);
  const latestValue = (kind: LandKind, p?: LandPoint) => (p ? p.values[latest(kind)] ?? null : null);
  const loaders = Object.fromEntries(KINDS.map((kind) => [kind, createPrefLoader<LandPoint>({
    map: o.map, fetchJSON: o.fetchJSON, id: kind, key: "points",
    active: () => o.toggle.checked,
    onChange: () => render(),
  })])) as Record<LandKind, ReturnType<typeof createPrefLoader<LandPoint>>>;
  const items = (kind: LandKind) => legacy[kind] ?? loaders[kind].items();

  async function load(): Promise<boolean> {
    if (loaded) return true;
    await Promise.all(KINDS.map(async (kind) => {
      try {
        files[kind] = await o.fetchJSON<LandPriceFile>(`places/${kind}.json`);
      } catch {
        // その公開版にない方は出さない
      }
    }));
    if (!files.land_price && !files.land_survey_price) {
      o.legend.hidden = false;
      o.legend.textContent = "この公開版には地価のデータがありません。";
      return false;
    }
    loaded = true;
    for (const kind of KINDS) {
      const f = files[kind];
      if (!f) continue;
      loaders[kind].init(f);
      if (f.points) legacy[kind] = f.points;
    }
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
        "circle-stroke-color": ["get", "stroke"] as never,
        "circle-stroke-width": 1.2,
      },
    }, o.beforeLayer);
    o.map.addLayer({
      id: SELECTED, type: "circle", source: SOURCE, filter: selectedFilter(null),
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
    render();
    return true;
  }

  // 共通地点は標準地のIDで描くので、基準地のIDで選んだときも枠を付けられるよう、両方のIDで探す
  const selectedFilter = (id: string | null) => ["any", ["==", ["get", "id"], id ?? ""], ["==", ["get", "sv"], id ?? ""]] as never;

  function updateLegend() {
    if (!loaded) return;
    const bins = landBins();
    const has = KINDS.filter((kind) => files[kind]);
    const parts = has.map((kind) => {
      const k = LAND_KINDS[kind];
      return `${k.name}（${esc(files[kind]!.periods[latest(kind)].label.replace(/現在$/, ""))}）の${k.point}`;
    });
    const zoomNote = loaders.land_price.tooFar() ? "地点は地図を拡大すると表示します。" : "";
    o.legend.innerHTML =
      `${parts.join("と、")}の価格（1㎡あたり${shownCount ? `、読み込んだ${formatNumber(shownCount, 0)}地点` : ""}）。` +
      (has.length === 2 ? "縁が濃い色の点は地価調査の基準地です。同じ土地を両方で調べている地点（共通地点）は1つの点にまとめています。" : "") +
      `地域の平均ではなく1地点の価格です。${zoomNote}` +
      `<span class="land-bins">${LAND_COLORS.map((c, k) =>
        `<span><span class="sw" style="background:${c}"></span>${esc(bins[k])}</span>`).join("")}</span>`;
  }

  /** 読み込んだ地点（都道府県の分が増えるたびに全体）を地図に描き直す。共通地点は1つの点にする */
  function render() {
    if (!loaded) return;
    const publics = items("land_price");
    const surveys = items("land_survey_price");
    const pairs = pairLandPoints(publics, surveys);
    const publicById = new Map(publics.map((p) => [p.id, p]));
    const spots: Spot[] = publics.map((p) => ({ land_price: p }));
    const spotOf = new Map(spots.map((s) => [s.land_price!.id, s]));
    for (const s of surveys) {
      const pid = pairs.get(s.id);
      if (pid && publicById.has(pid)) spotOf.get(pid)!.land_survey_price = s;
      else spots.push({ land_survey_price: s });
    }
    byId = new Map();
    const features: object[] = [];
    for (const s of spots) {
      for (const p of [s.land_price, s.land_survey_price]) if (p) byId.set(p.id, s);
      const v = spotValue(s);
      if (v == null) continue;
      const main = (s.land_price ?? s.land_survey_price)!;
      const pair = s.land_price && s.land_survey_price;
      features.push({
        type: "Feature",
        properties: {
          id: main.id, sv: pair ? s.land_survey_price!.id : "", name: main.name, v,
          stroke: s.land_price ? LAND_KINDS.land_price.stroke : LAND_KINDS.land_survey_price.stroke,
          pick: pair ? `${main.name}（共通地点）` : `${main.name}（${s.land_price ? "地価公示" : "地価調査"}）`,
        },
        geometry: { type: "Point", coordinates: main.coord },
      });
    }
    shownCount = features.length;
    (o.map.getSource(SOURCE) as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features } as never);
    updateLegend();
  }

  /**
   * 点の色に使う価格。最新の時点に値のある地点だけ出す（廃止された地点を出さない）。
   * 共通地点は、2つの調査のうち新しい方の時点の価格（ふつうは地価公示、9月の地価調査の公表から翌年3月までは地価調査）
   */
  function spotValue(s: Spot): number | null {
    const have = KINDS.filter((kind) => latestValue(kind, s[kind]) != null)
      .sort((a, b) => files[b]!.periods[latest(b)].period.localeCompare(files[a]!.periods[latest(a)].period));
    return have.length ? latestValue(have[0], s[have[0]]) : null;
  }

  async function setVisible(on: boolean) {
    if (on && !(await load())) {
      o.toggle.checked = false;
      return;
    }
    o.legend.hidden = !on && loaded;
    for (const id of [LAYER, SELECTED, LABEL]) {
      if (o.map.getLayer(id)) o.map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    }
    if (!on) showPoint(null);
    else await Promise.all(KINDS.map((kind) => loaders[kind].refresh()));
  }
  o.toggle.addEventListener("change", () => void setVisible(o.toggle.checked));

  /** 1つの調査の現在の価格と前年からの変化 */
  function currentHtml(kind: LandKind, p: LandPoint, both: boolean): string {
    const f = files[kind]!;
    const k = LAND_KINDS[kind];
    const i = latest(kind);
    const v = p.values[i];
    const head = both ? `${k.name}（${f.periods[i].label.replace(/現在$/, "")}、1㎡あたり）` : `${f.name}（${f.periods[i].label}、1㎡あたり）`;
    return `<div class="small">${esc(head)}</div>
      <div class="value">${v != null ? `${formatNumber(v, 0)}円` : "値なし"}</div>
      ${p.change_rate != null ? `<p class="small">前年から ${changeLabel(p.change_rate)}</p>` : ""}`;
  }

  /** 推移の表。共通地点は地価公示（1月1日）と地価調査（7月1日）を時点の順に並べる */
  function trendHtml(s: Spot): string {
    const kinds = KINDS.filter((kind) => s[kind] && files[kind]);
    const both = kinds.length === 2;
    const rows: LandRow[] = kinds.flatMap((kind) => files[kind]!.periods.flatMap((x, k) => {
      const v = s[kind]!.values[k];
      return v == null ? [] : [{ period: x.period, kind, value: v }];
    })).sort((a, b) => a.period.localeCompare(b.period));
    const labelOf = new Map(kinds.flatMap((kind) => files[kind]!.periods.map((x) => [`${kind}:${x.period}`, x.label])));
    const current = new Set(kinds.map((kind) => `${kind}:${files[kind]!.periods[latest(kind)].period}`));
    const body = withChanges(rows).map((r) => {
      const label = labelOf.get(`${r.kind}:${r.period}`) ?? r.period;
      const when = both
        ? `${esc(label.replace(/(\d+)年(\d+)月.*$/, "$1年$2月"))} <span class="muted">${LAND_KINDS[r.kind].short}</span>`
        : esc(yearOnly(label));
      return `<tr${current.has(`${r.kind}:${r.period}`) ? ' aria-current="true"' : ""}><td>${when}</td>
        <td class="num">${formatNumber(r.value, 0)}円</td><td class="num">${r.change != null ? changeLabel(r.change) : ""}</td></tr>`;
    }).reverse().join("");
    const caption = both ? "推移（地価公示は各年1月1日、地価調査は各年7月1日）" : `推移（各年${LAND_KINDS[kinds[0]].date}）`;
    return `<div class="trend-scroll"><table class="trend"><caption>${caption}</caption>
      <thead><tr><th>${both ? "時点" : "年"}</th><th class="num">価格（円/㎡）</th><th class="num">${both ? "前回から" : "前年から"}</th></tr></thead>
      <tbody>${body}</tbody></table></div>` +
      (both ? `<p class="note small">共通地点なので、「前回から」は半年前（もう一方の調査の時点）の価格からの変化です。</p>` : "");
  }

  /** 情報を出している地点の位置 */
  let at: [number, number] | null = null;
  function showPoint(id: string | null) {
    if (o.map.getLayer(SELECTED)) o.map.setFilter(SELECTED, selectedFilter(id));
    const s = id ? byId.get(id) : undefined;
    const kinds = s ? KINDS.filter((kind) => s[kind] && files[kind]) : [];
    at = s && kinds.length ? s[kinds[0]]!.coord : null;
    if (!s || !kinds.length) {
      o.panel.hidden = true;
      o.panel.innerHTML = "";
      o.onPanel();
      return;
    }
    const both = kinds.length === 2;
    const main = s[kinds[0]]!;
    const k = LAND_KINDS[kinds[0]];
    const facts = [
      main.use_label,
      main.current_use ? `利用現況: ${main.current_use}` : "",
      main.area_m2 ? `地積 ${formatNumber(main.area_m2, 0)}㎡` : "",
      main.zoning ? `用途地域: ${main.zoning}` : "",
      main.station ? `最寄駅: ${main.station}${main.station_distance_m ? `（${formatNumber(main.station_distance_m, 0)}m）` : ""}` : "",
    ].filter(Boolean);
    // 値のある最初の年が、表の最初の年より後なら、それより前は地点でなかったことを書く
    const starts = kinds.flatMap((kind) => {
      const first = s[kind]!.values.findIndex((v) => v != null);
      return first > 0 ? [{ kind, year: yearOnly(files[kind]!.periods[first].label) }] : [];
    });
    const startNote = !starts.length ? ""
      : both ? `値があるのは、${starts.map((x) => `${LAND_KINDS[x.kind].name}は${x.year}から`).join("、")}です。`
      : `${starts[0].year}から${LAND_KINDS[starts[0].kind].point}です。それより前は値がありません。`;
    const caveats = [...new Set(kinds.flatMap((kind) => files[kind]!.caveats))];
    const sourceIds = [...new Set(kinds.flatMap((kind) => files[kind]!.source_ids))];
    o.panel.hidden = false;
    o.panel.innerHTML = `
      <button type="button" class="close" data-close aria-label="地価の情報を閉じる">×</button>
      <p class="muted">${esc(o.municipalityName(main.municipality_id))}・${both ? "地価公示と地価調査の共通地点" : `${k.name}の${k.point}`}</p>
      <h2>${esc(main.name)}</h2>
      <p class="muted small">${esc(main.address ?? "")}${main.residential_address ? `（住居表示 ${esc(main.residential_address)}）` : ""}${
        both ? `<br>地価調査の基準地番号 ${esc(s.land_survey_price!.name)}` : ""}</p>
      ${kinds.map((kind) => currentHtml(kind, s[kind]!, both)).join("")}
      <p class="small">${facts.map(esc).join("・")}</p>
      ${startNote ? `<p class="note small">${esc(startNote)}</p>` : ""}
      ${trendHtml(s)}
      <p class="muted small">${caveats.map(esc).join(" ")}</p>
      ${sourcesHtml(sourceIds, o.sources)}`;
    o.onPanel();
  }

  o.panel.addEventListener("click", (e) => {
    if ((e.target as HTMLElement).closest("[data-close]")) showPoint(null);
  });

  // ?lp=<標準地ID> か ?ls=<基準地ID> で開いたときは表示をオンにしてその地点を選ぶ
  const params = new URLSearchParams(location.search);
  const initialKind = KINDS.find((kind) => params.get(LAND_KINDS[kind].param));
  if (initialKind) {
    const k = LAND_KINDS[initialKind];
    const initial = params.get(k.param)!;
    o.toggle.checked = true;
    void setVisible(true).then(async () => {
      // 地点のIDは land-<市区町村コード>-…（地価調査は landsv-…）なので、都道府県が分かる
      const pref = k.idPattern.exec(initial)?.[1];
      const p = await loaders[initialKind].find((x) => x.id === initial, pref);
      if (!p) return;
      o.map.jumpTo({ center: p.coord, zoom: Math.max(o.map.getZoom(), 14.5, PLACES_MIN_ZOOM) });
      // 共通地点の相手も同じ都道府県にあるので、先に読んでから選ぶ
      const other = KINDS.find((kind) => kind !== initialKind)!;
      if (files[other] && pref) await loaders[other].loadPrefecture(pref);
      showPoint(initial);
    });
  }

  // ?show=land（以前の地価調査の land survey も）で開いたときは表示をオンにする（トップページの指標の一覧から）
  const shown = params.get("show")?.split(",") ?? [];
  if (!initialKind && KINDS.some((kind) => shown.includes(LAND_KINDS[kind].show))) {
    o.toggle.checked = true;
    void setVisible(true);
  }

  return {
    layer: LAYER,
    kind: "地価",
    visible: () => !!o.map.getLayer(LAYER) && o.toggle.checked,
    show: showPoint,
    isOpen: () => !o.panel.hidden,
    coord: () => (o.panel.hidden ? null : at),
  };
}
