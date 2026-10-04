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
  ["90-about", "/about/", { width: 1280, height: 900 }],
];

await mkdir(out, { recursive: true });
const browser = await chromium.launch();
let errors = 0;
for (const [name, path, viewport] of shots) {
  const page = await browser.newPage({ viewport, locale: "ja-JP" });
  page.on("pageerror", (e) => { errors++; console.error(`[${name}] ${e.message}`); });
  await page.goto(base + path, { waitUntil: "networkidle", timeout: 60_000 }).catch((e) => console.error(`[${name}] ${e.message}`));
  await page.waitForTimeout(4000); // 地図タイルと塗り分けの描画を待つ
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: !path.startsWith("/map/") });
  console.log(`${out}/${name}.png`);
  await page.close();
}
await browser.close();
if (errors) console.error(`ページ上のエラー: ${errors} 件`);
