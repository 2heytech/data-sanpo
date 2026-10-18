// ビルド済みサイトを開いて主要ページの画面写真を撮る（Data release のプレビュー用）。
// 使い方: node scripts/screenshots.mjs <サイトのURL> <出力先>
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright";

const [base = "http://127.0.0.1:4321", out = "screenshots"] = process.argv.slice(2);

const shots = [
  ["01-top", "/", { width: 1280, height: 900 }],
  ["02-map-population", "/map/", { width: 1280, height: 900 }],
  ["03-map-aged-share", "/map/?i=aged_65_plus_share", { width: 1280, height: 900 }],
  ["04-map-chiyoda", "/map/?i=population_density&a=muni-13101", { width: 1280, height: 900 }],
  ["05-area-setagaya", "/areas/muni-13112/", { width: 1280, height: 1200 }],
  ["06-map-phone", "/map/?i=aged_65_plus_share", { width: 390, height: 844 }],
  ["07-map-2010", "/map/?i=aged_65_plus_share&p=2010-10-01", { width: 1280, height: 900 }],
  ["08-map-marunouchi", "/map/?i=population_total&a=area-13101001001", { width: 1280, height: 900 }],
  ["09-map-growth", "/map/?i=population_change_rate", { width: 1280, height: 900 }],
  ["10-map-household", "/map/?i=persons_per_household&a=muni-13104", { width: 1280, height: 900 }],
  ["11-map-university", "/map/?i=university_graduate_share", { width: 1280, height: 900 }],
  ["12-map-education-unknown", "/map/?i=education_unknown_share&a=muni-13101", { width: 1280, height: 900 }],
  ["13-map-crime", "/map/?i=crime_total&a=muni-13101", { width: 1280, height: 900 }],
  ["14-map-crime-residents", "/map/?i=crime_total_per_100_residents&a=muni-13101", { width: 1280, height: 900 }],
  ["15-map-crime-daytime", "/map/?i=crime_total_per_100_daytime&a=muni-13101", { width: 1280, height: 900 }],
  ["16-map-crime-marunouchi", "/map/?i=crime_total&a=area-13101001001", { width: 1280, height: 900 }],
  ["19-map-crime-violent-5y", "/map/?i=crime_violent&p=2021-2025&a=muni-13104", { width: 1280, height: 900 }],
  ["17-map-stations", "/map/?i=population_total&s=station-003700-3afb24", { width: 1280, height: 900 }],
  ["18-map-schools", "/map/?i=children_0_14_share&sc=school-201150", { width: 1280, height: 900 }],
  ["20-map-traffic-residents", "/map/?i=traffic_accidents_per_100_residents&a=muni-13104", { width: 1280, height: 900 }],
  ["21-map-schools-mikura", "/map/?i=population_total&sc=school-276010", { width: 1280, height: 900 }],
  // 全国版（東京都だけの公開版では、地図は東京都以外が灰色、地域ページは 404 になる）
  ["30-map-japan", "/map/?i=aged_65_plus_share", { width: 1280, height: 900 }],
  ["31-map-osaka-kita", "/map/?i=population_density&a=muni-27127", { width: 1280, height: 900 }],
  ["32-map-sapporo-chuo", "/map/?i=single_person_household_share&a=muni-01101", { width: 1280, height: 900 }],
  ["33-area-yokohama-naka", "/areas/muni-14104/", { width: 1280, height: 1200 }],
  // 東京都以外の点（駅・地価は値あり、学校・保育所は位置だけ）と2025年国勢調査（市区町村）
  ["34-map-osaka-points", "/map/?i=population_total&a=muni-27127&show=stations,schools,land,nurseries", { width: 1280, height: 900 }],
  ["35-map-2025-aged", "/map/?i=aged_65_plus_share&p=2025-10-01", { width: 1280, height: 900 }],
  // 天気（気象庁の平年値、観測所の点）。全国の降水量と、東京の観測所を選んだところ
  ["36-map-weather-japan", "/map/?i=population_total&show=weather&wx=precipitation_normal", { width: 1280, height: 900 }],
  ["37-map-weather-tokyo", "/map/?i=population_total&show=weather&wx=sunshine_normal&ws=wx-44132", { width: 1280, height: 900 }],
  // 全国の犯罪（警察庁の都道府県別、都道府県警察の窃盗7手口）。市区町村の年ごとと、町丁目の5年合計
  ["38-map-npa-crime", "/map/?i=crime_npa_total_per_100_residents", { width: 1280, height: 900 }],
  ["39-map-street-crime-japan", "/map/?i=street_crime_total&p=2025-01-01", { width: 1280, height: 900 }],
  ["40-map-street-crime-osaka", "/map/?i=street_crime_total&a=muni-27127", { width: 1280, height: 900 }],
  ["41-map-street-crime-nagoya", "/map/?i=street_crime_bicycle&a=muni-23106", { width: 1280, height: 900 }],
  // 空港の乗降客数・港の船舶乗降人員（点）。全国と、羽田空港を選んだところ
  ["42-map-airports-ports", "/map/?i=population_total&show=airports,ports", { width: 1280, height: 900 }],
  ["43-map-airport-haneda", "/map/?i=population_total&show=airports,ports&ap=airport-681ee300", { width: 1280, height: 900 }],
  ["44-map-port-okata", "/map/?i=population_total&show=airports,ports&pt=port-13-7c5c475d", { width: 1280, height: 900 }],
  // 全国の国政選挙（総務省の結果調）。比例代表の得票率は市区町村・都道府県、投票率は都道府県
  ["45-map-vote-ldp-japan", "/map/?i=vote_share_ldp&p=2024-10-27", { width: 1280, height: 900 }],
  ["46-map-vote-sanseito-osaka", "/map/?i=vote_share_sanseito&p=2025-07-20&a=muni-27127", { width: 1280, height: 900 }],
  ["47-map-turnout-japan", "/map/?i=voter_turnout&p=2026-02-08", { width: 1280, height: 900 }],
  // 面積と財政（design-changes #119）。将来負担比率の「－」（0%と注記）、政令市の区（値なし）、2016年度の課税対象所得
  ["48-map-area", "/map/?i=area&a=muni-13101", { width: 1280, height: 900 }],
  ["49-map-fiscal-strength", "/map/?i=fiscal_strength_index&a=muni-13101", { width: 1280, height: 900 }],
  ["50-map-future-burden", "/map/?i=future_burden_ratio&a=muni-13101", { width: 1280, height: 900 }],
  ["51-map-debt-yokohama", "/map/?i=local_debt_per_capita&a=muni-14104", { width: 1280, height: 900 }],
  ["52-map-income-2016", "/map/?i=taxable_income_per_taxpayer&p=2016-04-01&a=muni-13112", { width: 1280, height: 900 }],
  ["53-indicator-fiscal-strength", "/indicators/fiscal_strength_index/", { width: 1280, height: 1200 }],
  // 観光（#149）。都道府県の延べ宿泊者数、熱海市の入湯税と町丁目の宿泊業、道の駅と文化財の点（スマホも）
  ["54-map-guest-nights", "/map/?i=guest_nights", { width: 1280, height: 900 }],
  ["55-map-onsen-tax-atami", "/map/?i=onsen_tax&a=muni-22205", { width: 1280, height: 900 }],
  ["56-map-accommodation-atami", "/map/?i=accommodation_establishments&l=small_area&a=muni-22205", { width: 1280, height: 900 }],
  ["57-map-michi-no-eki", "/map/?i=roadside_stations&show=michi", { width: 1280, height: 900 }],
  ["58-map-cultural-properties", "/map/?i=historic_sites&show=bunka&a=muni-22205", { width: 1280, height: 900 }],
  ["59-map-michi-phone", "/map/?i=roadside_stations&show=michi", { width: 390, height: 844 }],
  ["90-about", "/about/", { width: 1280, height: 900 }],
];

