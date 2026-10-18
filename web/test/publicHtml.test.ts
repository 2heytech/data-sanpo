import { describe, expect, it } from "vitest";
import { cssCommentAt, inlineComments, jsCommentAt, stripHtmlComments } from "../src/integrations/publicHtml";

describe("stripHtmlComments", () => {
  it("HTML のコメントを消す", () => {
    const r = stripHtmlComments(`<div><!-- メモ -->本文<!--\n2行目\n--></div>`);
    expect(r.html).toBe("<div>本文</div>");
    expect(r.removed).toHaveLength(2);
  });

  it("スクリプト・スタイル・pre の中は変えない", () => {
    const html = `<script>const s = "<!-- x -->";</script><style>a{content:"<!--"}</style><pre><!-- 例 --></pre>`;
    expect(stripHtmlComments(html)).toEqual({ html, removed: [] });
  });
});

describe("jsCommentAt", () => {
  it("// と /* を見つける", () => {
    expect(jsCommentAt("let a = 1; // メモ")).toBe(11);
    expect(jsCommentAt("/* メモ */ let a = 1;")).toBe(0);
    expect(jsCommentAt("let a = 1;\n<!-- x")).toBe(11);
  });

  it("文字列・テンプレート・正規表現の中は数えない", () => {
    expect(jsCommentAt(`location.replace("https://" + host); const t = '*/*';`)).toBe(-1);
    expect(jsCommentAt("const u = `https://${host}/${p}`;")).toBe(-1);
    expect(jsCommentAt("if (/\\/\\/|a*b/.test(s)) x = s.split(/[/*]/);")).toBe(-1);
    expect(jsCommentAt("return /a*b/g.test(s)")).toBe(-1);
  });

  it("割り算は正規表現と取り違えない", () => {
    expect(jsCommentAt("const r = a / b / c;")).toBe(-1);
    expect(jsCommentAt("const r = f(a) / 2; // メモ")).toBe(20);
  });

  it("テンプレートの式の中のコメントは見つける", () => {
    expect(jsCommentAt("const t = `${a /* メモ */}`;")).toBe(15);
  });
});

describe("cssCommentAt", () => {
  it("/* を見つけ、文字列の中は数えない", () => {
    expect(cssCommentAt("a{color:red}/* メモ */")).toBe(12);
    expect(cssCommentAt(`a::before{content:"/*"}`)).toBe(-1);
  });
});

describe("inlineComments", () => {
  it("ページに直接書かれたスクリプト・スタイルのコメントを抜き出す", () => {
    const html = `<script>(function(){ // 転送\n})();</script><style>a{}/* メモ */</style><script src="/a.js"></script>`;
    expect(inlineComments(html)).toEqual(["<script> // 転送 })();", "<style> /* メモ */"]);
  });

  it("構造化データ（JSON）は見ない", () => {
    expect(inlineComments(`<script type="application/ld+json">{"url":"https://example.com/"}</script>`)).toEqual([]);
  });
});
