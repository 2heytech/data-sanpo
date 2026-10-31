// 色分け地図の画像（PNG、1200×630）。都道府県ページと寄り道に置き、共有画像（og:image）にも使う（設計変更記録 #142）。
// 地図はブラウザで描くので検索エンジンの画像検索に出ない。ビルドのときに境界と値から SVG を作り、resvg で PNG にする。
// 文字はロゴと同じ M PLUS Rounded 1c を、画像に出る文字だけに絞って使う（scripts/image-font.mjs で作る）。
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Resvg } from "@resvg/resvg-js";
import { BLANK_COLOR, classIndex, colorsFor, NO_DATA_COLOR } from "./classify";
import { frameFor, pathFor, type Frame, type Geometry } from "./shape";

export const IMAGE_WIDTH = 1200;
export const IMAGE_HEIGHT = 630;
const INK = "#1c2733";
const SUB = "#4a5866";
const ACCENT = "#0b5cad";
// 地図を置く枠（右側）と、文字を置く左側の幅
const MAP = { x: 612, y: 24, w: 560, h: 566 };
const LEFT = 56;
const TEXT_W = 536;

export interface MapFeature { id: string; geometry: Geometry }

export interface ChoroplethSpec {
  /** 題名。「：」で改行し、長いときは「、」「・」などの区切りで折り返す */
  title: string;
  subtitle: string;
  /** 凡例の下に並べる短い文（増えた市区町村の数など） */
  facts?: string[];
  features: MapFeature[];
  values: Map<string, number | null>;
  breaks: number[];
  scheme: string;
  zeroBlank?: boolean;
  /** 凡例の区切りの書き方 */
  formatBreak: (v: number) => string;
  /** 凡例の上に書く単位（区切りに単位を付けないとき） */
  unitLabel?: string;
  source: string;
  /** fit: 形に合わせる（都道府県）。japan: 日本全体（沖縄県は左上に別枠） */
  frame: "fit" | "japan";
  /** fit の枠を決める形（都道府県の境界。小さな島は枠を決めるのに使わない）。ないときは features */
  frameGeometries?: Geometry[];
}

const FONT_DIR = join(process.cwd(), "src/assets/image-fonts");
let fontChars: Set<string> | null = null;

/** 画像の文字がフォントにあるか確かめる。ないとその文字が抜けた画像になるので、ビルドを止める */
export function assertGlyphs(texts: string[]): void {
  fontChars ??= new Set([...readFileSync(join(FONT_DIR, "chars.txt"), "utf8")]);
  const missing = [...new Set([...texts.join("")])].filter((c) => !fontChars!.has(c));
  if (missing.length) {
    throw new Error(`地図の画像のフォントにない文字があります: ${missing.join("")}。node scripts/image-font.mjs を動かしてフォントを作り直してください`);
  }
}

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** 文字列の幅の目安（英数字は全角の約6割） */
export function textWidth(s: string, size: number): number {
  let em = 0;
  for (const c of s) em += c < "Ā" ? 0.6 : 1;
  return em * size;
}

const BREAK_AFTER = new Set([..."、・」）。"]);
const BREAK_BEFORE = new Set([..."「（"]);
// 説明の文は、助詞の後でも折り返してよいことにする
const SOFT_AFTER = new Set([..."のをとでにはが"]);

/** 折り返してよい位置で区切る */
function segments(text: string, soft: boolean): string[] {
  const out: string[] = [];
  let cur = "";
  for (const c of text) {
    if (BREAK_BEFORE.has(c) && cur) { out.push(cur); cur = ""; }
    cur += c;
    if (BREAK_AFTER.has(c) || (soft && SOFT_AFTER.has(c))) { out.push(cur); cur = ""; }
  }
  if (cur) out.push(cur);
  return out;
}

