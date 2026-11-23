// スマホ（画面の幅 860px 以下）の地図の画面（設計変更記録 #194）。
// 地域の検索を地図の上に常に出し、条件の欄（指標・時点・凡例・表示）と情報の欄（地域の情報）を地図の下端のパネルにまとめる。
// 閉じたパネルには指標の名前・時点・凡例の色の帯だけを出し、押すと開く。パソコンでは何もしない（左右の欄のまま）。
// パネルの上の部分（つまみ・見出し・切替のボタンの帯）を上下に引いても開け閉めできる（設計変更記録 #254）。

/** pages/map/index.astro の @media (max-width: 860px) と同じ */
export const PHONE_QUERY = "(max-width: 860px)";
/** 開いたパネルの高さの上限（地図の画面の高さに対する割合）。index.astro の .map-sheet の max-height と同じ */
const SHEET_MAX = 0.55;
/** 開け閉めの動きの長さ（ms）。index.astro の .map-sheet.settling と同じ */
const SETTLE_MS = 220;

export interface MapSheet {
  /** スマホの画面の並びか */
  isPhone(): boolean;
  /** 地域を選んだとき（地図を押した・検索した）。スマホではパネルを開いて地域の情報を見せる */
  showDetail(): void;
  /** 開いたパネルが地図を隠す高さ（px）の上限。スマホでパネルを開いているときだけ 0 より大きい */
  coveredHeight(): number;
  /** 地図の色分けが出たとき。パネルをまだ開いていなければ、つまみを小さく弾ませて、引けば開くことを知らせる */
  hint(): void;
}

/** 指を離したときに、開くか閉じるかを決める（#254）。
 * height は離したときのパネルの高さ、closed・open は閉じた・開いた高さ、velocity は離す直前の速さ（px/ms、下向きが正）。
 * 速く払ったときはその向きに。ゆっくり離したときは、開いていたなら少し下げただけで閉じ、閉じていたなら少し上げただけで開く */
export function settleOpen(height: number, closed: number, open: number, velocity: number, wasOpen: boolean): boolean {
  if (velocity <= -FLICK) return true;
  if (velocity >= FLICK) return false;
  const range = open - closed;
  if (range <= 0) return wasOpen;
  const ratio = (height - closed) / range;
  return wasOpen ? ratio > 1 - SETTLE : ratio > SETTLE;
}
/** 払ったとみなす速さ（px/ms） */
const FLICK = 0.4;
/** 開け閉めが切り替わるまでに引く割合（閉じた高さと開いた高さの差に対して） */
const SETTLE = 0.2;
/** 押してから、引いたとみなすまでに動く距離（px）。これより小さい動きは押しただけ（開け閉めの切り替え） */
const DRAG_SLOP = 6;

