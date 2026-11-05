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

// ホーム画面から開いたときの「戻る」（設計変更記録 #199）。head の is:inline のスクリプトを取り出し、
// 置き換えた navigator・matchMedia・Navigation API・referrer の組み合わせで、html に印が付くかを確かめる
describe("ホーム画面から開いたときの「戻る」", () => {
  const base = readFileSync(join(__dirname, "../src/layouts/Base.astro"), "utf-8");
  const css = readFileSync(join(__dirname, "../src/styles/global.css"), "utf-8");
  const inline = [...base.matchAll(/<script is:inline>([\s\S]*?)<\/script>/g)].map((m) => m[1]).find((s) => s.includes("app-back-on"));

  interface Env {
    standalone?: boolean;
    displayMode?: string;
    canGoBack?: boolean;
    referrer?: string;
  }
  function run(env: Env) {
    const classes = new Set<string>();
    const listeners: Record<string, () => void> = {};
    const navigation = env.canGoBack === undefined ? undefined : {
      canGoBack: env.canGoBack,
      addEventListener: (type: string, fn: () => void) => { listeners[`navigation:${type}`] = fn; },
    };
    const document = {
      documentElement: { classList: { toggle: (c: string, on: boolean) => (on ? classes.add(c) : classes.delete(c)) } },
      referrer: env.referrer ?? "",
    };
    const navigator = { standalone: env.standalone };
    const matchMedia = (q: string) => ({ matches: env.displayMode !== undefined && q === `(display-mode: ${env.displayMode})` });
    const addEventListener = (type: string, fn: () => void) => { listeners[type] = fn; };
    new Function("document", "navigator", "matchMedia", "window", "location", "addEventListener", inline!)(
      document, navigator, matchMedia, { navigation }, { origin: "https://data-sanpo.com" }, addEventListener,
    );
    return { on: () => classes.has("app-back-on"), navigation, listeners };
  }

  it("ヘッダーにボタンがあり、印がないときは出さない", () => {
    expect(inline).toBeDefined();
    expect(base).toContain('id="app-back"');
    expect(base).toContain('getElementById("app-back")?.addEventListener("click", () => history.back())');
    expect(css).toContain(".app-back { display: none; }");
    expect(css).toContain(".app-back-on .app-back {");
  });

  it("ブラウザで開いたときは出さない（前のページがあっても）", () => {
    expect(run({ canGoBack: true }).on()).toBe(false);
    expect(run({ referrer: "https://data-sanpo.com/areas/" }).on()).toBe(false);
  });

  it("ホーム画面から開き、前のページがあるときだけ出す（Navigation API）", () => {
    expect(run({ displayMode: "standalone", canGoBack: true }).on()).toBe(true);
    expect(run({ displayMode: "standalone", canGoBack: false }).on()).toBe(false);
    expect(run({ displayMode: "fullscreen", canGoBack: true }).on()).toBe(true);
  });

  it("同じページの中で移った（目次など）あとも、出す・出さないを直す", () => {
    const r = run({ displayMode: "standalone", canGoBack: false });
    r.navigation!.canGoBack = true;
    r.listeners["navigation:currententrychange"]();
    expect(r.on()).toBe(true);
    r.navigation!.canGoBack = false;
    r.listeners["pageshow"]();
    expect(r.on()).toBe(false);
  });

  it("Navigation API がない iPhone では、このサイトから来たときだけ出す", () => {
    expect(run({ standalone: true, referrer: "https://data-sanpo.com/areas/" }).on()).toBe(true);
    expect(run({ standalone: true, referrer: "" }).on()).toBe(false);
    expect(run({ standalone: true, referrer: "https://www.google.com/" }).on()).toBe(false);
    expect(run({ standalone: true, referrer: "not a url" }).on()).toBe(false);
  });
});
