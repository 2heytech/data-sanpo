import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";
import publicHtml from "./src/integrations/publicHtml.ts";
import sitemapLastmod from "./src/integrations/sitemapLastmod.ts";

// 独自ドメイン（設計変更記録 #53）。canonical と sitemap に使う。Actions の変数 SITE_URL があればそちらを優先する
export default defineConfig({
  site: process.env.SITE_URL || "https://data-sanpo.com",
  trailingSlash: "always",
  // 移動先へ案内するだけのページ（noindex）はサイトマップに載せない。載せると Search Console が
  // 「送信したページに noindex がある」と数える
  // lastmod は sitemapLastmod が入れる。ページの中身（題名・説明文・本文）が前回の公開から変わったときだけ、そのビルドの日時にする（設計変更記録 #242。#130 を変える）
  // publicHtml はビルドの最後に、公開する HTML からコメントを消し、スクリプト・スタイルのコメントを見つけたら止める（設計変更記録 #147）
  integrations: [sitemap({ filter: (page) => !/\/(privacy|terms|indicators)\/$/.test(page) }), sitemapLastmod(), publicHtml()],
  build: { format: "directory" },
});