await mkdir(out, { recursive: true });
const browser = await chromium.launch();
let errors = 0;

async function shoot([name, path, viewport]) {
  const page = await browser.newPage({ viewport, locale: "ja-JP" });
  page.on("pageerror", (e) => { errors++; console.error(`[${name}] ${e.message}`); });
  const open = () => page.goto(base + path, { waitUntil: "networkidle", timeout: 60_000 }).catch((e) => console.error(`[${name}] ${e.message}`));
  await open();
  // 同時に開くと読み込みが遅れることがあるので、地図は凡例（色の見本か「値がない」の文）が出る（指標の値を読み終える）まで待つ。出なければ1回だけ開き直す
  if (path.startsWith("/map/")) {
    const ready = () => page.waitForSelector("#legend .swatch, #legend p", { timeout: 20_000 }).then(() => true, () => false);
    if (!(await ready())) {
      console.error(`[${name}] 凡例が出ないので開き直します`);
      await open();
      if (!(await ready())) console.error(`[${name}] 凡例が出ません`);
    }
  }
  await page.waitForTimeout(4000); // 地図タイルと塗り分けの描画を待つ
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: !path.startsWith("/map/") });
  console.log(`${out}/${name}.png`);
  await page.close();
}

// 1枚ずつだと待ち時間（読み込みと描画待ち）が積み重なって4分かかるので、いくつか同時に開く
const concurrency = Number(process.env.SCREENSHOT_CONCURRENCY ?? 4);
const queue = [...shots];
await Promise.all(Array.from({ length: concurrency }, async () => {
  for (let s; (s = queue.shift()); ) await shoot(s);
}));
await browser.close();
if (errors) console.error(`ページ上のエラー: ${errors} 件`);
