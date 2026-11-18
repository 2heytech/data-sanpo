import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  applySitemapLastmod,
  contentHash,
  decideLastmod,
  fallbackLastmod,
  loadRecord,
  pageText,
  parseRecord,
  previousRecord,
  RECORD_FILE,
  recordSource,
  rewriteSitemap,
  type LastmodRecord,
} from "../src/integrations/sitemapLastmod";

const page = (body: string, opts: { title?: string; description?: string; header?: string; extra?: string } = {}) =>
  `<!DOCTYPE html><html><head><title>${opts.title ?? "題名"}</title>` +
  `<meta name="description" content="${opts.description ?? "説明"}">${opts.extra ?? ""}</head>` +
  `<body><header>${opts.header ?? "ヘッダー"}</header><main id="main">${body}</main><footer>運営: へいてく</footer></body></html>`;

describe("pageText と contentHash", () => {
  it("題名・説明文・本文を比べ、ヘッダー・フッター・タグ・スクリプト・空白の違いは数えない", () => {
    const base = page("<h1>新宿区</h1><p>人口 35万人</p>");
    expect(pageText(base)).toBe("題名\n説明\n新宿区 人口 35万人");
    expect(contentHash(page(`<h1 class="x">新宿区</h1>\n  <p>人口 <b>35万人</b></p><script>let a = 1;</script>`))).toBe(contentHash(base));
    expect(contentHash(page("<h1>新宿区</h1><p>人口 35万人</p>", { header: "別のメニュー" }))).toBe(contentHash(base));
    expect(contentHash(page("<h1>新宿区</h1><!-- メモ --><p>人口 35万人</p>"))).toBe(contentHash(base));
    // パンくず・テーマの札の本数・前後の記事などのナビ（<nav>）の違いも数えない
    const withNav = (n: number) => page(`<nav aria-label="現在地">トップ</nav><h1>新宿区</h1><p>人口 35万人</p><nav class="theme-nav">すべての寄り道（${n}本）</nav>`);
    expect(contentHash(withNav(28))).toBe(contentHash(base));
    expect(contentHash(withNav(29))).toBe(contentHash(base));
  });

  it("本文・題名・説明文が変われば変わる", () => {
    const base = contentHash(page("<p>人口 35万人</p>"));
    expect(contentHash(page("<p>人口 36万人</p>"))).not.toBe(base);
    expect(contentHash(page("<p>人口 35万人</p>", { title: "新しい題名" }))).not.toBe(base);
    expect(contentHash(page("<p>人口 35万人</p>", { description: "新しい説明" }))).not.toBe(base);
  });
});

describe("decideLastmod", () => {
  const now = "2026-11-20T21:30:00.000Z";
  const html = page("<p>本文</p>");
  const previous: LastmodRecord = {
    version: 1,
    pages: {
      "/same/": { hash: contentHash(html), lastmod: "2026-11-14T02:00:00.000Z" },
      "/edited/": { hash: "0000000000000000", lastmod: "2026-11-14T02:00:00.000Z" },
    },
  };

  it("中身が前と同じなら前回の更新日を残す", () => {
    expect(decideLastmod("/same/", html, previous, null, now)).toEqual({
      record: { hash: contentHash(html), lastmod: "2026-11-14T02:00:00.000Z" },
      change: "kept",
    });
  });

  it("中身が変わったページと新しいページはビルドの日時にする", () => {
    expect(decideLastmod("/edited/", html, previous, null, now).record.lastmod).toBe(now);
    expect(decideLastmod("/edited/", html, previous, null, now).change).toBe("changed");
    expect(decideLastmod("/new/", html, previous, null, now)).toMatchObject({ record: { lastmod: now }, change: "added" });
  });

  it("前回の記録がないときは、記事の更新日、データの公開版の日時、ビルドの日時の順に使う", () => {
    const article = page("<p>本文</p>", {
      extra: `<script type="application/ld+json">{"@type":"Article","datePublished":"2026-10-20","dateModified":"2026-11-11"}</script>`,
    });
    expect(decideLastmod("/articles/a/", article, null, "2026-11-13T16:01:00+00:00", now)).toMatchObject({
      record: { lastmod: "2026-11-11T00:00:00+09:00" },
      change: "fallback",
    });
    expect(fallbackLastmod(html, "2026-11-13T16:01:00+00:00", now)).toBe("2026-11-13T16:01:00+00:00");
    expect(fallbackLastmod(html, null, now)).toBe(now);
  });
});

