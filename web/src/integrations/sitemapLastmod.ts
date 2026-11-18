import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import type { AstroIntegration } from "astro";

// サイトマップの更新日（lastmod）を、ページの中身が実際に変わった日時にする仕組み（設計変更記録 #242。#130 の「公開のビルドの日時」を変える）。
// ビルドの最後に、各ページの題名・説明文・本文（<main> の中の文字）からハッシュを作り、公開中のサイトに置いた前回の記録
// （/sitemap-lastmod.json）と比べる。同じなら前回の更新日を残し、中身が変わったページと新しいページだけをこのビルドの日時にする。
// ヘッダー・フッター・スクリプト・タグ・空白だけの違いは、中身の変更に数えない。
// 前回の記録が読めないとき（この仕組みの初回など）は、寄り道は記事の更新日（構造化データの dateModified）、
// ほかのページはデータの公開版を作った日時にする（どちらもないときはビルドの日時）。

/** 前回の記録のファイル名（サイトの一番上に置く） */
export const RECORD_FILE = "sitemap-lastmod.json";

export interface PageRecord {
  hash: string;
  lastmod: string;
}

export interface LastmodRecord {
  version: 1;
  pages: Record<string, PageRecord>;
}

const SCRIPT_STYLE = /<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi;

/** 中身の比べ方に使う文字（題名・説明文・<main> の中の文字）。<main> がないページはページ全体 */
export function pageText(html: string): string {
  const title = /<title>([\s\S]*?)<\/title>/i.exec(html)?.[1] ?? "";
  const description = /<meta\s+name="description"\s+content="([^"]*)"/i.exec(html)?.[1] ?? "";
  const main = /<main\b[^>]*>([\s\S]*)<\/main>/i.exec(html)?.[1] ?? html;
  const text = main.replace(SCRIPT_STYLE, " ").replace(/<!--[\s\S]*?-->/g, " ").replace(/<[^>]+>/g, " ");
  return [title, description, text].map((s) => s.replace(/\s+/g, " ").trim()).join("\n");
}

/** ページの中身のハッシュ（16桁） */
export function contentHash(html: string): string {
  return createHash("sha256").update(pageText(html)).digest("hex").slice(0, 16);
}

/**
 * 前回の記録がないときの更新日。寄り道は記事の更新日、ほかはデータの公開版を作った日時、どちらもなければビルドの日時。
 * 記事の更新日は日本の日付（YYYY-MM-DD）なので、その日の 0 時（日本時間）にする
 */
export function fallbackLastmod(html: string, releaseDate: string | null, now: string): string {
  const modified = /"dateModified"\s*:\s*"(\d{4}-\d{2}-\d{2}[^"]*)"/.exec(html)?.[1];
  if (modified) return /^\d{4}-\d{2}-\d{2}$/.test(modified) ? `${modified}T00:00:00+09:00` : modified;
  return releaseDate ?? now;
}

export type PageChange = "kept" | "changed" | "added" | "fallback";

/** 1ページの更新日と、前回と比べてどうだったか */
export function decideLastmod(
  path: string,
  html: string,
  previous: LastmodRecord | null,
  releaseDate: string | null,
  now: string,
): { record: PageRecord; change: PageChange } {
  const hash = contentHash(html);
  if (!previous) return { record: { hash, lastmod: fallbackLastmod(html, releaseDate, now) }, change: "fallback" };
  const before = previous.pages[path];
  if (!before) return { record: { hash, lastmod: now }, change: "added" };
  if (before.hash === hash) return { record: { hash, lastmod: before.lastmod }, change: "kept" };
  return { record: { hash, lastmod: now }, change: "changed" };
}

/** 前回の記録として読めるか確かめる。読めなければ null */
export function parseRecord(text: string): LastmodRecord | null {
  try {
    const r = JSON.parse(text);
    if (!r || r.version !== 1 || !r.pages || typeof r.pages !== "object") return null;
    const ok = Object.values(r.pages).every(
      (p) => !!p && typeof (p as PageRecord).hash === "string" && typeof (p as PageRecord).lastmod === "string",
    );
    return ok ? (r as LastmodRecord) : null;
  } catch {
    return null;
  }
}

const unescapeXml = (s: string) =>
  s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, "&");

/** サイトマップの各 URL の lastmod を差し替える（なければ <loc> のあとに足す） */
export function rewriteSitemap(xml: string, lastmodOf: (loc: string) => string): string {
  return xml.replace(
    /<url><loc>([^<]+)<\/loc>(?:<lastmod>[^<]*<\/lastmod>)?/g,
    (_m, loc: string) => `<url><loc>${loc}</loc><lastmod>${lastmodOf(unescapeXml(loc))}</lastmod>`,
  );
}

/** サイトマップの索引（sitemap-index.xml）の lastmod を差し替える */
export function rewriteSitemapIndex(xml: string, lastmod: string): string {
  return xml.replace(
    /<sitemap><loc>([^<]+)<\/loc>(?:<lastmod>[^<]*<\/lastmod>)?/g,
    (_m, loc: string) => `<sitemap><loc>${loc}</loc><lastmod>${lastmod}</lastmod>`,
  );
}

