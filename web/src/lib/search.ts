import type { Level, SearchIndex } from "./types";

const KANJI_DIGITS: Record<string, number> = {
  〇: 0, 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9,
};

function kanjiNumber(s: string): string {
  // 1〜99 の漢数字を算用数字に（例: 二十三 → 23）
  let n = 0;
  let cur = 0;
  for (const ch of s) {
    if (ch === "十") {
      n += (cur || 1) * 10;
      cur = 0;
    } else {
      cur = KANJI_DIGITS[ch];
    }
  }
  return String(n + cur);
}

/** 検索用の正規化: 全角半角・カタカナ／ひらがな・漢数字の丁目・空白の違いを吸収する。 */
export function normalize(text: string): string {
  return text
    .normalize("NFKC")
    // 霞ヶ関／霞ケ関／霞が関 を同一視
    .replace(/(?<=\p{Script=Han})[ヶケヵが](?=\p{Script=Han})/gu, "が")
    .replace(/[ァ-ヶ]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0x60))
    .replace(/([〇一二三四五六七八九十]+)(?=丁目|番|丁|$)/g, (m) => kanjiNumber(m))
    .replace(/\s+/g, "")
    .toLowerCase();
}

export interface SearchHit {
  id: string;
  name: string;
  context: string;
  level: Level;
}

export class AreaSearch {
  private items: (SearchHit & { key: string; nameKey: string })[] = [];

  constructor(index: SearchIndex) {
    this.add(index);
  }

  /** 索引を追加する（町丁・字等の索引は都道府県ごとに分かれていて、必要になってから読む） */
  add(index: SearchIndex): void {
    for (const [id, name, context, level] of index.entries) {
      this.items.push({ id, name, context, level, key: normalize(context + name), nameKey: normalize(name) });
    }
  }

  search(query: string, limit = 10): SearchHit[] {
    const q = normalize(query);
    if (!q) return [];
    const scored: [number, SearchHit][] = [];
    for (const item of this.items) {
      const nameKey = item.nameKey;
      let score = -1;
      if (nameKey === q) score = 0;
      else if (nameKey.startsWith(q)) score = 1;
      else if (nameKey.includes(q)) score = 2;
      else if (item.key.includes(q)) score = 3;
      if (score >= 0) {
        // 市区町村を先に、短い名前を先に
        scored.push([score * 10 + (item.level === "small_area" ? 1 : 0), item]);
      }
    }
    scored.sort((a, b) => a[0] - b[0] || a[1].name.length - b[1].name.length);
    return scored.slice(0, limit).map(([, { id, name, context, level }]) => ({ id, name, context, level }));
  }
}
