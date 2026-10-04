// 公開版のデータを public/data/<release_id>/ に配置し、ビルドで参照する版を固定する。
//   DATA_RELEASE_DIR=<dir>  使う公開版のディレクトリ（省略時は ../data/releases の最新）
// 版はビルド時に固定し、新旧データの混在を防ぐ（設計書 第9章「容量とキャッシュ」）。
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const releasesDir = resolve(webDir, "../data/releases");

function latestRelease() {
  if (!existsSync(releasesDir)) return null;
  const candidates = readdirSync(releasesDir)
    .map((name) => join(releasesDir, name))
    .filter((p) => statSync(p).isDirectory() && existsSync(join(p, "manifest.json")))
    .map((p) => ({ p, created: JSON.parse(readFileSync(join(p, "manifest.json"), "utf8")).created_at }))
    .sort((a, b) => a.created.localeCompare(b.created));
  return candidates.at(-1)?.p ?? null;
}

const source = process.env.DATA_RELEASE_DIR ? resolve(process.env.DATA_RELEASE_DIR) : latestRelease();
if (!source || !existsSync(join(source, "manifest.json"))) {
  console.error(
    "公開版のデータが見つかりません。\n" +
      "  開発用の架空データ: npm run fixture\n" +
      "  実データ: pipeline の README に従って python -m tdm build を実行",
  );
  process.exit(1);
}

const manifest = JSON.parse(readFileSync(join(source, "manifest.json"), "utf8"));
for (const f of manifest.files) {
  if (!existsSync(join(source, f.path))) {
    console.error(`manifest にあるファイルがありません: ${f.path}`);
    process.exit(1);
  }
}

const publicData = join(webDir, "public/data");
rmSync(publicData, { recursive: true, force: true });
mkdirSync(publicData, { recursive: true });
cpSync(source, join(publicData, manifest.release_id), { recursive: true });

const info = {
  release_id: manifest.release_id,
  created_at: manifest.created_at,
  is_fixture: manifest.release_id === "dev-fixture",
};
mkdirSync(join(webDir, "src/generated"), { recursive: true });
writeFileSync(join(webDir, "src/generated/release.json"), JSON.stringify(info, null, 2) + "\n");
// 利用回数の窓口（worker/）が受け付ける指標 ID の一覧
const indicatorIds = JSON.parse(readFileSync(join(source, "indicators.json"), "utf8")).indicators.map((i) => i.id);
writeFileSync(join(webDir, "src/generated/indicator-ids.json"), JSON.stringify(indicatorIds) + "\n");
console.log(`公開版 ${manifest.release_id} を使用します（${source}）`);
