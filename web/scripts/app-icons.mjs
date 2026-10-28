// ホーム画面に追加したときのアイコン（public/apple-touch-icon.png・icon-192.png・icon-512.png、設計変更記録 #171）を作る。
// 足あとマーク（public/logo-mark.svg）を白地の真ん中に置く。画像を変えたいときだけ手で動かす（ビルドでは動かさない）:
//   node scripts/app-icons.mjs
import { readFile, writeFile } from "node:fs/promises";
import { Resvg } from "@resvg/resvg-js";

const mark = await readFile(new URL("../public/logo-mark.svg", import.meta.url), "utf8");
const inner = mark.replace(/^<svg[^>]*>/, "").replace(/<\/svg>\s*$/, "");
const [W, H] = mark.match(/viewBox="0 0 (\d+) (\d+)"/).slice(1).map(Number);

// 足あと2歩の描かれている範囲（中心と、中心から一番遠い点までの距離）を、大きく描いて測る
// pixels は読むたびに複製を作るので、一度だけ読む
const { width, height, pixels } = new Resvg(mark, { fitTo: { mode: "width", value: W * 10 } }).render();
const unit = W / width;
const inked = [];
for (let y = 0; y < height; y++) {
  for (let x = 0; x < width; x++) {
    if (pixels[(y * width + x) * 4 + 3] > 8) inked.push([(x + 0.5) * unit, (y + 0.5) * unit]);
  }
}
const range = (vs) => vs.reduce(([lo, hi], v) => [Math.min(lo, v), Math.max(hi, v)], [Infinity, -Infinity]);
const [x0, x1] = range(inked.map((p) => p[0]));
const [y0, y1] = range(inked.map((p) => p[1]));
const cx = (x0 + x1) / 2;
const cy = (y0 + y1) / 2;
const radius = range(inked.map(([x, y]) => Math.hypot(x - cx, y - cy)))[1];
if (!(radius > 0 && radius < Math.max(W, H))) throw new Error("足あとマークの範囲を測れませんでした");

// Android の丸や角丸のマスク（maskable）でも切れない円（一辺の 40%）より内側の 36% に収める。iPhone の角丸でも余白が残る
const FILL = 0.36;
for (const [file, size] of [["apple-touch-icon.png", 180], ["icon-192.png", 192], ["icon-512.png", 512]]) {
  const scale = (size * FILL) / radius;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">` +
    `<rect width="${size}" height="${size}" fill="#fff"/>` +
    `<g transform="translate(${size / 2} ${size / 2}) scale(${scale}) translate(${-cx} ${-cy})">${inner}</g></svg>`;
  await writeFile(new URL(`../public/${file}`, import.meta.url), new Resvg(svg).render().asPng());
  console.log(`public/${file}（${size}×${size}）`);
}
