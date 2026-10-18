import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import type { AstroIntegration } from "astro";

// 公開する HTML に開発用のコメントを残さない仕組み（設計変更記録 #143・#147）。
// ビルドの最後に dist の全ページを読み、<!-- --> を消す。ページに直接書かれたスクリプト・スタイルの
// コメントは、文字列や正規表現と見分けて安全に消すのが難しいので、見つけたらビルドを止めてソースの方を直す。

// 中身をそのまま残す要素。この中の <!-- は HTML のコメントではない
const RAW_OR_COMMENT = /(<(script|style|textarea|pre)\b[^>]*>[\s\S]*?<\/\2\s*>)|<!--[\s\S]*?-->/gi;

/** HTML のコメント（<!-- -->）を消す。消したものも返す */
export function stripHtmlComments(html: string): { html: string; removed: string[] } {
  const removed: string[] = [];
  const out = html.replace(RAW_OR_COMMENT, (m: string, raw?: string) => {
    if (raw) return raw;
    removed.push(m);
    return "";
  });
  return { html: out, removed };
}

// この語の直後の / は割り算ではなく正規表現の始まり
const REGEX_AFTER = new Set(["return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do", "else", "yield", "await"]);

function regexAllowed(prev: string): boolean {
  if (prev === "") return true;
  if (/^[\w$]+$/.test(prev)) return REGEX_AFTER.has(prev);
  return ![")", "]", "}", "str", "re"].includes(prev);
}

/** JavaScript のコメント（// と /* と <!--）の位置。なければ -1。文字列・テンプレート・正規表現の中は数えない */
export function jsCommentAt(code: string): number {
  const n = code.length;
  let i = 0;
  let depth = 0;
  let prev = "";
  const templates: number[] = [];
  const scanTemplate = () => {
    while (i < n) {
      const c = code[i];
      if (c === "\\") { i += 2; continue; }
      if (c === "`") { i++; prev = "str"; return; }
      if (c === "$" && code[i + 1] === "{") { i += 2; templates.push(depth++); prev = "{"; return; }
      i++;
    }
  };
  while (i < n) {
    const c = code[i];
    if (c === "/" && (code[i + 1] === "/" || code[i + 1] === "*")) return i;
    if (c === "<" && code.startsWith("<!--", i)) return i;
    if (/\s/.test(c)) { i++; continue; }
    if (c === '"' || c === "'") {
      i++;
      while (i < n && code[i] !== c) i += code[i] === "\\" ? 2 : 1;
      i++;
      prev = "str";
      continue;
    }
    if (c === "`") { i++; scanTemplate(); continue; }
    if (c === "{") { depth++; prev = "{"; i++; continue; }
    if (c === "}") {
      depth--;
      i++;
      if (templates.length && templates[templates.length - 1] === depth) { templates.pop(); scanTemplate(); }
      else prev = "}";
      continue;
    }
    if (c === "/") {
      i++;
      if (!regexAllowed(prev)) { prev = "/"; continue; }
      let inClass = false;
      while (i < n && code[i] !== "\n") {
        const d = code[i];
        if (d === "\\") { i += 2; continue; }
        if (inClass) { if (d === "]") inClass = false; }
        else if (d === "[") inClass = true;
        else if (d === "/") break;
        i++;
      }
      i++;
      while (i < n && /[a-z]/i.test(code[i])) i++;
      prev = "re";
      continue;
    }
    if (/[\w$]/.test(c)) {
      const start = i;
      while (i < n && /[\w$]/.test(code[i])) i++;
      prev = code.slice(start, i);
      continue;
    }
    prev = c;
    i++;
  }
  return -1;
}

/** CSS のコメント（/* *\/）の位置。なければ -1 */
export function cssCommentAt(css: string): number {
  for (let i = 0; i < css.length; i++) {
    const c = css[i];
    if (c === '"' || c === "'") {
      i++;
      while (i < css.length && css[i] !== c) i += css[i] === "\\" ? 2 : 1;
      continue;
    }
    if (c === "/" && css[i + 1] === "*") return i;
  }
  return -1;
}

/** ページに直接書かれたスクリプト・スタイルの中のコメント（見つかったところの抜き出し） */
export function inlineComments(html: string): string[] {
  const found: string[] = [];
  for (const m of html.matchAll(/<(script|style)\b([^>]*)>([\s\S]*?)<\/\1\s*>/gi)) {
    const [, tag, attrs, body] = m;
    if (!body.trim()) continue;
    if (/\btype\s*=\s*["']?application\/(ld\+)?json/i.test(attrs)) continue;
    const at = tag.toLowerCase() === "style" ? cssCommentAt(body) : jsCommentAt(body);
    if (at >= 0) found.push(`<${tag}> ${body.slice(at, at + 60).replace(/\s+/g, " ")}`);
  }
  return found;
}

function htmlFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name);
    if (e.isDirectory()) return htmlFiles(p);
    return e.name.endsWith(".html") ? [p] : [];
  });
}

export default function publicHtml(): AstroIntegration {
  return {
    name: "public-html",
    hooks: {
      "astro:build:done": ({ dir, logger }) => {
        const root = fileURLToPath(dir);
        const files = htmlFiles(root);
        const removed: string[] = [];
        const problems: string[] = [];
        for (const f of files) {
          const page = stripHtmlComments(readFileSync(f, "utf-8"));
          if (page.removed.length) {
            writeFileSync(f, page.html);
            removed.push(...page.removed.map((c) => `${relative(root, f)}: ${c.slice(0, 60)}`));
          }
          problems.push(...inlineComments(page.html).map((c) => `${relative(root, f)}: ${c}`));
        }
        if (removed.length) {
          logger.warn(`HTML のコメントを ${removed.length} か所消しました。.astro では {/* */} を使ってください。\n${removed.slice(0, 5).join("\n")}`);
        }
        if (problems.length) {
          throw new Error(`ページに直接書かれたスクリプト・スタイルにコメントがあります。ソースから消してください（${problems.length} か所）。\n${problems.slice(0, 10).join("\n")}`);
        }
        logger.info(`${files.length} ページにコメントがないことを確かめました`);
      },
    },
  };
}