/** 区切りを行に詰める。1つの区切りが幅を超えるときは null */
function pack(segs: string[], size: number, maxWidth: number): string[] | null {
  const lines: string[] = [];
  let cur = "";
  for (const s of segs) {
    if (textWidth(cur + s, size) <= maxWidth) { cur += s; continue; }
    if (!cur || textWidth(s, size) > maxWidth) return null;
    lines.push(cur);
    cur = s;
  }
  if (cur) lines.push(cur);
  return lines;
}

/** 文字で折り返す（区切りで収まらないとき）。行が多すぎるときは最後の行を「…」で切る */
function charWrap(text: string, size: number, maxWidth: number, maxLines: number): string[] {
  const lines: string[] = [];
  let cur = "";
  for (const c of text) {
    if (textWidth(cur + c, size) > maxWidth && cur) { lines.push(cur); cur = ""; }
    cur += c;
  }
  if (cur) lines.push(cur);
  if (lines.length <= maxLines) return lines;
  const head = lines.slice(0, maxLines);
  head[maxLines - 1] = `${[...head[maxLines - 1]].slice(0, -1).join("")}…`;
  return head;
}

/** 決まった大きさの文字で、maxLines 行までに折り返す */
export function breakText(text: string, size: number, maxWidth: number, maxLines: number): string[] {
  const lines = pack(segments(text, true), size, maxWidth);
  return lines && lines.length <= maxLines ? lines : charWrap(text, size, maxWidth, maxLines);
}

/**
 * 題名の文字の大きさと行。なるべく2行、だめなら3行に収まる、いちばん大きい文字にする。
 * 「、」「・」などの区切りで収まらないときは、助詞の後でも折り返す（数字や言葉の途中では切らない）
 */
export function layoutTitle(text: string, maxWidth = TEXT_W): { size: number; lines: string[] } {
  const parts = text.split("：");
  const at = (size: number, soft: boolean) => {
    const ls = parts.map((p) => pack(segments(p, soft), size, maxWidth));
    return ls.some((l) => !l) ? null : (ls as string[][]).flat();
  };
  for (const soft of [false, true]) {
    for (const [maxLines, sizes] of [[2, [44, 40, 36]], [3, [44, 40, 36, 32]]] as const) {
      for (const size of sizes) {
        const lines = at(size, soft);
        if (lines && lines.length <= maxLines) return { size, lines };
      }
    }
  }
  return { size: 32, lines: charWrap(parts.join(""), 32, maxWidth, 3) };
}

/** 枠を、指定した箱に収まる大きさにする */
function fitFrame(f: Frame, w: number, h: number): Frame {
  const k = Math.min(w / f.width, h / f.height);
  return { ...f, scale: f.scale * k, width: f.width * k, height: f.height * k };
}

/** 経緯度の範囲から枠を作る（日本全体の図など、形ではなく範囲で決めるとき） */
function boxFrame(minLon: number, maxLon: number, minLat: number, maxLat: number, w: number, h: number): Frame {
  const cos = Math.cos((((minLat + maxLat) / 2) * Math.PI) / 180);
  const fw = (maxLon - minLon) * cos, fh = maxLat - minLat;
  const scale = Math.min(w / fw, h / fh);
  return { minX: minLon * cos, minY: -maxLat, scale, width: fw * scale, height: fh * scale, cos, mainShare: 1 };
}

function fillFor(spec: ChoroplethSpec, colors: string[], id: string): string {
  const v = spec.values.get(id);
  if (v === null || v === undefined) return NO_DATA_COLOR;
  if (spec.zeroBlank && v === 0) return "#ffffff";
  const c = colors[classIndex(v, spec.breaks)];
  return c === BLANK_COLOR ? "#ffffff" : c;
}

function mapLayer(spec: ChoroplethSpec, features: MapFeature[], f: Frame, colors: string[], stroke: number): string {
  const paths = features.map((ft) => {
    const d = pathFor(ft.geometry, f, 0.35, 0.6);
    return d ? `<path d="${d}" fill="${fillFor(spec, colors, ft.id)}"/>` : "";
  }).join("");
  return `<g stroke="#ffffff" stroke-width="${stroke}" stroke-linejoin="round">${paths}</g>`;
}

