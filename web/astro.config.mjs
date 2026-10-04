import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

// 独自ドメイン（設計変更記録 #53）。canonical と sitemap に使う。Actions の変数 SITE_URL があればそちらを優先する
export default defineConfig({
  site: process.env.SITE_URL || "https://data-sanpo.com",
  trailingSlash: "always",
  // /privacy/ は利用規約への案内だけのページなのでサイトマップに載せない
  integrations: [sitemap({ filter: (page) => !page.endsWith("/privacy/") })],
  build: { format: "directory" },
});
