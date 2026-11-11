/// <reference path="../.astro/types.d.ts" />

declare namespace App {
  interface Locals {
    /** 寄り道の本文から、表に出てくる地域を集めているときだけ入る（lib/articleMentions.ts。設計変更記録 #234） */
    articleTables?: import("./lib/articleLinks").TableMention[];
  }
}