/** URL のページの HTML のファイル（build.format = "directory"） */
export function htmlFileFor(root: string, loc: string): string | null {
  const path = decodeURIComponent(new URL(loc).pathname);
  const candidates = path.endsWith("/") ? [join(root, path, "index.html")] : [join(root, path), join(root, path, "index.html")];
  return candidates.find((p) => existsSync(p)) ?? null;
}

const time = (s: string) => {
  const t = Date.parse(s);
  return Number.isNaN(t) ? 0 : t;
};

export interface ApplyResult {
  counts: Record<PageChange, number>;
  /** サイトマップにあるのに HTML が見つからなかったページ（ビルドの日時にした） */
  missing: string[];
  record: LastmodRecord;
}

/** ビルドしたサイト（root）のサイトマップの lastmod を書き換え、次のビルドのための記録を root に置く */
export function applySitemapLastmod(
  root: string,
  previous: LastmodRecord | null,
  releaseDate: string | null,
  now: string,
): ApplyResult {
  const counts: Record<PageChange, number> = { kept: 0, changed: 0, added: 0, fallback: 0 };
  const missing: string[] = [];
  const pages: Record<string, PageRecord> = {};
  let latest = "";
  for (const name of readdirSync(root).filter((f) => /^sitemap-\d+\.xml$/.test(f))) {
    const file = join(root, name);
    const xml = rewriteSitemap(readFileSync(file, "utf-8"), (loc) => {
      const path = new URL(loc).pathname;
      const html = htmlFileFor(root, loc);
      if (!html) {
        missing.push(path);
        return now;
      }
      const { record, change } = decideLastmod(path, readFileSync(html, "utf-8"), previous, releaseDate, now);
      pages[path] = record;
      counts[change]++;
      if (time(record.lastmod) > time(latest)) latest = record.lastmod;
      return record.lastmod;
    });
    writeFileSync(file, xml);
  }
  const index = join(root, "sitemap-index.xml");
  if (existsSync(index) && latest) writeFileSync(index, rewriteSitemapIndex(readFileSync(index, "utf-8"), latest));
  const record: LastmodRecord = { version: 1, pages };
  writeFileSync(join(root, RECORD_FILE), JSON.stringify(record) + "\n");
  return { counts, missing, record };
}

/** 前回の記録を読む。URL ならダウンロードし、それ以外はファイルとして読む。読めなければ null と理由 */
export async function loadRecord(source: string): Promise<{ record: LastmodRecord | null; error?: string }> {
  try {
    let text: string;
    if (/^https?:\/\//.test(source)) {
      const res = await fetch(source, { signal: AbortSignal.timeout(20_000) });
      if (!res.ok) return { record: null, error: `HTTP ${res.status}` };
      text = await res.text();
    } else {
      text = readFileSync(source, "utf-8");
    }
    const record = parseRecord(text);
    return record ? { record } : { record: null, error: "形式が違います" };
  } catch (e) {
    return { record: null, error: e instanceof Error ? e.message : String(e) };
  }
}

/**
 * 前回の記録の場所。SITEMAP_LASTMOD_PREVIOUS（URL かファイル）があればそれ、
 * 検索エンジンに載せる公開のビルド（ALLOW_INDEXING=true）なら公開中のサイトの記録、ほかは読まない
 */
export function recordSource(site: string | undefined, env: Record<string, string | undefined>): string | null {
  if (env.SITEMAP_LASTMOD_PREVIOUS) return env.SITEMAP_LASTMOD_PREVIOUS;
  if (env.ALLOW_INDEXING !== "true" || !site) return null;
  return new URL(RECORD_FILE, site.endsWith("/") ? site : `${site}/`).href;
}

export default function sitemapLastmod(): AstroIntegration {
  let site: string | undefined;
  let rootDir = "";
  return {
    name: "sitemap-lastmod",
    hooks: {
      "astro:config:done": ({ config }) => {
        site = config.site;
        rootDir = fileURLToPath(config.root);
      },
      "astro:build:done": async ({ dir, logger }) => {
        const root = fileURLToPath(dir);
        const now = new Date().toISOString();
        const releaseFile = join(rootDir, "src/generated/release.json");
        const releaseDate: string | null = existsSync(releaseFile)
          ? (JSON.parse(readFileSync(releaseFile, "utf-8")).created_at ?? null)
          : null;
        const source = recordSource(site, process.env);
        let previous: LastmodRecord | null = null;
        if (source) {
          const loaded = await loadRecord(source);
          previous = loaded.record;
          if (!previous) logger.warn(`前回のサイトマップの更新日の記録を読めませんでした（${source}: ${loaded.error}）`);
        }
        const { counts, missing } = applySitemapLastmod(root, previous, releaseDate, now);
        if (missing.length) logger.warn(`サイトマップにあるのに HTML が見つからないページがあります（ビルドの日時にしました）: ${missing.slice(0, 5).join(", ")}`);
        if (previous) {
          logger.info(`サイトマップの更新日: 前と同じ ${counts.kept}・中身が変わった ${counts.changed}・新しいページ ${counts.added}`);
        } else {
          logger.info(
            `サイトマップの更新日: 前回の記録がないので、寄り道は記事の更新日、ほかはデータの公開版の日時（${releaseDate ?? now}）にしました（${counts.fallback} ページ）`,
          );
        }
      },
    },
  };
}
