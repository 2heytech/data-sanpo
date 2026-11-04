// MapLibre の ES モジュール（本体・共有部・Worker）を public/vendor/ に置く。
// Worker は本体と同じ場所から相対パスで読み込まれるため、バンドルせずにそのまま配信する。
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const pkgDir = join(webDir, "node_modules/maplibre-gl");
const { version } = JSON.parse(readFileSync(join(pkgDir, "package.json"), "utf8"));
// フォルダ名に「@」を使わない。Cloudflare の配信が「@」を「%40」に直す転送（307）を毎回返し、地図を開くたびに余分な往復が3回入るため（設計変更記録 #174）
const dest = join(webDir, "public/vendor", `maplibre-gl-${version}`);
rmSync(join(webDir, "public/vendor"), { recursive: true, force: true });
mkdirSync(dest, { recursive: true });
// 末尾の sourceMappingURL の行は外す。.map は配らないので、ブラウザの開発ツールがないファイルを取りに行くだけになる（設計変更記録 #147）。
// 冒頭の利用条件（@license）は残す
for (const f of ["maplibre-gl.mjs", "maplibre-gl-shared.mjs", "maplibre-gl-worker.mjs"]) {
  const code = readFileSync(join(pkgDir, "dist", f), "utf8");
  writeFileSync(join(dest, f), code.replace(/\n\/\/# sourceMappingURL=\S+\s*$/, "\n"));
}
cpSync(join(pkgDir, "LICENSE.txt"), join(dest, "LICENSE.txt"));
console.log(`MapLibre ${version} を ${dest} に配置しました`);
