import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// 公開する HTML に開発用のメモを残さない（設計変更記録 #143）。
// .astro の <!-- --> と is:inline のスクリプトの中のコメントは、そのままページに出る。
// メモは {/* */}（ビルドで消える）か、フロントマターに書く
const SRC = join(__dirname, "../src");

function astroFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name);
    if (e.isDirectory()) return astroFiles(p);
    return e.name.endsWith(".astro") ? [p] : [];
  });
}

describe("ページに出るソース", () => {
  const files = astroFiles(SRC);

  it(".astro を見つけられる", () => {
    expect(files.length).toBeGreaterThan(10);
  });

  it("HTML のコメント（<!-- -->）を使わない", () => {
    for (const f of files) {
      expect(readFileSync(f, "utf-8"), f).not.toContain("<!--");
    }
  });

  it("is:inline のスクリプトにコメントを書かない", () => {
    for (const f of files) {
      for (const m of readFileSync(f, "utf-8").matchAll(/<script\b[^>]*\bis:inline\b[^>]*>([\s\S]*?)<\/script>/g)) {
        expect(m[1], f).not.toMatch(/(^|\s)\/\/|\/\*/);
      }
    }
  });

  it("運営者のアカウント名を載せない", () => {
    for (const f of files) {
      expect(readFileSync(f, "utf-8"), f).not.toContain("2heytech");
    }
  });
});
