// 楽天ふるさと納税へのリンクの URL を作る（設計変更記録 #189・#252・#257）。
// 環境変数を読まないので、地図の処理（ブラウザで動く）からも使える。アフィリエイトID は呼ぶ側が渡す
// （ページは lib/rakuten.ts がビルド時の環境変数から、地図は地図のページの data-rakuten から）。

/** アフィリエイトID の形（8桁の英数字を「.」で4つつないだもの） */
export const AFFILIATE_ID_PATTERN = /^[0-9a-f]{8}(\.[0-9a-f]{8}){3}$/i;

/**
 * 自治体の返礼品を楽天市場で探す検索の URL。同じ名前の市町村（府中市など）を見分けるため都道府県名を付ける。
 * 自治体ごとのショップの URL（f＋団体コード6桁＋ローマ字）はローマ字の部分を作れないので、検索にしている。
 * keyword（「米」「果物」など）は、農業の指標のページで名産に近い品が出るように足す言葉（設計変更記録 #252）。
 * 市区町村名を空にすると、都道府県の中の返礼品を探す
 */
export function rakutenFurusatoSearchUrl(prefName: string, muniName: string, keyword = ""): string {
  const words = ["ふるさと納税", keyword, `${prefName}${muniName}`].filter(Boolean).join(" ");
  return `https://search.rakuten.co.jp/search/mall/${encodeURIComponent(words)}/`;
}

/** 楽天の URL を、渡したアフィリエイトID のリンクにする。ID が空・形式違いなら null */
export function affiliateLink(affiliateId: string, url: string): string | null {
  if (!AFFILIATE_ID_PATTERN.test(affiliateId)) return null;
  return `https://hb.afl.rakuten.co.jp/hgc/${affiliateId}/?pc=${encodeURIComponent(url)}&link_type=text`;
}
