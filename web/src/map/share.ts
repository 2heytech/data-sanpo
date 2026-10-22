// 地図の画像保存と共有（設計変更記録 #153）。地図の右下のボタンで共有の画面を開く。
// 画像は表示中の地図（WebGL の canvas）に、題名・凡例・出典・サイト名を書き足してブラウザの中で作る（どこにも送らない）。
// 共有するリンクは URL の状態（指標・時点・選んだ地域・色分けの単位）だけで、地図の位置は入れない（設計書 3章「共有」）。
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

export interface ShareView {
  /** 画像の題名（指標名。色分けを消しているときは「地図」） */
  title: string;
  /** 題名の下の行（時点・単位・選んだ地域） */
  subtitle: string;
  legend: LegendModel | null;
  /** 画像の下に書く出典（「統計: …」「地図: …」の行） */
  credits: string[];
  /** X などに投稿する文と、保存する画像のファイル名のもと */
  text: string;
  fileName: string;
}

interface ShareOptions {
  map: MapLibreMap;
  root: HTMLElement;
  view: () => ShareView;
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
  const nativeButton = $<HTMLButtonElement>("#share-native");
  const urlInput = $<HTMLInputElement>("#share-url");
  const copyButton = $<HTMLButtonElement>("#share-copy");
  const xLink = $<HTMLAnchorElement>("#share-x");
  const lineLink = $<HTMLAnchorElement>("#share-line");
  let objectUrl: string | null = null;
  let file: File | null = null;
  let view: ShareView | null = null;
  let token = 0;

  const control: IControl = {
    onAdd() {
      const div = document.createElement("div");
      div.className = "maplibregl-ctrl maplibregl-ctrl-group share-ctrl";
      div.innerHTML = `<button type="button" aria-haspopup="dialog" title="画像の保存・共有">${ICON_SHARE}<span>共有</span></button>`;
      div.querySelector("button")!.addEventListener("click", () => void open());
      return div;
    },
    onRemove() {},
  };
  o.map.addControl(control, "bottom-right");

  async function open() {
    const t = ++token;
    view = o.view();
    const url = location.href;
    urlInput.value = url;
    xLink.href = `https://x.com/intent/post?text=${encodeURIComponent(view.text)}&url=${encodeURIComponent(url)}`;
    lineLink.href = `https://social-plugins.line.me/lineit/share?url=${encodeURIComponent(url)}`;
    copyButton.textContent = "コピー";
    nativeButton.hidden = !navigator.share;
    download.removeAttribute("href");
    download.setAttribute("aria-disabled", "true");
    preview.hidden = true;
    status.hidden = false;
    status.textContent = "画像を作っています…";
    dialog.showModal();
    try {
      const canvas = compose(await snapshot(o.map), view, o.font, await logo());
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
      if (t !== token) return;
      if (!blob) throw new Error("toBlob");
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = URL.createObjectURL(blob);
      file = new File([blob], view.fileName, { type: "image/png" });
      preview.src = objectUrl;
      preview.alt = `${view.title}（${view.subtitle}）の地図の画像`;
      preview.hidden = false;
      status.hidden = true;
      download.href = objectUrl;
      download.download = view.fileName;
      download.removeAttribute("aria-disabled");
      nativeButton.textContent = navigator.canShare?.({ files: [file] }) ? "画像をアプリで共有" : "ほかのアプリで共有";
    } catch {
      if (t !== token) return;
      file = null;
      status.textContent = "画像を作れませんでした。リンクの共有はできます。";
    }
  }

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
  nativeButton.addEventListener("click", async () => {
    if (!view) return;
    const url = urlInput.value;
    // 画像を付けて送れる端末（スマートフォンなど）は画像も渡す。送り先によっては URL が落ちるので、文に URL を入れる
    const data: ShareData = file && navigator.canShare?.({ files: [file] })
      ? { files: [file], title: view.title, text: `${view.text} ${url}` }
      : { title: view.title, text: view.text, url };
    try {
      await navigator.share(data);
    } catch {
      // 共有を取り消したとき（AbortError）など。何もしない
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
  const footH = px(12) + legendH + creditLines.length * creditLH + px(12);

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
      const sw = px(14);
      const sh = px(10);
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
  ctx.fillStyle = SUB;
  setFont(10.5);
  for (const line of creditLines) { ctx.fillText(line, pad, y + creditLH * 0.75); y += creditLH; }
  return out;
}

/** 保存する画像のファイル名に使えない文字を除く */
export function safeFileName(name: string): string {
  return name.replace(/[\\/:*?"<>|\s]+/g, "_").replace(/_+/g, "_").slice(0, 120);
}
