import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";
import publicHtml from "./src/integrations/publicHtml.ts";

// 独自ドメイン（設計変更記録 #53）。canonical と sitemap に使う。Actions の変数 SITE_URL があればそちらを優先する
export default defineConfig({
  site: process.env.SITE_URL || "https://data-sanpo.com",
  trailingSlash: "always",
  // 移動先へ案内するだけのページ（noindex）はサイトマップに載せない。載せると Search Console が
  // 「送信したページに noindex がある」と数える
  // lastmod は公開（ビルド）の日。公開のたびにデータ・考察を作り直すので、Google が読み直すきっかけにする（設計変更記録 #130）
  // publicHtml はビルドの最後に、公開する HTML からコメントを消し、スクリプト・スタイルのコメントを見つけたら止める（設計変更記録 #147）
  integrations: [sitemap({ filter: (page) => !/\/(privacy|terms|indicators)\/$/.test(page), lastmod: new Date() }), publicHtml()],
  build: { format: "directory" },
});
