// 地図の画像（都道府県ページ・記事の共有画像、設計変更記録 #142）の文字に使うフォントを用意する。
// M PLUS Rounded 1c（ロゴと同じ字体、SIL Open Font License 1.1）を、画像に出る文字だけに絞って Google Fonts から取る。
// 画像に出る文字が増えたとき（記事の題名・指標の名前・単位など）に手で動かし、できたファイルをコミットする:
//   node scripts/image-font.mjs
// ビルドは src/assets/image-fonts/chars.txt にない文字があると止まる（src/lib/mapImage.ts）。
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const out = join(root, "src/assets/image-fonts");

// 47都道府県（公開版の areas.json と同じ名前）
const PREFECTURES = "北海道 青森県 岩手県 宮城県 秋田県 山形県 福島県 茨城県 栃木県 群馬県 埼玉県 千葉県 東京都 神奈川県 新潟県 富山県 石川県 福井県 山梨県 長野県 岐阜県 静岡県 愛知県 三重県 滋賀県 京都府 大阪府 兵庫県 奈良県 和歌山県 鳥取県 島根県 岡山県 広島県 山口県 徳島県 香川県 愛媛県 高知県 福岡県 佐賀県 長崎県 熊本県 大分県 宮崎県 鹿児島県 沖縄県";

const text = [
  PREFECTURES,
  // 画像の決まった文言（mapImage.ts と shareImages.ts に書いた文字。コメントの文字も含まれるが害はない）
  readFileSync(join(root, "src/lib/mapImage.ts"), "utf8"),
  readFileSync(join(root, "src/lib/shareImages.ts"), "utf8"),
  // 記事の題名
  [...readFileSync(join(root, "src/lib/articles.ts"), "utf8").matchAll(/title: "([^"]+)"/g)].map((m) => m[1]).join(""),
  // 指標の名前・単位・時点（記事の画像の副題と凡例に出る）。説明文などは画像に出ないので入れない
  readFileSync(join(root, "../pipeline/config/indicators.toml"), "utf8").split("\n")
    .filter((l) => /^(name|unit|period_labels)\s*=/.test(l)).join(""),
  // 出典の提供者（記事の画像の出典の行に出る）
  readFileSync(join(root, "../pipeline/config/sources.toml"), "utf8").split("\n")
    .filter((l) => /^provider\s*=/.test(l)).join(""),
  // 時点の名前・凡例の数・開発用の架空データの出典（tdm/fixture.py）
  "年月日現在度合計卒業実施公開万億開発用",
  // 英数字と記号
  Array.from({ length: 95 }, (_, i) => String.fromCharCode(32 + i)).join(""),
  "−＋～〜→・、。（）「」：％",
].join("");
const chars = [...new Set([...text].filter((c) => c >= " " && c !== "\u007f"))].sort().join("");

/** フォントにある文字（cmap の形式4・12を読む）。Google Fonts から返ったフォントにない文字を chars.txt に入れないため */
function coveredChars(buf) {
  const tables = buf.readUInt16BE(4);
  let cmap = -1;
  for (let i = 0; i < tables; i++) {
    if (buf.toString("latin1", 12 + i * 16, 16 + i * 16) === "cmap") cmap = buf.readUInt32BE(20 + i * 16);
  }
  const has = new Set();
  for (let i = 0; i < buf.readUInt16BE(cmap + 2); i++) {
    const at = cmap + buf.readUInt32BE(cmap + 8 + i * 8);
    const format = buf.readUInt16BE(at);
    if (format === 4) {
      const seg = buf.readUInt16BE(at + 6) / 2;
      const ends = at + 14, starts = ends + seg * 2 + 2, deltas = starts + seg * 2, ranges = deltas + seg * 2;
      for (let s = 0; s < seg; s++) {
        const end = buf.readUInt16BE(ends + s * 2), start = buf.readUInt16BE(starts + s * 2);
        const delta = buf.readInt16BE(deltas + s * 2), range = buf.readUInt16BE(ranges + s * 2);
        for (let c = start; c <= end && c !== 0xffff; c++) {
          let gid = range === 0 ? c : buf.readUInt16BE(ranges + s * 2 + range + (c - start) * 2);
          if (range !== 0 && gid === 0) continue;
          gid = (gid + delta) & 0xffff;
          if (gid) has.add(String.fromCodePoint(c));
        }
      }
    } else if (format === 12) {
      for (let g = 0; g < buf.readUInt32BE(at + 12); g++) {
        const start = buf.readUInt32BE(at + 16 + g * 12), end = buf.readUInt32BE(at + 20 + g * 12);
        for (let c = start; c <= end; c++) has.add(String.fromCodePoint(c));
      }
    }
  }
  return has;
}

mkdirSync(out, { recursive: true });
let covered = null;
for (const weight of [500, 700]) {
  const css = await (await fetch(
    `https://fonts.googleapis.com/css2?family=M+PLUS+Rounded+1c:wght@${weight}&text=${encodeURIComponent(chars)}`,
    // 古い形式（truetype）で返してもらう。resvg は woff2 を読めない
    { headers: { "user-agent": "Wget/1.21" } },
  )).text();
  const url = /url\((https:[^)]+)\) format\('truetype'\)/.exec(css)?.[1];
  if (!url) throw new Error(`フォントの URL が見つかりません: ${css.slice(0, 200)}`);
  const buf = Buffer.from(await (await fetch(url)).arrayBuffer());
  writeFileSync(join(out, `mplus-rounded-1c-${weight}.ttf`), buf);
  console.log(`mplus-rounded-1c-${weight}.ttf: ${buf.length.toLocaleString()} bytes`);
  const has = coveredChars(buf);
  covered = covered ? new Set([...covered].filter((c) => has.has(c))) : has;
}
// 空白は字形がなくても描ける
const usable = [...chars].filter((c) => c === " " || covered.has(c));
const lacking = [...chars].filter((c) => c !== " " && !covered.has(c));
if (lacking.length) console.log(`フォントにない文字（画像に使うとビルドが止まる）: ${lacking.join("")}`);
writeFileSync(join(out, "chars.txt"), usable.join(""));
console.log(`文字数: ${usable.length}`);
