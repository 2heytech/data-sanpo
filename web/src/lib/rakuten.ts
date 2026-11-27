// 楽天アフィリエイト（楽天ふるさと納税へのリンク、設計変更記録 #189）。
// アフィリエイトID（8桁の英数字を「.」で4つつないだもの）はビルド時の環境変数 RAKUTEN_AFFILIATE_ID で渡す。
// 未設定・形式違いならリンクも「広告」の表示も一切出さない。楽天のスクリプト（ウィジェット）は読み込まず、文字のリンクだけにする。
// URL を作る部分は、地図の処理からも使えるよう lib/rakutenUrl.ts に分けている（#257）
import { AFFILIATE_ID_PATTERN, affiliateLink, rakutenFurusatoSearchUrl } from "./rakutenUrl";

export { rakutenFurusatoSearchUrl };

const raw = (process.env.RAKUTEN_AFFILIATE_ID ?? "").trim();
export const RAKUTEN_AFFILIATE_ID = AFFILIATE_ID_PATTERN.test(raw) ? raw : "";
if (raw && !RAKUTEN_AFFILIATE_ID) console.warn("RAKUTEN_AFFILIATE_ID の形式が違うため楽天のリンクを出しません（8桁の英数字を「.」で4つつないだもの）");

/** 楽天ふるさと納税のトップ */
export const RAKUTEN_FURUSATO_TOP = "https://event.rakuten.co.jp/furusato/";

/** 楽天の URL をアフィリエイトのリンクにする。ID がなければ null */
export function rakutenAffiliateUrl(url: string): string | null {
  return affiliateLink(RAKUTEN_AFFILIATE_ID, url);
}

// 返礼品の画像（楽天市場商品検索 API、設計変更記録 #195）。アプリは「Webアプリケーション」として登録し、
// 許可するサイト（data-sanpo.com）からのブラウザの呼び出しだけが通る。アプリIDとアクセスキーはページに載る公開値。
// どちらかが未設定・形式違いなら画像は出さない（リンクのボタンだけになる）
const appRaw = (process.env.RAKUTEN_APP_ID ?? "").trim();
const keyRaw = (process.env.RAKUTEN_ACCESS_KEY ?? "").trim();
const appOk = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(appRaw);
const keyOk = /^pk_[0-9A-Za-z_-]{10,}$/.test(keyRaw);
if ((appRaw || keyRaw) && !(appOk && keyOk)) console.warn("RAKUTEN_APP_ID・RAKUTEN_ACCESS_KEY の形式が違うため返礼品の画像を出しません");
export const RAKUTEN_API = appOk && keyOk && RAKUTEN_AFFILIATE_ID
  ? { appId: appRaw, accessKey: keyRaw, affiliateId: RAKUTEN_AFFILIATE_ID } : null;