export function initMapSheet(root: HTMLElement): MapSheet {
  const phone = matchMedia(PHONE_QUERY);
  const sheet = root.querySelector<HTMLElement>(".map-sheet")!;
  const head = sheet.querySelector<HTMLButtonElement>(".sheet-head")!;
  const tabs = [...sheet.querySelectorAll<HTMLButtonElement>(".sheet-tabs button")];
  const infoTab = tabs.find((b) => b.dataset.tab === "info")!;
  const searchBar = root.querySelector<HTMLElement>(".map-search")!;
  const search = root.querySelector<HTMLElement>(".search")!;
  const searchHome = root.querySelector<HTMLElement>(".move-tools-body")!;

  // 開いているか（開け閉めの動きの途中でも、行き先の方）。class の open は中身を見せるかどうかで、閉じる動きの間は残す
  let opened = false;
  const isOpen = () => opened;
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
  let settleTimer = 0;
  /** 開け閉めの動き（高さの移り変わり）を止め、高さをパネルの中身に任せる */
  function stopSettle() {
    window.clearTimeout(settleTimer);
    sheet.classList.remove("settling");
    sheet.style.height = "";
    sheet.classList.toggle("open", opened);
  }
  /** 開いたときの高さ（中身の高さか、地図の画面の高さの 55% の低い方）。測るために一度開く */
  function openHeight(): number {
    const shown = sheet.classList.contains("open");
    const h = sheet.style.height;
    sheet.style.height = "";
    sheet.classList.add("open");
    const v = sheet.offsetHeight;
    sheet.classList.toggle("open", shown);
    sheet.style.height = h;
    return v;
  }
  /** 開け閉めする。animate のときは、今の高さから開いた・閉じた高さへなめらかに動かす */
  function setOpen(open: boolean, animate = false) {
    const from = sheet.offsetHeight;
    opened = open;
    stopSettle();
    head.setAttribute("aria-expanded", String(open));
    if (open) {
      sheet.classList.remove("hint");
      sheet.dataset.used = "1";
    }
    if (!animate || reduceMotion.matches || !phone.matches) return;
    const to = open ? openHeight() : head.offsetHeight;
    if (from === to) return;
    // 閉じるときは、閉じ終わるまで中身を見せておく
    sheet.classList.add("open");
    sheet.style.height = `${from}px`;
    void sheet.offsetHeight;
    sheet.classList.add("settling");
    sheet.style.height = `${to}px`;
    settleTimer = window.setTimeout(stopSettle, SETTLE_MS + 40);
  }
  function setTab(tab: string) {
    sheet.dataset.tab = tab;
    for (const b of tabs) b.setAttribute("aria-pressed", String(b.dataset.tab === tab));
  }
  head.addEventListener("click", () => setOpen(!isOpen(), true));
  for (const b of tabs) b.addEventListener("click", () => setTab(b.dataset.tab!));

  // 上下に引いて開け閉めする（#254）。引けるのは、つまみ・見出し・切替のボタンの帯（中の欄は今までどおり送れる）。
  // 引いている間はパネルの高さを指に合わせ、離したら開くか閉じるかを決めて動かす。引いたあとの「押した」は数えない
  const tabBar = sheet.querySelector<HTMLElement>(".sheet-tabs")!;
  let drag: { id: number; el: HTMLElement; y0: number; h0: number; closed: number; open: number; wasOpen: boolean;
    moving: boolean; y: number; t: number; vy: number } | null = null;
  let swallowClick = false;
  function onDown(e: PointerEvent) {
    // 引き始める前に指が見出しの外で離れたときは、前の分が残るので、上書きする
    if (!phone.matches || drag?.moving || !e.isPrimary || (e.pointerType === "mouse" && e.button !== 0)) return;
    const h0 = sheet.offsetHeight;
    drag = { id: e.pointerId, el: e.currentTarget as HTMLElement, y0: e.clientY, h0, closed: head.offsetHeight, open: 0,
      wasOpen: isOpen(), moving: false, y: e.clientY, t: e.timeStamp, vy: 0 };
  }
  function onMove(e: PointerEvent) {
    if (!drag || e.pointerId !== drag.id) return;
    const dy = e.clientY - drag.y0;
    if (!drag.moving) {
      // 閉じているときに下へ引いても何もしない
      if (Math.abs(dy) < DRAG_SLOP || (!drag.wasOpen && dy > 0)) return;
      drag.moving = true;
      drag.el.setPointerCapture(e.pointerId);
      stopSettle();
      drag.open = Math.max(openHeight(), drag.closed);
      sheet.classList.remove("hint");
      sheet.classList.add("open", "dragging");
    }
    const dt = e.timeStamp - drag.t;
    if (dt > 0) drag.vy = (e.clientY - drag.y) / dt;
    drag.y = e.clientY;
    drag.t = e.timeStamp;
    const h = Math.min(drag.open, Math.max(drag.closed, drag.h0 - dy));
    sheet.style.height = `${h}px`;
  }
  function onUp(e: PointerEvent) {
    if (!drag || e.pointerId !== drag.id) return;
    const d = drag;
    drag = null;
    if (!d.moving) return;
    sheet.classList.remove("dragging");
    swallowClick = true;
    if (e.type === "pointercancel") return setOpen(d.wasOpen, true);
    // 離す直前に止めていたときは、払ったとみなさない
    const vy = e.timeStamp - d.t > 80 ? 0 : d.vy;
    setOpen(settleOpen(sheet.offsetHeight, d.closed, d.open, vy, d.wasOpen), true);
  }
  for (const el of [head, tabBar]) {
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
  }
  // 引いて離したあとに続く「押した」を、見出し（開け閉め）にも切替のボタンにも届けない。
  // 「押した」が続かなかったときに次に押したものを止めないよう、パネルのどこかを押し始めたら忘れる
  sheet.addEventListener("pointerdown", () => (swallowClick = false), true);
  sheet.addEventListener("click", (e) => {
    if (!swallowClick) return;
    swallowClick = false;
    e.stopPropagation();
    e.preventDefault();
  }, true);

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
      setOpen(true, !isOpen());
    },
    coveredHeight() {
      if (!phone.matches || !isOpen()) return 0;
      return Math.max(0, root.clientHeight * SHEET_MAX - head.offsetHeight);
    },
    hint() {
      if (!phone.matches || isOpen() || sheet.dataset.used || reduceMotion.matches) return;
      sheet.classList.add("hint");
    },
  };
}
