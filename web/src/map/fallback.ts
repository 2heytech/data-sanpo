// 地図を表示できない環境への案内（設計変更記録 #196）。WebGL2 が使えない（ブラウザ・端末の設定、古い端末など）か、
// 地図の部品・データを読み込めなかったときに、地図の場所に説明・静止画の地図・指標と地域のページへのリンクを出す。
// 案内の文と既定の指標の分は地図のページに書いてあり、ほかの指標・地域を選んだ URL のときだけ FALLBACK_URL を読んで差し替える
import { FALLBACK_URL, fallbackView, type FallbackView, type MapFallbackData } from "../lib/mapFallback";
import { parseState } from "../lib/urlstate";

/** webgl: WebGL2 が使えない。load: 地図の部品（MapLibre）や指標の一覧を読み込めない */
export type FallbackReason = "webgl" | "load";

/** WebGL2 が使えるか（MapLibre は WebGL2 で描く）。確かめるために作った描画の準備はすぐ手放す */
export function supportsWebGL2(): boolean {
  try {
    const gl = document.createElement("canvas").getContext("webgl2");
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
    return !!gl;
  } catch {
    return false;
  }
}

export function showMapFallback(root: HTMLElement, reason: FallbackReason): void {
  const box = root.querySelector<HTMLElement>("#map-fallback");
  if (!box || !box.hidden) return;
  for (const el of box.querySelectorAll<HTMLElement>("[data-reason]")) el.hidden = el.dataset.reason !== reason;
  root.classList.add("no-map");
  box.hidden = false;
  const state = parseState(location.search);
  const custom = (state.indicator && state.indicator !== box.dataset.default) || state.area;
  const data: Promise<MapFallbackData | null> = custom
    ? fetch(FALLBACK_URL).then((r) => (r.ok ? (r.json() as Promise<MapFallbackData>) : null)).catch(() => null)
    : Promise.resolve(null);
  void data.then((d) => {
    if (d) applyView(box, fallbackView(state, d));
    showImage(box);
  });
}

/** 先頭のリンク（指標・地域のページ）と静止画の地図を、URL で選んでいたものに差し替える */
function applyView(box: HTMLElement, view: FallbackView): void {
  const list = box.querySelector<HTMLUListElement>(".mf-links");
  const icon = list?.querySelector("svg");
  if (list) {
    list.querySelectorAll("li[data-dynamic]").forEach((li) => li.remove());
    const items = view.links.map((link) => {
      const li = document.createElement("li");
      li.dataset.dynamic = "";
      const a = li.appendChild(document.createElement("a"));
      a.href = link.href;
      const span = a.appendChild(document.createElement("span"));
      span.append(link.text);
      span.appendChild(document.createElement("small")).textContent = link.note;
      if (icon) a.appendChild(icon.cloneNode(true));
      return li;
    });
    list.prepend(...items);
  }
  const fig = box.querySelector<HTMLElement>(".mf-figure");
  const img = fig?.querySelector("img");
  if (!fig || !img || !view.image) return;
  img.dataset.src = view.image.path;
  img.alt = view.image.alt;
  fig.querySelector("a")?.setAttribute("href", view.image.href);
  const caption = fig.querySelector("figcaption");
  if (caption) caption.textContent = view.image.alt;
}

/** 静止画の地図は案内を出すときに読み込む（ふだん地図が出る人には読ませない）。読めなければ枠ごと隠す */
function showImage(box: HTMLElement): void {
  const fig = box.querySelector<HTMLElement>(".mf-figure");
  const img = fig?.querySelector("img");
  if (!fig || !img?.dataset.src) return;
  img.addEventListener("error", () => { fig.hidden = true; }, { once: true });
  img.src = img.dataset.src;
  fig.hidden = false;
}
