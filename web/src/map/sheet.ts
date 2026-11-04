// スマホ（画面の幅 860px 以下）の地図の画面（設計変更記録 #194）。
// 地域の検索を地図の上に常に出し、条件の欄（指標・時点・凡例・表示）と情報の欄（地域の情報）を地図の下端のパネルにまとめる。
// 閉じたパネルには指標の名前・時点・凡例の色の帯だけを出し、押すと開く。パソコンでは何もしない（左右の欄のまま）。

/** pages/map/index.astro の @media (max-width: 860px) と同じ */
export const PHONE_QUERY = "(max-width: 860px)";
/** 開いたパネルの高さの上限（地図の画面の高さに対する割合）。index.astro の .map-sheet の max-height と同じ */
const SHEET_MAX = 0.55;

export interface MapSheet {
  /** スマホの画面の並びか */
  isPhone(): boolean;
  /** 地域を選んだとき（地図を押した・検索した）。スマホではパネルを開いて地域の情報を見せる */
  showDetail(): void;
  /** 開いたパネルが地図を隠す高さ（px）の上限。スマホでパネルを開いているときだけ 0 より大きい */
  coveredHeight(): number;
}

export function initMapSheet(root: HTMLElement): MapSheet {
  const phone = matchMedia(PHONE_QUERY);
  const sheet = root.querySelector<HTMLElement>(".map-sheet")!;
  const head = sheet.querySelector<HTMLButtonElement>(".sheet-head")!;
  const tabs = [...sheet.querySelectorAll<HTMLButtonElement>(".sheet-tabs button")];
  const infoTab = tabs.find((b) => b.dataset.tab === "info")!;
  const searchBar = root.querySelector<HTMLElement>(".map-search")!;
  const search = root.querySelector<HTMLElement>(".search")!;
  const searchHome = root.querySelector<HTMLElement>(".move-tools-body")!;

  const isOpen = () => sheet.classList.contains("open");
  function setOpen(open: boolean) {
    sheet.classList.toggle("open", open);
    head.setAttribute("aria-expanded", String(open));
  }
  function setTab(tab: string) {
    sheet.dataset.tab = tab;
    for (const b of tabs) b.setAttribute("aria-pressed", String(b.dataset.tab === tab));
  }
  head.addEventListener("click", () => setOpen(!isOpen()));
  for (const b of tabs) b.addEventListener("click", () => setTab(b.dataset.tab!));

  // 地域の検索欄は、スマホでは地図の上の帯へ、パソコンでは左の欄の「範囲・地域を検索」の中へ置く（要素ごと移すので、動きはそのまま）
  function place() {
    if (phone.matches) searchBar.append(search);
    else {
      searchHome.append(search);
      setOpen(false);
    }
  }
  phone.addEventListener("change", place);
  place();

  // 閉じたパネルの見出し: 指標の名前・時点・凡例の色の帯。左の欄の表示を写す（地図の処理が書き換えるたびに追う）
  const ioIcon = root.querySelector<HTMLElement>(".io-icon")!;
  const ioName = root.querySelector<HTMLElement>(".io-name")!;
  const periodLabel = root.querySelector<HTMLOutputElement>("#period-label")!;
  const legend = root.querySelector<HTMLElement>("#legend")!;
  const detail = root.querySelector<HTMLElement>("#detail")!;
  const shIcon = head.querySelector<HTMLElement>(".sh-icon")!;
  const shName = head.querySelector<HTMLElement>(".sh-name")!;
  const shPeriod = head.querySelector<HTMLElement>(".sh-period")!;
  const shLegend = head.querySelector<HTMLElement>(".sh-legend")!;
  const shLow = head.querySelector<HTMLElement>(".sh-low")!;
  const shBar = head.querySelector<HTMLElement>(".sh-bar")!;
  const shHigh = head.querySelector<HTMLElement>(".sh-high")!;
  function mirror() {
    shIcon.innerHTML = ioIcon.innerHTML;
    shName.textContent = ioName.textContent;
    // 時点は、凡例の見出しの「（市区町村別・2025年）」を使う（色分けの単位と年が短く分かる）。凡例がないときは時点の欄の文字
    const sub = legend.querySelector(".legend-head .muted")?.textContent?.replace(/^（|）$/g, "");
    shPeriod.textContent = sub || periodLabel.value || periodLabel.textContent;
    const bar = legend.querySelector(".legend-bar");
    const ticks = [...legend.querySelectorAll(".legend-ticks span")].map((t) => t.textContent?.trim() ?? "").filter(Boolean);
    shBar.innerHTML = bar ? bar.innerHTML : "";
    shBar.hidden = !bar;
    // 凡例の帯がないとき（この時点の値がないなど）は、凡例の文をそのまま出す
    shLow.textContent = bar ? (ticks[0] ?? "") : (legend.textContent?.trim() ?? "");
    shHigh.textContent = bar && ticks.length > 1 ? ticks[ticks.length - 1] : "";
    shLegend.classList.toggle("dimmed", legend.classList.contains("dimmed"));
    shLegend.classList.toggle("none", !bar);
    // 地域を選んでいないときは、情報の欄に地図の説明（見出しと文）が入っている
    infoTab.textContent = detail.querySelector(".map-intro") ? "この地図について" : "地域の情報";
  }
  let queued = false;
  const observer = new MutationObserver(() => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      mirror();
    });
  });
  for (const el of [ioIcon, ioName, periodLabel]) observer.observe(el, { childList: true, subtree: true, characterData: true });
  // 凡例は、色分けを消したときに薄くする（class の dimmed）のも写す
  observer.observe(legend, { childList: true, subtree: true, characterData: true, attributeFilter: ["class"] });
  observer.observe(detail, { childList: true });
  mirror();

  return {
    isPhone: () => phone.matches,
    showDetail() {
      if (!phone.matches) return;
      setTab("info");
      setOpen(true);
    },
    coveredHeight() {
      if (!phone.matches || !isOpen()) return 0;
      return Math.max(0, root.clientHeight * SHEET_MAX - head.offsetHeight);
    },
  };
}