describe("parseRecord と recordSource", () => {
  it("形の合う記録だけ読む", () => {
    expect(parseRecord('{"version":1,"pages":{"/":{"hash":"ab","lastmod":"2026-11-14"}}}')).toEqual({
      version: 1,
      pages: { "/": { hash: "ab", lastmod: "2026-11-14" } },
    });
    expect(parseRecord("<html>Not Found</html>")).toBeNull();
    expect(parseRecord('{"version":2,"pages":{}}')).toBeNull();
    expect(parseRecord('{"version":1,"pages":{"/":{"hash":1}}}')).toBeNull();
  });

  it("公開のビルドだけ公開中のサイトの記録を読む", () => {
    expect(recordSource("https://data-sanpo.com", { ALLOW_INDEXING: "true" })).toBe("https://data-sanpo.com/sitemap-lastmod.json");
    expect(recordSource("https://data-sanpo.com/", { ALLOW_INDEXING: "true" })).toBe("https://data-sanpo.com/sitemap-lastmod.json");
    expect(recordSource("https://data-sanpo.com", {})).toBeNull();
    expect(recordSource("https://data-sanpo.com", { SITEMAP_LASTMOD_PREVIOUS: "/tmp/prev.json" })).toBe("/tmp/prev.json");
  });
});

describe("previousRecord", () => {
  const dirs: string[] = [];
  afterEach(() => {
    for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true });
  });
  const write = (dir: string, name: string, lastmod: string) => {
    const p = join(dir, name);
    writeFileSync(p, JSON.stringify({ version: 1, pages: { "/": { hash: "ab", lastmod } } }));
    return p;
  };

  it("公開中のサイトの記録が読めればそれを使い、読めなければ最初の記録を使う", async () => {
    const dir = mkdtempSync(join(tmpdir(), "sitemap-prev-"));
    dirs.push(dir);
    const initial = write(dir, "initial.json", "2026-11-14T00:00:00Z");
    const live = write(dir, "live.json", "2026-11-20T00:00:00Z");
    expect(await previousRecord(live, initial)).toMatchObject({ from: live, warnings: [], record: { pages: { "/": { lastmod: "2026-11-20T00:00:00Z" } } } });
    const r = await previousRecord(join(dir, "none.json"), initial);
    expect(r.record?.pages["/"].lastmod).toBe("2026-11-14T00:00:00Z");
    expect(r.warnings).toHaveLength(1);
    expect(await previousRecord(null, join(dir, "none.json"))).toEqual({ record: null, from: "", warnings: [] });
  });
});

describe("rewriteSitemap", () => {
  it("lastmod を差し替え、なければ足す", () => {
    const xml =
      `<urlset><url><loc>https://data-sanpo.com/</loc><lastmod>2026-11-15T21:29:57.438Z</lastmod></url>` +
      `<url><loc>https://data-sanpo.com/about/</loc></url></urlset>`;
    const out = rewriteSitemap(xml, (loc) => (loc.endsWith("/about/") ? "2026-10-01" : "2026-11-14"));
    expect(out).toBe(
      `<urlset><url><loc>https://data-sanpo.com/</loc><lastmod>2026-11-14</lastmod></url>` +
        `<url><loc>https://data-sanpo.com/about/</loc><lastmod>2026-10-01</lastmod></url></urlset>`,
    );
  });
});

