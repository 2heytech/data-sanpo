// 地図の画像の保存・コピーと、リンクのコピー（設計変更記録 #153・#156）。地図の右下のボタンで画面を開く。
// 画像は表示中の地図（WebGL の canvas）に、題名・凡例・出典・サイト名を書き足してブラウザの中で作る（どこにも送らない）。
// リンクは URL の状態（指標・時点・選んだ地域・色分けの単位・背景・重ねた点・表示の切替）に、地図の位置と縮尺を足したもの。
// 位置と縮尺は「地図の位置と縮尺も入れる」を外すと入れない（#175。アドレス欄の URL には入れない）。
// SNS などへ送るボタンは置かない（#156）。
import type { IControl, Map as MapLibreMap } from "maplibre-gl";
import { tickStep } from "../lib/classify";

/** 凡例の中身（左の欄の凡例と、画像の凡例で同じものを使う） */
export interface LegendModel {
  unit: string;
  /** 「市区町村」など。見出しは「〇〇別」 */
  levelLabel: string;
  colors: string[];
  /** 色ごとの範囲の説明 */
  labels: string[];
  /** 帯の上の位置（0〜1）と文字。区分で公表された値は色の中ほど、ほかは色の境目 */
  ticks: { at: number; text: string }[];
  /** 区分で公表された値（目盛りの線を引かない） */
  band: boolean;
  zeroBlank: boolean;
  noDataColor: string;
}

/** 背景の凡例（色分けを消して土地利用・標高を見ているとき、画像に書く。#175） */
export interface BaseLegend {
  title: string;
  /** 区分の色と名前（土地利用） */
  items?: { color: string; label: string }[];
  /** 色の帯（標高）。位置は 0〜1 */
  gradient?: { stops: { at: number; color: string }[]; ticks: { at: number; text: string }[] };
}

export interface ShareView {
  /** 画像の題名（指標名。色分けを消しているときは「地図」） */
  title: string;
  /** 題名の下の行（時点・単位・選んだ地域・背景） */
  subtitle: string;
  legend: LegendModel | null;
  base?: BaseLegend | null;
  /** 画像の下に書く出典（「統計: …」「地図: …」の行） */
  credits: string[];
  /** 保存する画像のファイル名 */
  fileName: string;
}

interface ShareOptions {
  map: MapLibreMap;
  root: HTMLElement;
  view: () => ShareView;
  /** 共有用のリンク。withView のときは地図の位置と縮尺も入れる */
  link: (withView: boolean) => string;
  font: string;
}

const INK = "#1c2733";
const SUB = "#4a5866";
const LINE = "#d5dbe1";
const ICON_SHARE =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5v11M8 7.5l4-4 4 4"/><path d="M8.5 10.5H6.5a1.5 1.5 0 0 0-1.5 1.5v7a1.5 1.5 0 0 0 1.5 1.5h11a1.5 1.5 0 0 0 1.5-1.5v-7a1.5 1.5 0 0 0-1.5-1.5h-2"/></svg>';
// 画像の幅の上限（高い解像度の画面で、ファイルが大きくなりすぎないように）
const MAX_WIDTH = 2000;

