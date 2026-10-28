import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// ホーム画面に追加したときの設定とアイコン（設計変更記録 #171）
const PUBLIC = join(__dirname, "../public");

// PNG の幅と高さ（IHDR）
function pngSize(file: string): [number, number] {
  const b = readFileSync(join(PUBLIC, file));
  expect(b.subarray(1, 4).toString("latin1"), file).toBe("PNG");
  return [b.readUInt32BE(16), b.readUInt32BE(20)];
}

describe("ホーム画面に追加", () => {
  const manifest = JSON.parse(readFileSync(join(PUBLIC, "manifest.webmanifest"), "utf-8"));
  const base = readFileSync(join(__dirname, "../src/layouts/Base.astro"), "utf-8");

  it("名前と、トップから全画面で開く設定がある", () => {
    expect(manifest.name).toBe("データさんぽ");
    expect(manifest.short_name).toBe("データさんぽ");
    expect(manifest.start_url).toBe("/");
    expect(manifest.scope).toBe("/");
    expect(manifest.display).toBe("standalone");
  });

  it("アイコンのファイルがあり、大きさが書いたとおり", () => {
    const icons: { src: string; sizes: string; purpose: string }[] = manifest.icons;
    for (const icon of icons) {
      const [w, h] = pngSize(icon.src.replace(/^\//, ""));
      expect(`${w}x${h}`, icon.src).toBe(icon.sizes);
    }
    // Chrome でインストールできるには 192 と 512 が要る。Android のマスク用（maskable）も置く
    expect(icons.map((i) => i.sizes)).toEqual(expect.arrayContaining(["192x192", "512x512"]));
    expect(icons.some((i) => i.purpose === "maskable")).toBe(true);
    expect(pngSize("apple-touch-icon.png")).toEqual([180, 180]);
  });

  it("全ページの head から設定ファイルと iPhone 用アイコンを指す", () => {
    expect(base).toContain('<link rel="manifest" href="/manifest.webmanifest" />');
    expect(base).toContain('<link rel="apple-touch-icon" href="/apple-touch-icon.png" />');
    expect(base).toContain(`<meta name="theme-color" content="${manifest.theme_color}" />`);
  });
});
