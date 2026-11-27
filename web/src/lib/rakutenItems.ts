// 楽天ふるさと納税の返礼品の例を、楽天市場商品検索 API から取って画像付きで並べる（設計変更記録 #195・#257）。
// ブラウザで動く。地域ページ・都道府県ページの返礼品の欄（components/FurusatoItems.astro）と、地図の地域の情報の欄（map/app.ts）で使う。
// アプリID・アクセスキー・アフィリエイトID はページに載る公開値で、ビルド時にあるときだけページの data-* に入る。
// 取れなかったとき・その自治体の品が見つからないときは空を返し、呼ぶ側はリンクのボタンだけにする

const ENDPOINT = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701";
/** 楽天ウェブサービスのクレジット表示（楽天の指定のテキスト版のリンク。API を使って表示したときだけ出す） */
export const RAKUTEN_CREDIT_HTML = '<a href="https://developers.rakuten.com/" target="_blank">Supported by Rakuten Developers</a>';

export interface RakutenApi { appId: string; accessKey: string; affiliateId: string }

export interface FurusatoItem {
  name: string;
  /** 寄附額（円） */
  price: number;
  href: string;
  /** 240px 角の画像。なければ空 */
  image: string;
}

interface RawItem {
  itemName?: string; itemPrice?: number; affiliateUrl?: string; itemUrl?: string; shopName?: string;
  mediumImageUrls?: (string | { imageUrl: string })[];
}

const NO_GIFT = /返礼品(は|が)?(ありません|なし|無し)/;
const TRAVEL = /楽天トラベル.?クーポン/;

/**
 * 検索結果から、その自治体の返礼品だけを選ぶ。別の自治体の品を出さないよう、ショップ名に自治体の名前がある品だけにする
 * （市区町村名が空なら、都道府県名のあるショップ）。返礼品のない寄附（災害の応援など）は除き、
 * 楽天トラベルクーポンは金額違いが並びやすいので1つだけにする
 */
export function pickFurusatoItems(data: unknown, pref: string, name: string): FurusatoItem[] {
  const d = (data ?? {}) as { Items?: RawItem[]; items?: RawItem[] };
  const all = (d.Items ?? d.items ?? []).filter((it) => {
    const shop = it.shopName ?? "";
    return name ? shop.includes(`${pref}${name}`) || shop.includes(name) : !!pref && shop.includes(pref);
  }).filter((it) => !NO_GIFT.test(it.itemName ?? ""));
  return all
    .filter((it, i) => !TRAVEL.test(it.itemName ?? "") || all.findIndex((x) => TRAVEL.test(x.itemName ?? "")) === i)
    .map((it) => {
      const img = it.mediumImageUrls?.[0];
      const src = typeof img === "string" ? img : img?.imageUrl ?? "";
      // どの品の名前も「【ふるさと納税】」で始まり、2行までの名前の場所を取るので、表示では外す
      return {
        name: (it.itemName ?? "").replace(/^\s*【ふるさと納税】\s*/, ""), price: Number(it.itemPrice ?? 0), href: it.affiliateUrl || it.itemUrl || "",
        image: src.replace(/_ex=\d+x\d+/, "_ex=240x240"),
      };
    })
    .filter((it) => it.href);
}

// 同じ自治体を何度も選んだとき・同じページの2つの欄で、楽天へ問い合わせるのを1回にする
const cache = new Map<string, Promise<FurusatoItem[]>>();

/** その自治体（市区町村名が空なら都道府県）の返礼品を最大30件の検索から選ぶ。失敗したら空 */
export function fetchFurusatoItems(api: RakutenApi, pref: string, name: string): Promise<FurusatoItem[]> {
  const key = `${pref}|${name}`;
  let p = cache.get(key);
  if (!p) {
    const q = new URLSearchParams({
      applicationId: api.appId, accessKey: api.accessKey, affiliateId: api.affiliateId, format: "json", formatVersion: "2",
      keyword: `ふるさと納税 ${pref}${name}`, hits: "30", imageFlag: "1",
    });
    p = fetch(`${ENDPOINT}?${q}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => pickFurusatoItems(data, pref, name), () => []);
    // 失敗したときは覚えておかない（次に選んだときに問い合わせ直す）
    p.then((items) => { if (items.length === 0) cache.delete(key); });
    cache.set(key, p);
  }
  return p;
}

/**
 * 返礼品を ul に並べる。trackText を渡すと、GA に送る文字を商品名の代わりにそれにする（地図では地域の名前を送らない、#255）
 */
export function renderFurusatoItems(ul: HTMLElement, items: FurusatoItem[], trackText?: string): void {
  ul.replaceChildren(...items.map((it) => {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = it.href;
    a.target = "_blank";
    a.rel = "sponsored noopener";
    if (trackText) a.dataset.trackText = trackText;
    if (it.image) {
      const im = document.createElement("img");
      im.src = it.image; im.alt = ""; im.loading = "lazy"; im.width = 240; im.height = 240;
      a.append(im);
    }
    const t = document.createElement("span");
    t.className = "item-name";
    t.textContent = it.name;
    const p = document.createElement("span");
    p.className = "item-price";
    p.textContent = `寄附額 ${it.price.toLocaleString("ja-JP")}円`;
    a.append(t, p);
    li.append(a);
    return li;
  }));
}

/**
 * 同じ自治体の欄がページに2つある（地域ページの中ほどと最後）とき、最後の欄は5件目から並べて同じ品を繰り返さない。
 * 並べる数に足りなければ最初から並べる
 */
export function itemsFrom(items: FurusatoItem[], offset: number, count: number): FurusatoItem[] {
  return items.length >= offset + count ? items.slice(offset, offset + count) : items.slice(0, count);
}