export function initShare(o: ShareOptions): void {
  const $ = <T extends HTMLElement>(sel: string) => o.root.querySelector<T>(sel)!;
  const dialog = $<HTMLDialogElement>("#share-dialog");
  const preview = $<HTMLImageElement>("#share-image");
  const status = $("#share-status");
  const download = $<HTMLAnchorElement>("#share-download");
  const imageCopyButton = $<HTMLButtonElement>("#share-image-copy");
  const urlInput = $<HTMLInputElement>("#share-url");
  const copyButton = $<HTMLButtonElement>("#share-copy");
  const viewCheck = $<HTMLInputElement>("#share-view");
  // 画像をクリップボードに入れられるブラウザだけ「画像をコピー」を出す
  const canCopyImage = typeof ClipboardItem !== "undefined" && !!navigator.clipboard?.write
    && (ClipboardItem.supports?.("image/png") ?? true);
  let objectUrl: string | null = null;
  let blob: Blob | null = null;
  let token = 0;

  const control: IControl = {
    onAdd() {
      const div = document.createElement("div");
      div.className = "maplibregl-ctrl maplibregl-ctrl-group share-ctrl";
      div.innerHTML = `<button type="button" aria-haspopup="dialog" title="画像の保存・コピーとリンクのコピー">${ICON_SHARE}<span>共有</span></button>`;
      div.querySelector("button")!.addEventListener("click", () => void open());
      return div;
    },
    onRemove() {},
  };
  o.map.addControl(control, "bottom-right");

  async function open() {
    const t = ++token;
    const view = o.view();
    setLink();
    blob = null;
    imageCopyButton.hidden = !canCopyImage;
    imageCopyButton.textContent = "画像をコピー";
    imageCopyButton.disabled = true;
    download.removeAttribute("href");
    download.setAttribute("aria-disabled", "true");
    preview.hidden = true;
    status.hidden = false;
    status.textContent = "画像を作っています…";
    dialog.showModal();
    try {
      const canvas = compose(await snapshot(o.map), view, o.font, await logo());
      const png = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
      if (t !== token) return;
      if (!png) throw new Error("toBlob");
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = URL.createObjectURL(png);
      blob = png;
      preview.src = objectUrl;
      preview.alt = `${view.title}（${view.subtitle}）の地図の画像`;
      preview.hidden = false;
      status.hidden = true;
      download.href = objectUrl;
      download.download = view.fileName;
      download.removeAttribute("aria-disabled");
      imageCopyButton.disabled = false;
    } catch {
      if (t !== token) return;
      status.textContent = "画像を作れませんでした。リンクのコピーはできます。";
    }
  }

  function setLink() {
    urlInput.value = o.link(viewCheck.checked);
    copyButton.textContent = "コピー";
  }
  viewCheck.addEventListener("change", setLink);
  $(".share-close").addEventListener("click", () => dialog.close());
  // 画面の外側（背景）を押したら閉じる
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
  copyButton.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(urlInput.value);
      copyButton.textContent = "コピーしました";
    } catch {
      urlInput.select();
    }
  });
  urlInput.addEventListener("focus", () => urlInput.select());
  imageCopyButton.addEventListener("click", async () => {
    if (!blob) return;
    try {
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
      imageCopyButton.textContent = "画像をコピーしました";
    } catch {
      // 権限がないときなど。保存するか、画像を長押し・右クリックしてコピーしてもらう
      imageCopyButton.textContent = "画像をコピーできませんでした";
    }
  });
}

interface Snapshot {
  canvas: HTMLCanvasElement;
  /** 画面での地図の幅（CSS の px）。文字の大きさを地図の文字に合わせるのに使う */
  cssWidth: number;
}

/** 表示中の地図の画像。描き終えた直後に写す（WebGL の canvas は描いた後に中身が消えるため）。
 *  画面の画素の倍率が低い（1 など）ときは、2倍で描き直して写す（文字や線をくっきりさせる。幅は MAX_WIDTH まで） */
async function snapshot(map: MapLibreMap): Promise<Snapshot> {
  if (!map.loaded()) {
    await Promise.race([
      new Promise<void>((resolve) => map.once("idle", () => resolve())),
      new Promise<void>((resolve) => setTimeout(resolve, 5000)),
    ]);
  }
  const cssWidth = map.getCanvas().clientWidth;
  const before = map.getPixelRatio();
  const ratio = Math.min(Math.max(before, 2), MAX_WIDTH / Math.max(1, cssWidth));
  const raise = ratio > before + 0.01;
  if (raise) map.setPixelRatio(ratio);
  try {
    const canvas = await new Promise<HTMLCanvasElement>((resolve) => {
      map.once("render", () => {
        const src = map.getCanvas();
        const c = document.createElement("canvas");
        c.width = src.width;
        c.height = src.height;
        c.getContext("2d")!.drawImage(src, 0, 0);
        resolve(c);
      });
      map.triggerRepaint();
    });
    return { canvas, cssWidth };
  } finally {
    // null で端末の倍率に戻す（MapLibre の setPixelRatio の説明どおり。型は number だけになっている）
    if (raise) map.setPixelRatio(null as unknown as number);
  }
}

