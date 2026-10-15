// 指標の分類（ジャンルとその中のカテゴリ）の並び。トップページの指標一覧と、地図の指標の選択画面で使う。
// ここにないカテゴリは「その他」として最後に出る
export const GENRES: { title: string; categories: string[] }[] = [
  { title: "人と暮らし", categories: ["人口・世帯", "年齢構成", "暮らし方", "外国人住民", "子育て"] },
  { title: "仕事と学び", categories: ["働き方", "通勤・通学", "学歴", "教育"] },
  { title: "安全", categories: ["犯罪", "交通事故"] },
  { title: "所得と税・財政", categories: ["所得・税", "財政"] },
  { title: "産業", categories: ["農業", "工業", "商業"] },
  { title: "まちと土地", categories: ["土地", "交通", "地価", "緑", "観光"] },
  { title: "天気", categories: ["天気"] },
  { title: "選挙", categories: ["選挙"] },
];

/** 実際にあるカテゴリだけのジャンルの並び（並びにないカテゴリは「その他」にまとめる） */
export function genresFor(present: Iterable<string>): { title: string; categories: string[] }[] {
  const have = new Set(present);
  const known = new Set(GENRES.flatMap((g) => g.categories));
  const rest = [...have].filter((c) => !known.has(c));
  return [...GENRES, ...(rest.length ? [{ title: "その他", categories: rest }] : [])]
    .map((g) => ({ title: g.title, categories: g.categories.filter((c) => have.has(c)) }))
    .filter((g) => g.categories.length);
}