describe("applySitemapLastmod", () => {
  const dirs: string[] = [];
  afterEach(() => {
    for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true });
  });

  function site(pages: Record<string, string>): string {
    const root = mkdtempSync(join(tmpdir(), "sitemap-lastmod-"));
    dirs.push(root);
    const urls = Object.keys(pages)
      .map((p) => `<url><loc>https://data-sanpo.com${p}</loc></url>`)
      .join("");
    writeFileSync(join(root, "sitemap-0.xml"), `<?xml version="1.0" encoding="UTF-8"?><urlset>${urls}</urlset>`);
    writeFileSync(
      join(root, "sitemap-index.xml"),
      `<sitemapindex><sitemap><loc>https://data-sanpo.com/sitemap-0.xml</loc><lastmod>2026-11-20T00:00:00.000Z</lastmod></sitemap></sitemapindex>`,
    );
    for (const [p, html] of Object.entries(pages)) {
      mkdirSync(join(root, p), { recursive: true });
      writeFileSync(join(root, p, "index.html"), html);
    }
    return root;
  }

  it("2回目のビルドでは、変わったページと新しいページだけ更新日が新しくなる", async () => {
    const first = site({ "/": page("<p>トップ</p>"), "/areas/muni-13104/": page("<p>新宿区 35万人</p>") });
    const r1 = applySitemapLastmod(first, null, "2026-11-13T16:01:00+00:00", "2026-11-18T21:30:00.000Z");
    expect(r1.counts).toEqual({ kept: 0, changed: 0, added: 0, fallback: 2 });
    expect(readFileSync(join(first, "sitemap-0.xml"), "utf-8")).toContain(
      "<loc>https://data-sanpo.com/areas/muni-13104/</loc><lastmod>2026-11-13T16:01:00+00:00</lastmod>",
    );

    // 公開中のサイトに置いた記録を、次のビルドで読む
    const { record: previous } = await loadRecord(join(first, RECORD_FILE));
    expect(previous).not.toBeNull();

    const second = site({
      "/": page("<p>トップ</p>"),
      "/areas/muni-13104/": page("<p>新宿区 36万人</p>"),
      "/articles/new/": page("<p>新しい記事</p>"),
    });
    const now = "2026-11-20T21:30:00.000Z";
    const r2 = applySitemapLastmod(second, previous, "2026-11-13T16:01:00+00:00", now);
    expect(r2.counts).toEqual({ kept: 1, changed: 1, added: 1, fallback: 0 });
    const xml = readFileSync(join(second, "sitemap-0.xml"), "utf-8");
    expect(xml).toContain("<loc>https://data-sanpo.com/</loc><lastmod>2026-11-13T16:01:00+00:00</lastmod>");
    expect(xml).toContain(`<loc>https://data-sanpo.com/areas/muni-13104/</loc><lastmod>${now}</lastmod>`);
    expect(xml).toContain(`<loc>https://data-sanpo.com/articles/new/</loc><lastmod>${now}</lastmod>`);
    // 索引の更新日は、そのサイトマップのいちばん新しいページの更新日
    expect(readFileSync(join(second, "sitemap-index.xml"), "utf-8")).toContain(
      `<loc>https://data-sanpo.com/sitemap-0.xml</loc><lastmod>${now}</lastmod>`,
    );
  });

  it("種類ごとに分けたサイトマップも書き換え、索引にはファイルごとのいちばん新しい更新日を書く", () => {
    const root = site({ "/": page("<p>トップ</p>"), "/areas/muni-13104/": page("<p>新宿区</p>") });
    rmSync(join(root, "sitemap-0.xml"));
    writeFileSync(join(root, "sitemap-pages-0.xml"), `<urlset><url><loc>https://data-sanpo.com/</loc></url></urlset>`);
    writeFileSync(join(root, "sitemap-areas-0.xml"), `<urlset><url><loc>https://data-sanpo.com/areas/muni-13104/</loc></url></urlset>`);
    writeFileSync(
      join(root, "sitemap-index.xml"),
      `<sitemapindex><sitemap><loc>https://data-sanpo.com/sitemap-areas-0.xml</loc></sitemap>` +
        `<sitemap><loc>https://data-sanpo.com/sitemap-pages-0.xml</loc></sitemap></sitemapindex>`,
    );
    const previous: LastmodRecord = {
      version: 1,
      pages: {
        "/": { hash: contentHash(page("<p>トップ</p>")), lastmod: "2026-11-14T00:00:00Z" },
        "/areas/muni-13104/": { hash: contentHash(page("<p>新宿区</p>")), lastmod: "2026-11-16T00:00:00Z" },
      },
    };
    const r = applySitemapLastmod(root, previous, null, "2026-11-20T21:30:00.000Z");
    expect(r.counts.kept).toBe(2);
    expect(readFileSync(join(root, "sitemap-areas-0.xml"), "utf-8")).toContain("<lastmod>2026-11-16T00:00:00Z</lastmod>");
    expect(readFileSync(join(root, "sitemap-index.xml"), "utf-8")).toBe(
      `<sitemapindex><sitemap><loc>https://data-sanpo.com/sitemap-areas-0.xml</loc><lastmod>2026-11-16T00:00:00Z</lastmod></sitemap>` +
        `<sitemap><loc>https://data-sanpo.com/sitemap-pages-0.xml</loc><lastmod>2026-11-14T00:00:00Z</lastmod></sitemap></sitemapindex>`,
    );
  });

  it("HTML がないページはビルドの日時にして知らせる", () => {
    const root = site({ "/": page("<p>トップ</p>") });
    writeFileSync(
      join(root, "sitemap-0.xml"),
      `<urlset><url><loc>https://data-sanpo.com/</loc></url><url><loc>https://data-sanpo.com/gone/</loc></url></urlset>`,
    );
    const r = applySitemapLastmod(root, { version: 1, pages: {} }, null, "2026-11-20T21:30:00.000Z");
    expect(r.missing).toEqual(["/gone/"]);
    expect(readFileSync(join(root, "sitemap-0.xml"), "utf-8")).toContain(
      "<loc>https://data-sanpo.com/gone/</loc><lastmod>2026-11-20T21:30:00.000Z</lastmod>",
    );
  });
});