// ロゴ（ヘッダーと同じ画像）。読めないときは文字で書く
let logoImage: Promise<HTMLImageElement | null> | null = null;
function logo(): Promise<HTMLImageElement | null> {
  logoImage ??= new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = "/logo.svg";
  });
  return logoImage;
}

/** 文字を幅に収まるように折り返す。日本語なので1文字ずつ測り、行の後ろ半分に「・」「、」「／」などの区切りがあればそこで折る。
 *  句読点・閉じかっこは行の頭に置かない */
export function wrapText(text: string, maxWidth: number, measure: (s: string) => number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const ch of [...text]) {
    if (line && measure(line + ch) > maxWidth && !/[、。，．・）」』％%]/.test(ch)) {
      const chars = [...line];
      let cut = -1;
      for (let i = chars.length - 1; i >= Math.ceil(chars.length * 0.5); i--) {
        if (/[・、／）\s]/.test(chars[i])) { cut = i + 1; break; }
      }
      const head = cut > 0 ? chars.slice(0, cut).join("") : line;
      lines.push(head.trimEnd());
      line = ((cut > 0 ? chars.slice(cut).join("") : "") + ch).trimStart();
    } else {
      line += ch;
    }
  }
  if (line) lines.push(line);
  return lines;
}

/** 地図の画像に、上に題名とロゴ、下に凡例と出典を足す。大きさは画面の文字の大きさ（CSS の px）× 画面の画素の倍率 */
function compose(shot: Snapshot, view: ShareView, font: string, logoImg: HTMLImageElement | null): HTMLCanvasElement {
  const mapCanvas = shot.canvas;
  const cssWidth = shot.cssWidth || mapCanvas.width;
  const k = Math.min(1, MAX_WIDTH / mapCanvas.width);
  const W = Math.round(mapCanvas.width * k);
  const mapH = Math.round(mapCanvas.height * k);
  const s = W / cssWidth;
  const px = (v: number) => v * s;
  const pad = px(16);
  const out = document.createElement("canvas");
  const ctx = out.getContext("2d")!;
  const setFont = (size: number, weight = 400) => { ctx.font = `${weight} ${px(size)}px ${font}`; };
  const measure = (t: string) => ctx.measureText(t).width;

  // 上: 題名と時点（左）、ロゴとサイトの URL（右）
  const logoH = px(cssWidth < 480 ? 20 : 24);
  const logoW = logoImg ? logoH * (logoImg.naturalWidth / logoImg.naturalHeight || 164 / 34) : px(100);
  setFont(11);
  const siteW = Math.max(logoW, measure("data-sanpo.com"));
  const textW = W - pad * 2 - siteW - px(14);
  setFont(cssWidth < 480 ? 17 : 20, 700);
  const titleLines = wrapText(view.title, textW, measure);
  const titleLH = px(cssWidth < 480 ? 23 : 27);
  setFont(13);
  const subLines = view.subtitle ? wrapText(view.subtitle, textW, measure) : [];
  const subLH = px(19);
  const headH = Math.max(pad + titleLines.length * titleLH + px(2) + subLines.length * subLH + px(10), pad + logoH + px(30));

  // 下: 凡例と出典
  const lg = view.legend;
  const barW = Math.min(W - pad * 2, px(440));
  const barH = px(14);
  const rows = lg && lg.colors.length > 6 ? 2 : 1;
  const tickLH = px(14);
  setFont(10.5);
  const creditLines = view.credits.flatMap((c) => wrapText(c, W - pad * 2, measure));
  const creditLH = px(15);
  const legendH = lg ? px(18) + barH + px(4) + rows * tickLH + px(4) + px(16) + px(8) : 0;
  // 背景の凡例: 土地利用の区分は色の見本と名前を、幅に収まるだけ1行に並べて折り返す
  const bl = view.base;
  const sw = px(14), sh = px(10), itemLH = px(18);
  setFont(11);
  const itemRows: { color: string; label: string; x: number }[][] = [];
  let row: { color: string; label: string; x: number }[] = [];
  let rowX = pad;
  for (const it of bl?.items ?? []) {
    const w = sw + px(4) + measure(it.label);
    if (row.length && rowX + w > W - pad) { itemRows.push(row); row = []; rowX = pad; }
    row.push({ ...it, x: rowX });
    rowX += w + px(14);
  }
  if (row.length) itemRows.push(row);
  const baseH = bl
    ? px(18) + (bl.gradient ? barH + px(4) + tickLH + px(4) : 0) + itemRows.length * itemLH + px(8) : 0;
  const footH = px(12) + legendH + baseH + creditLines.length * creditLH + px(12);

  out.width = W;
  out.height = Math.round(headH + mapH + footH);
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, W, out.height);
  ctx.textBaseline = "alphabetic";

  let y = pad;
  ctx.fillStyle = INK;
  setFont(cssWidth < 480 ? 17 : 20, 700);
  for (const line of titleLines) { ctx.fillText(line, pad, y + titleLH * 0.78); y += titleLH; }
  y += px(2);
  ctx.fillStyle = SUB;
  setFont(13);
  for (const line of subLines) { ctx.fillText(line, pad, y + subLH * 0.75); y += subLH; }
  const siteX = W - pad - siteW;
  if (logoImg) ctx.drawImage(logoImg, siteX + siteW - logoW, pad, logoW, logoH);
  else {
    ctx.fillStyle = "#0b5cad";
    setFont(15, 700);
    ctx.textAlign = "right";
    ctx.fillText("データさんぽ", W - pad, pad + logoH * 0.8);
    ctx.textAlign = "left";
  }
  ctx.fillStyle = SUB;
  setFont(11);
  ctx.textAlign = "right";
  ctx.fillText("data-sanpo.com", W - pad, pad + logoH + px(16));
  ctx.textAlign = "left";

  ctx.drawImage(mapCanvas, 0, headH, W, mapH);
  ctx.fillStyle = LINE;
  ctx.fillRect(0, headH - Math.max(1, px(0.5)), W, Math.max(1, px(1)));
  ctx.fillRect(0, headH + mapH, W, Math.max(1, px(1)));

  y = headH + mapH + px(12);
  if (lg) {
    ctx.fillStyle = INK;
    setFont(12.5, 700);
    ctx.fillText(lg.unit, pad, y + px(13));
    const unitW = measure(lg.unit);
    setFont(12.5);
    ctx.fillStyle = SUB;
    ctx.fillText(`（${lg.levelLabel}別）`, pad + unitW, y + px(13));
    y += px(18);
    const n = lg.colors.length;
    lg.colors.forEach((c, i) => {
      ctx.fillStyle = c;
      const x0 = pad + (barW * i) / n;
      ctx.fillRect(x0, y, barW / n + 0.5, barH);
    });
    ctx.strokeStyle = "rgba(0,0,0,.25)";
    ctx.lineWidth = Math.max(1, px(1));
    ctx.strokeRect(pad, y, barW, barH);
    y += barH;
    // 目盛りの値は帯の境目（区分のときは色の中ほど）に、重ならないように間引いて上下2段に互い違いに書く
    setFont(10.5);
    const xs = lg.ticks.map((t) => pad + t.at * barW);
    const ws = lg.ticks.map((t) => measure(t.text));
    const step = tickStep(xs, ws, rows, px(4));
    ctx.textAlign = "center";
    lg.ticks.forEach((t, j) => {
      const x = xs[j];
      const shown = j % step === 0;
      const low = rows > 1 && shown && (j / step) % 2 === 1;
      if (!lg.band) {
        ctx.fillStyle = "rgba(0,0,0,.35)";
        ctx.fillRect(x - px(0.5), y, Math.max(1, px(1)), px(3) + (low ? tickLH : 0));
      }
      if (!shown) return;
      ctx.fillStyle = SUB;
      // 端の値は帯からはみ出さないように寄せる
      const half = ws[j] / 2;
      const cx = Math.min(Math.max(x, pad + half), W - pad - half);
      ctx.fillText(t.text, cx, y + px(3) + tickLH * (low ? 2 : 1) - px(2));
    });
    ctx.textAlign = "left";
    y += px(4) + rows * tickLH + px(4);
    // 値なし・0（色なし）の見本
    let x = pad;
    const swatch = (fill: string | null, label: string) => {
      if (fill) { ctx.fillStyle = fill; ctx.fillRect(x, y + px(2), sw, sh); }
      ctx.strokeStyle = "rgba(0,0,0,.3)";
      ctx.setLineDash(fill ? [] : [px(2), px(2)]);
      ctx.strokeRect(x, y + px(2), sw, sh);
      ctx.setLineDash([]);
      ctx.fillStyle = SUB;
      setFont(11);
      ctx.fillText(label, x + sw + px(4), y + px(11));
      x += sw + px(4) + measure(label) + px(14);
    };
    if (lg.zeroBlank) swatch(null, "0（色なし）");
    swatch(lg.noDataColor, "値なし");
    y += px(16) + px(8);
  }
  if (bl) {
    ctx.fillStyle = INK;
    setFont(12.5, 700);
    ctx.fillText(bl.title, pad, y + px(13));
    y += px(18);
    if (bl.gradient) {
      const g = ctx.createLinearGradient(pad, 0, pad + barW, 0);
      for (const st of bl.gradient.stops) g.addColorStop(st.at, st.color);
      ctx.fillStyle = g;
      ctx.fillRect(pad, y, barW, barH);
      ctx.strokeStyle = "rgba(0,0,0,.25)";
      ctx.lineWidth = Math.max(1, px(1));
      ctx.strokeRect(pad, y, barW, barH);
      y += barH;
      setFont(10.5);
      ctx.fillStyle = SUB;
      ctx.textAlign = "center";
      for (const t of bl.gradient.ticks) {
        const half = measure(t.text) / 2;
        const cx = Math.min(Math.max(pad + t.at * barW, pad + half), pad + barW - half);
        ctx.fillText(t.text, cx, y + px(3) + tickLH - px(2));
      }
      ctx.textAlign = "left";
      y += px(4) + tickLH + px(4);
    }
    setFont(11);
    for (const items of itemRows) {
      for (const it of items) {
        ctx.fillStyle = it.color;
        ctx.fillRect(it.x, y + px(2), sw, sh);
        ctx.strokeStyle = "rgba(0,0,0,.3)";
        ctx.lineWidth = Math.max(1, px(1));
        ctx.strokeRect(it.x, y + px(2), sw, sh);
        ctx.fillStyle = SUB;
        ctx.fillText(it.label, it.x + sw + px(4), y + px(11));
      }
      y += itemLH;
    }
    y += px(8);
  }
  ctx.fillStyle = SUB;
  setFont(10.5);
  for (const line of creditLines) { ctx.fillText(line, pad, y + creditLH * 0.75); y += creditLH; }
  return out;
}

/** 保存する画像のファイル名に使えない文字を除く */
export function safeFileName(name: string): string {
  return name.replace(/[\\/:*?"<>|\s]+/g, "_").replace(/_+/g, "_").slice(0, 120);
}
