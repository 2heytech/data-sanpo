// 楽天アフィリエイト（楽天ふるさと納税へのリンク、設計変更記録 #189）。
// アフィリエイトID（8桁の英数字を「.」で4つつないだもの）はビルド時の環境変数 RAKUTEN_AFFILIATE_ID で渡す。
// 未設定・形式違いならリンクも「広告」の表示も一切出さない。楽天のスクリプト（ウィジェット）は読み込まず、文字のリンクだけにする。
const raw = (process.env.RAKUTEN_AFFILIATE_ID ?? "").trim();
export const RAKUTEN_AFFILIATE_ID = /^[0-9a-f]{8}(\.[0-9a-f]{8}){3}$/i.test(raw) ? raw : "";
if (raw && !RAKUTEN_AFFILIATE_ID) console.warn("RAKUTEN_AFFILIATE_ID の形式が違うため楽天のリンクを出しません（8桁の英数字を「.」で4つつないだもの）");

/** 楽天ふるさと納税のトップ */
export const RAKUTEN_FURUSATO_TOP = "https://event.rakuten.co.jp/furusato/";

/**
 * 自治体の返礼品を楽天市場で探す検索の URL。同じ名前の市町村（府中市など）を見分けるため都道府県名を付ける。
 * 自治体ごとのショップの URL（f＋団体コード6桁＋ローマ字）はローマ字の部分を作れないので、検索にしている
 */
export function rakutenFurusatoSearchUrl(prefName: string, muniName: string): string {
  return `https://search.rakuten.co.jp/search/mall/${encodeURIComponent(`ふるさと納税 ${prefName}${muniName}`)}/`;
}

/** 楽天の URL をアフィリエイトのリンクにする。ID がなければ null */
export function rakutenAffiliateUrl(url: string): string | null {
  if (!RAKUTEN_AFFILIATE_ID) return null;
  return `https://hb.afl.rakuten.co.jp/hgc/${RAKUTEN_AFFILIATE_ID}/?pc=${encodeURIComponent(url)}&link_type=text`;
}