/** 枠の外（東京都の島しょなど、枠を決めるのに使わなかった島）は切る */
const clipped = (id: string, x: number, y: number, w: number, h: number, body: string) =>
  `<clipPath id="${id}"><rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}"/></clipPath>`
  + `<g clip-path="url(#${id})"><g transform="translate(${x.toFixed(1)} ${y.toFixed(1)})">${body}</g></g>`;

function mapSvg(spec: ChoroplethSpec, colors: string[]): string {
  if (spec.frame === "fit") {
    const f = fitFrame(frameFor(spec.frameGeometries ?? spec.features.map((x) => x.geometry), 1, 0.1), MAP.w, MAP.h);
    const ox = MAP.x + (MAP.w - f.width) / 2, oy = MAP.y + (MAP.h - f.height) / 2;
    return clipped("map", ox, oy, f.width, f.height, mapLayer(spec, spec.features, f, colors, 1));
  }
  // 日本全体: 北海道から奄美まで。沖縄県は左上の別枠に描く（市区町村別の図も都道府県別の図も。#184）
  const inOkinawa = (id: string) => id.startsWith("muni-47") || id === "pref-47";
  const okinawa = spec.features.filter((x) => inOkinawa(x.id));
  const main = spec.features.filter((x) => !inOkinawa(x.id));
  const f = boxFrame(128.2, 146.0, 27.0, 45.6, MAP.w, MAP.h);
  const ox = MAP.x + (MAP.w - f.width) / 2, oy = MAP.y + (MAP.h - f.height) / 2;
  let inset = "";
  if (okinawa.length) {
    // 沖縄本島から八重山まで（大東島などの小さな島は枠の外になる）
    const box = { w: 220, h: 150 };
    const fi = fitFrame(frameFor(okinawa.map((x) => x.geometry), 1, 0.15), box.w - 16, box.h - 16);
    const ix = ox + 4, iy = oy + 4;
    inset = `<rect x="${ix.toFixed(1)}" y="${iy.toFixed(1)}" width="${box.w}" height="${box.h}" fill="#ffffff" stroke="#9aa5b1" stroke-width="1"/>`
      + clipped("okinawa", ix + (box.w - fi.width) / 2, iy + (box.h - fi.height) / 2, fi.width, fi.height, mapLayer(spec, okinawa, fi, colors, 0.4));
  }
  return clipped("japan", ox, oy, f.width, f.height, mapLayer(spec, main, f, colors, 0.4)) + inset;
}

/** 凡例: 色の箱を横に並べ、区切りの値を下に書く（両端と真ん中だけ。0 を境に色が変わる配色では真ん中の代わりに 0 を書く） */
function legendSvg(spec: ChoroplethSpec, colors: string[], y: number): string {
  const n = colors.length;
  const bw = Math.min(40, 440 / n), bh = 22;
  const boxes = colors.map((c, i) =>
    `<rect x="${(LEFT + i * bw).toFixed(1)}" y="${y}" width="${bw.toFixed(1)}" height="${bh}" fill="${c === BLANK_COLOR ? "#ffffff" : c}" stroke="#ffffff" stroke-width="1"/>`).join("");
  const nb = spec.breaks.length;
  const want = new Set(nb ? [0, nb - 1, Math.round((nb - 1) / 2)] : []);
  const zero = spec.breaks.indexOf(0);
  if (zero >= 0) { want.delete(Math.round((nb - 1) / 2)); want.add(zero); }
  const labels = [...want].sort((a, b) => a - b).map((i) =>
    `<text x="${(LEFT + (i + 1) * bw).toFixed(1)}" y="${y + bh + 22}" text-anchor="middle" font-size="16" font-weight="500" fill="${SUB}">${esc(spec.formatBreak(spec.breaks[i]))}</text>`).join("");
  const hasNull = spec.features.some((ft) => spec.values.get(ft.id) == null);
  const nullBox = hasNull
    ? `<rect x="${LEFT + n * bw + 20}" y="${y}" width="22" height="${bh}" fill="${NO_DATA_COLOR}"/>`
      + `<text x="${LEFT + n * bw + 48}" y="${y + 17}" font-size="16" font-weight="500" fill="${SUB}">値なし</text>`
    : "";
  const unit = spec.unitLabel
    ? `<text x="${LEFT}" y="${y - 10}" font-size="15" font-weight="500" fill="${SUB}">${esc(spec.unitLabel)}</text>`
    : "";
  return unit + boxes + labels + nullBox;
}

