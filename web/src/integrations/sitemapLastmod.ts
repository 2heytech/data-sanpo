import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import type { AstroIntegration } from "astro";

// サイトマップの更新日（lastmod）を、ページの中身が実際に変わった日時にする仕組み（設計変更記録 #242。#130 の「公開のビルドの日時」を変える）。
// ビルドの最後に、各ページの題名・説明文・本文（<main> の中の文字）からハッシュを作り、公開中のサイトに置いた前回の記録
// （/sitemap-lastmod.json）と比べる。同じなら前回の更新日を残し、中身が変わったページと新しいページだけをこのビルドの日時にする。
// ヘッダー・フッター・ナビ（<nav>。パンくず・目次・寄り道のテーマの札と本数・前後の記事）・スクリプト・タグ・空白だけの違いは、中身の変更に数えない。
// 公開中のサイトの記録が読めないとき（この仕組みの初回など）は、web/ に置いた最初の記録（INITIAL_FILE）と比べる。
// 最初の記録は、2026-11-14〜18 の公開を同じデータでビルドし直し、ページごとに最後に中身が変わった公開の日時を調べたもの。
// 寄り道の15本は 2026-11-18 に、本当に中身が変わった公開（11-11 の本文の見直し、11-13 の平均寿命の記事の追加）の日時へ直した（#245）。
// それもないときは、寄り道は記事の更新日（構造化データの dateModified）、ほかのページはデータの公開版を作った日時にする。
// 最初の記録を作り直したとき（#245）は、記録に新しい seed を付ける。公開中の記録の seed と違えば、1回だけ、
// 公開中の記録と中身（hash）が同じページに最初の記録の更新日を当てる（その後に中身が変わったページは公開中の記録のまま）。
// 記録は比べた記録の seed を引き継ぐので、次からは公開中の記録だけと比べる。

/** 前回の記録のファイル名（サイトの一番上に置く） */
export const RECORD_FILE = "sitemap-lastmod.json";

/** 最初の記録のファイル名（web/ に置き、公開はしない） */
export const INITIAL_FILE = "sitemap-lastmod-initial.json";

export interface PageRecord {
  hash: string;
  lastmod: string;
}

export interface LastmodRecord {
  version: 1;
  /** 最初の記録の版。最初の記録を作り直したら変える（#245） */
  seed?: string;
  pages: Record<string, PageRecord>;
}

const SCRIPT_STYLE = /<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi;
const NAV = /<nav\b[^>]*>[\s\S]*?<\/nav\s*>/gi;

/** 中身の比べ方に使う文字（題名・説明文・<main> の中の <nav> を除いた文字）。<main> がないページはページ全体 */
export function pageText(html: string): string {
  const title = /<title>([\s\S]*?)<\/title>/i.exec(html)?.[1] ?? "";
  const description = /<meta\s+name="description"\s+content="([^"]*)"/i.exec(html)?.[1] ?? "";
  const main = /<main\b[^>]*>([\s\S]*)<\/main>/i.exec(html)?.[1] ?? html;
  const text = main.replace(SCRIPT_STYLE, " ").replace(NAV, " ").replace(/<!--[\s\S]*?-->/g, " ").replace(/<[^>]+>/g, " ");
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
    if (r.seed !== undefined && typeof r.seed !== "string") return null;
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

/** サイトマップの索引（sitemap-index.xml）の各サイトマップの lastmod を差し替える。lastmodOf が null を返すものは今のまま */
export function rewriteSitemapIndex(xml: string, lastmodOf: (loc: string) => string | null): string {
  return xml.replace(
    /<sitemap><loc>([^<]+)<\/loc>(?:<lastmod>[^<]*<\/lastmod>)?/g,
    (m, loc: string) => {
      const lastmod = lastmodOf(unescapeXml(loc));
      return lastmod ? `<sitemap><loc>${loc}</loc><lastmod>${lastmod}</lastmod>` : m;
    },
  );
}

/** 索引の下のサイトマップのファイル（sitemap-0.xml、種類ごとに分けた sitemap-areas-0.xml など） */
export const isChildSitemap = (name: string) => /^sitemap-[a-z0-9-]+\.xml$/.test(name) && name !== "sitemap-index.xml";

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
  // サイトマップのファイルごとの、いちばん新しいページの更新日（索引に書く）
  const latestOf = new Map<string, string>();
  for (const name of readdirSync(root).filter(isChildSitemap).sort()) {
    const file = join(root, name);
    let latest = "";
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
    if (latest) latestOf.set(name, latest);
  }
  const index = join(root, "sitemap-index.xml");
  if (existsSync(index)) {
    const fileName = (loc: string) => new URL(loc).pathname.split("/").pop() ?? "";
    writeFileSync(index, rewriteSitemapIndex(readFileSync(index, "utf-8"), (loc) => latestOf.get(fileName(loc)) ?? null));
  }
  const record: LastmodRecord = { version: 1, ...(previous?.seed ? { seed: previous.seed } : {}), pages };
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

/**
 * 比べる記録を選ぶ。公開中のサイトの記録（source）が読めればそれ、読めなければ最初の記録（initialPath）、どちらもなければ null。
 * 最初の記録に seed があり、公開中の記録の seed と違うときは、公開中の記録に、中身が同じページだけ最初の記録の更新日を当てる（#245）
 */
export async function previousRecord(
  source: string | null,
  initialPath: string,
): Promise<{ record: LastmodRecord | null; from: string; warnings: string[] }> {
  const warnings: string[] = [];
  let live: LastmodRecord | null = null;
  if (source) {
    const loaded = await loadRecord(source);
    if (loaded.record) live = loaded.record;
    else warnings.push(`前回のサイトマップの更新日の記録を読めませんでした（${source}: ${loaded.error}）`);
  }
  let initial: LastmodRecord | null = null;
  if (existsSync(initialPath)) {
    const loaded = await loadRecord(initialPath);
    if (loaded.record) initial = loaded.record;
    else warnings.push(`${INITIAL_FILE} を読めませんでした（${loaded.error}）`);
  }
  if (live && initial?.seed && initial.seed !== live.seed) {
    const pages = { ...live.pages };
    for (const [path, page] of Object.entries(initial.pages)) {
      if (pages[path]?.hash === page.hash) pages[path] = page;
    }
    return { record: { version: 1, seed: initial.seed, pages }, from: `${source} に ${INITIAL_FILE} を当てたもの`, warnings };
  }
  if (live) return { record: live, from: source!, warnings };
  if (initial) return { record: initial, from: INITIAL_FILE, warnings };
  return { record: null, from: "", warnings };
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
        const { record: previous, from, warnings } = await previousRecord(recordSource(site, process.env), join(rootDir, INITIAL_FILE));
        for (const w of warnings) logger.warn(w);
        const { counts, missing } = applySitemapLastmod(root, previous, releaseDate, now);
        if (missing.length) logger.warn(`サイトマップにあるのに HTML が見つからないページがあります（ビルドの日時にしました）: ${missing.slice(0, 5).join(", ")}`);
        if (previous) {
          logger.info(`サイトマップの更新日（${from} と比べた）: 前と同じ ${counts.kept}・中身が変わった ${counts.changed}・新しいページ ${counts.added}`);
        } else {
          logger.info(
            `サイトマップの更新日: 前回の記録がないので、寄り道は記事の更新日、ほかはデータの公開版の日時（${releaseDate ?? now}）にしました（${counts.fallback} ページ）`,
          );
        }
      },
    },
  };
}
