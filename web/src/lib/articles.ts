// 寄り道（/articles/）の一覧。本文は pages/articles/<slug>.astro に書く。
// 数値は本文に直接書かず、公開データから出す（components/ArticleValue.astro・ArticleRanking.astro）。
// 本文で名前を挙げた地域は ArticleRanking の expect に入れ、実データで表に出ないときはビルドを止める（設計変更記録 #126）。

export interface Article {
  slug: string;
  title: string;
  /** 一覧と検索結果の説明文 */
  description: string;
  /** 公開日・更新日（YYYY-MM-DD） */
  published: string;
  updated?: string;
  /** 主に使った指標（一覧の見出しの下に並べる） */
  indicators: string[];
}

export const ARTICLES: Article[] = [
  {
    slug: "population-change-2025",
    title: "人口が増えた市区町村・減った市区町村（2025年国勢調査）",
    description: "2025年国勢調査で、5年前より人口が増えた市区町村と減った市区町村。全国の約8割が減少するなか、増えたのはどんな地域か、都道府県と市区町村の順位から読みます。",
    published: "2026-10-16",
    indicators: ["population_change_rate", "population_total"],
  },
  {
    slug: "daytime-population",
    title: "昼夜間人口比率で見る「昼に人が集まるまち」と「ベッドタウン」",
    description: "昼夜間人口比率（住んでいる人を100としたときの昼間の人口）で、通勤・通学で人が集まるまちと、人が出ていくまちを全国の市区町村で比べます。",
    published: "2026-10-16",
    indicators: ["daytime_night_ratio", "daytime_population"],
  },
  {
    slug: "aging-rate",
    title: "65歳以上の割合（高齢化率）が高い市区町村・低い市区町村",
    description: "2025年国勢調査の65歳以上の割合を、都道府県と市区町村で比べます。高齢化率が50%を超える町村と、都心の若いまちの違い、町丁目で見たときの差も紹介します。",
    published: "2026-10-16",
    indicators: ["aged_65_plus_share", "children_0_14_share"],
  },
  {
    slug: "commute-rail-car",
    title: "通勤・通学は電車か車か：都道府県と市区町村で比べる",
    description: "2020年国勢調査の通勤・通学の交通手段から、自家用車を使う人の割合と鉄道・電車を使う人の割合を、都道府県と市区町村で比べます。",
    published: "2026-10-16",
    indicators: ["commute_car_share", "commute_rail_share", "commute_walk_share", "commute_bicycle_share"],
  },
  {
    slug: "taxable-income",
    title: "所得水準の高い市区町村：課税対象所得の納税者1人あたり額",
    description: "市区町村の所得水準の目安になる「課税対象所得の納税者1人あたり額」の上位と都道府県の違い。平均年収のランキングとして読むときの注意点もまとめます。",
    published: "2026-10-16",
    indicators: ["taxable_income_per_taxpayer", "resident_tax_per_taxpayer"],
  },
  {
    slug: "foreign-residents",
    title: "外国人住民の割合が高い市区町村",
    description: "住民基本台帳の外国人住民の割合を、都道府県と市区町村で比べます。リゾート地、製造業のまち、大都市の古くからの集住地など、割合が高い地域の背景を国籍別の数字とあわせて読みます。",
    published: "2026-10-16",
    indicators: ["foreign_residents_share", "census_foreign_brazil_share", "census_foreign_korea_share"],
  },
  {
    slug: "furusato-nozei",
    title: "ふるさと納税の受入額が多い自治体",
    description: "ふるさと納税の受入額の上位の自治体と、住民1人あたりにした額の上位。金額の大きさだけでなく、自治体の規模とあわせて見ると違う顔ぶれになります。",
    published: "2026-10-16",
    indicators: ["furusato_amount", "furusato_amount_per_capita"],
  },
  {
    slug: "vacant-houses",
    title: "空き家率の高い市区町村・低い市区町村（住宅・土地統計調査2023年）",
    description: "住宅・土地統計調査（2023年）の空き家率を、都道府県と市区町村で比べます。空き家率が高い地域には別荘地が多いなど、数字の中身に注意して読みます。",
    published: "2026-10-16",
    indicators: ["vacant_house_rate"],
  },
  {
    slug: "single-households",
    title: "一人暮らし世帯の割合：都市部で半分を超えるまち",
    description: "国勢調査の一人暮らし世帯の割合を、都道府県と市区町村で比べます。東京都では一般世帯の半分を超え、全国でも5年でさらに増えました。",
    published: "2026-10-16",
    indicators: ["single_person_household_share", "persons_per_household"],
  },
  {
    slug: "reading-public-data",
    title: "公開データを地図で読むときの5つの注意",
    description: "数と割合、時点、地域の単位、値がない地域、相関と因果。統計を地図や順位で見るときに気をつけたいことを、データさんぽの実例で説明します。",
    published: "2026-10-16",
    indicators: [],
  },
];

export const articleBySlug = (slug: string) => ARTICLES.find((a) => a.slug === slug);

/** 「2026-10-16」→「2026年10月16日」 */
export function formatDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${y}年${m}月${d}日`;
}