const textLines = (lines: string[], y: number, step: number, size: number, weight: number, fill: string) =>
  lines.map((l, i) => `<text x="${LEFT}" y="${y + i * step}" font-size="${size}" font-weight="${weight}" fill="${fill}">${esc(l)}</text>`).join("");

/** 画像に書く文字（フォントにあるか確かめる用） */
function allTexts(spec: ChoroplethSpec): string[] {
  return [spec.title, spec.subtitle, spec.source, spec.unitLabel ?? "", "値なし…", ...(spec.facts ?? []), ...spec.breaks.map(spec.formatBreak)];
}

export function choroplethSvg(spec: ChoroplethSpec): string {
  const colors = colorsFor(spec.scheme, spec.breaks, spec.zeroBlank ?? false);
  const logo = readFileSync(join(process.cwd(), "public/logo.svg"), "utf8")
    .replace(/^<svg[^>]*>/, `<svg x="${LEFT}" y="40" width="232" height="48" viewBox="0 0 339 70">`);
  // 左側に上から、ロゴ・題名・説明・凡例・短い文、いちばん下に出典
  const t = layoutTitle(spec.title);
  const titleStep = Math.round(t.size * 1.3);
  let y = 140 + t.size;
  const title = textLines(t.lines, y, titleStep, t.size, 700, INK);
  y += (t.lines.length - 1) * titleStep + 44;
  const subLines = breakText(spec.subtitle, 22, TEXT_W, 2);
  const sub = textLines(subLines, y, 30, 22, 500, SUB);
  y += (subLines.length - 1) * 30 + (spec.unitLabel ? 46 : 28);
  const legend = legendSvg(spec, colors, y);
  y += 22 + 22 + 48;
  const facts = textLines(spec.facts ?? [], y, 34, 22, 700, INK);
  const srcLines = breakText(spec.source, 15, TEXT_W, 2);
  const source = textLines(srcLines, IMAGE_HEIGHT - 40 - (srcLines.length - 1) * 21, 21, 15, 500, SUB);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${IMAGE_WIDTH}" height="${IMAGE_HEIGHT}" viewBox="0 0 ${IMAGE_WIDTH} ${IMAGE_HEIGHT}" font-family="Rounded Mplus 1c">`
    + `<rect width="${IMAGE_WIDTH}" height="${IMAGE_HEIGHT}" fill="#ffffff"/>`
    + mapSvg(spec, colors) + logo + title + sub + legend + facts + source
    + `<rect y="${IMAGE_HEIGHT - 14}" width="${IMAGE_WIDTH}" height="14" fill="${ACCENT}"/></svg>`;
}

/** 色分け地図の PNG。文字がフォントにないときは止める */
export function choroplethPng(spec: ChoroplethSpec): Uint8Array<ArrayBuffer> {
  assertGlyphs(allTexts(spec));
  const resvg = new Resvg(choroplethSvg(spec), {
    font: {
      fontFiles: [500, 700].map((w) => join(FONT_DIR, `mplus-rounded-1c-${w}.ttf`)),
      loadSystemFonts: false,
      defaultFontFamily: "Rounded Mplus 1c",
    },
  });
  // Response にそのまま渡せる形にする
  return new Uint8Array(resvg.render().asPng());
}
