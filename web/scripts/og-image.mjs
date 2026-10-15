// SNS で共有されたときの画像（public/og.png、1200×630）を作る。
// 画像を変えたいときだけ手で動かす（ビルドでは動かさない）。playwright が要る:
//   npm install --no-save playwright && node scripts/og-image.mjs
import { readFile } from "node:fs/promises";
import { chromium } from "playwright";

const logo = await readFile(new URL("../public/logo.svg", import.meta.url), "utf8");
// 地図の色分けを思わせる飾り。藍（#0b5cad）の濃淡だけを使い、ロゴの2色から外れないようにする
const tints = [0.08, 0.16, 0.28, 0.42, 0.6, 0.8, 1];
const cells = Array.from({ length: 6 * 7 }, (_, i) => {
  const t = tints[(i * 5 + Math.floor(i / 7) * 3) % tints.length];
  return `<span style="background:rgba(11,92,173,${t})"></span>`;
}).join("");

const html = `<!doctype html><html lang="ja"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=M+PLUS+Rounded+1c:wght@500;700&display=block" rel="stylesheet">
<style>
  html, body { margin: 0; width: 1200px; height: 630px; background: #fff; color: #1c2733;
    font-family: "M PLUS Rounded 1c", sans-serif; }
  .wrap { display: flex; height: 100%; box-sizing: border-box; padding: 72px 80px; gap: 64px; align-items: center; }
  .text { flex: 1; }
  .logo > svg { width: 520px; height: auto; display: block; }
  h1 { font-size: 44px; line-height: 1.45; margin: 48px 0 20px; font-weight: 700; }
  p { font-size: 26px; line-height: 1.6; margin: 0; font-weight: 500; }
  .grid { display: grid; grid-template-columns: repeat(6, 52px); gap: 8px; }
  .grid span { width: 52px; height: 52px; border-radius: 8px; }
  .bar { position: absolute; left: 0; right: 0; bottom: 0; height: 14px; background: #0b5cad; }
</style></head><body>
<div class="wrap">
  <div class="text">
    <div class="logo">${logo}</div>
    <h1>全国の市区町村・町丁目を<br>公開データで色分けした地図</h1>
    <p>人口・外国人・年収・選挙・犯罪・教育など</p>
  </div>
  <div class="grid">${cells}</div>
</div>
<div class="bar"></div>
</body></html>`;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1200, height: 630 } });
await page.setContent(html, { waitUntil: "networkidle" });
await page.evaluate(() => document.fonts.ready);
await page.screenshot({ path: new URL("../public/og.png", import.meta.url).pathname });
await browser.close();
