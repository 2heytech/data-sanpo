// MapLibre の ES モジュール（本体・共有部・Worker）を public/vendor/ に置く。
// Worker は本体と同じ場所から相対パスで読み込まれるため、バンドルせずにそのまま配信する。
import { cpSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const pkgDir = join(webDir, "node_modules/maplibre-gl");
const { version } = JSON.parse(readFileSync(join(pkgDir, "package.json"), "utf8"));
const dest = join(webDir, "public/vendor", `maplibre-gl@${version}`);
rmSync(join(webDir, "public/vendor"), { recursive: true, force: true });
mkdirSync(dest, { recursive: true });
for (const f of ["maplibre-gl.mjs", "maplibre-gl-shared.mjs", "maplibre-gl-worker.mjs"]) {
  cpSync(join(pkgDir, "dist", f), join(dest, f));
}
cpSync(join(pkgDir, "LICENSE.txt"), join(dest, "LICENSE.txt"));
console.log(`MapLibre ${version} を ${dest} に配置しました`);
