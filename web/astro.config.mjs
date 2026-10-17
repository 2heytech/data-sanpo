import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

// 独自ドメイン（設計変更記録 #53）。canonical と sitemap に使う。Actions の変数 SITE_URL があればそちらを優先する
export default defineConfig({
  site: process.env.SITE_URL || "https://data-sanpo.com",
  trailingSlash: "always",
  // 移動先へ案内するだけのページ（noindex）はサイトマップに載せない。載せると Search Console が
  // 「送信したページに noindex がある」と数える
  // lastmod は公開（ビルド）の日。公開のたびにデータ・考察を作り直すので、Google が読み直すきっかけにする（設計変更記録 #130）
  integrations: [sitemap({ filter: (page) => !/\/(privacy|terms|indicators)\/$/.test(page), lastmod: new Date() })],
  build: { format: "directory" },
});
