// 寄り道（/articles/）の一覧。本文は articles/<slug>.astro に書き、pages/articles/[slug].astro がページにする。
// 公開日（published）が来ていない記事は、ページも一覧も作らない。先にマージしておき、公開日の朝のビルドで出す（設計変更記録 #157）。
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
  /** 記事の地図の画像に使う指標（ないときは indicators の最初。設計変更記録 #142） */
  mapIndicator?: string;
  /** 「データを地図で見る」の行き先（ないときは地図の画像と同じ。画像と違う指標・時点を見せたいとき。設計変更記録 #157） */
  mapHref?: string;
}

export const ARTICLES: Article[] = [
  {
    slug: "agri-output-2024",
    title: "農業産出額の日本一は北海道でも九州でもない：市町村ランキング",
    description: "2024年の市町村別の農業産出額で1位になったのは、北海道でも九州でもないまちでした。6年ぶりに入れ替わった1位と2位の宮崎県都城市の違い、米・野菜・果実・畜産それぞれの1位、都道府県の順位も見ます。",
    published: "2026-11-06",
    indicators: ["agri_output", "agri_output_vegetables", "agri_output_livestock", "agri_output_rice", "agri_output_fruits"],
    mapHref: "/map/?i=agri_output&p=2024-01-01&a=muni-23231&l=municipality",
  },
  {
    slug: "households-with-children",
    title: "いちばん小さい村は子育て世帯の割合1位：子どものいる世帯の割合",
    description: "2025年国勢調査で、18歳未満の子どもがいる世帯の割合を市区町村と都道府県で比べます。1位は面積が日本一小さい村で、上位には大きな市のとなりのまちが並びます。人で数えた15歳未満の割合との違いも見ます。",
    published: "2026-11-04",
    indicators: ["households_with_children_share", "children_0_14_share"],
    mapHref: "/map/?i=households_with_children_share&p=2025-10-01&a=muni-16321&l=municipality",
  },
  {
    slug: "street-trees-ginkgo",
    title: "都道のイチョウが最も多い区はどこ？：東京の街路樹の本数",
    description: "東京都が公開している都道の街路樹のデータで、都の木イチョウの本数を市区町村ごとに数えます。イチョウが最も多い区、街路樹の4割以上がイチョウの市、町丁目で見た多い場所、ケヤキやサクラが多いまちも見ます。",
    published: "2026-11-02",
    // 東京都だけの指標なので、記事の地図の画像は東京都の形に合わせた図になる（#168）
    indicators: ["street_trees_ginkgo", "street_trees", "street_trees_zelkova", "street_trees_cherry", "street_tree_species"],
    mapHref: "/map/?i=street_trees_ginkgo&p=2026-04-01&a=muni-13105&l=municipality",
  },
  {
    slug: "cultural-properties",
    title: "国宝・重要文化財の建造物：京都・奈良の次は大津市",
    description: "国宝・重要文化財の建造物を市区町村ごとに数えると、京都市・奈良市の次は滋賀県大津市です。登録有形文化財が最も多い愛知県犬山市、史跡の多い鎌倉市など、文化財の多いまちを見ます。",
    published: "2026-10-30",
    indicators: ["important_cultural_buildings", "registered_cultural_buildings", "historic_sites"],
    mapHref: "/map/?i=important_cultural_buildings&a=muni-25201&l=municipality",
  },
  {
    slug: "lodging-hakuba",
    title: "旅館・ホテルが最も多い白馬村：宿と温泉のまち",
    description: "旅館・ホテルの数が最も多い市区町村は長野県白馬村です。小さな宿の多さ、入湯税の多い温泉地、働く人の半分近くが宿で働くまちなど、宿と温泉のまちをデータで見ます。",
    published: "2026-10-28",
    indicators: ["ryokan_hotels", "simple_lodgings", "onsen_tax", "accommodation_employees"],
    mapHref: "/map/?i=ryokan_hotels&p=2021-06-01&a=muni-20485&l=municipality",
  },
  {
    slug: "stations-2019-2024",
    title: "急増したのは、あのテーマパークの駅：コロナ禍前より利用が増えた駅",
    description: "コロナ禍前の2019年度と2024年度の駅の乗降客数を比べます。多くの駅はまだ戻っていませんが、愛・地球博記念公園駅や河口湖駅、新幹線が延びた敦賀駅などは大きく増えています。",
    published: "2026-10-26",
    // 駅の乗降客数は地図に重ねる点で、色分けの指標ではないので、記事の地図の画像はない。「データを地図で見る」は駅を選んだ地図
    indicators: [],
    mapHref: "/map/?s=station-005422-9745e8",
  },
  {
    slug: "population-1920-2025",
    title: "100年前より人口が少ない県：1920年と2025年の都道府県の人口",
    description: "第1回国勢調査の1920年と2025年の人口を都道府県で比べます。100年で約7倍になった県がある一方、1920年より人口が少ない県もあります。人口がいちばん多かった年や順位の移り変わりも見ます。",
    published: "2026-10-23",
    indicators: ["population_history", "population_total"],
    // 「人口（1920年からの推移）」は都道府県の値だけなので、記事の地図の画像は市区町村の人口（2025年）にする
    mapIndicator: "population_total",
    mapHref: "/map/?i=population_history&p=1920-10-01",
  },
  {
    slug: "area-largest-smallest",
    title: "日本一広い市・いちばん小さい村：市区町村の面積ランキング",
    description: "市区町村と都道府県の面積を比べます。東京都とほぼ同じ広さの岐阜県高山市から、最も小さい富山県舟橋村まで、広いまち・小さいまちの顔ぶれを見ます。",
    published: "2026-10-17",
    indicators: ["area", "population_density"],
  },
  {
    slug: "fiscal-strength",
    title: "財政力指数1位は○○村？：財政力指数のランキング",
    description: "財政力指数が1以上の市町村は全国のごく一部です。工場の多いまち、発電所や空港のあるまち、住宅地や別荘地など、どんなまちが並ぶかを見ます。",
    published: "2026-10-17",
    indicators: ["fiscal_strength_index", "taxable_income_per_taxpayer"],
  },
  {
    slug: "population-growth-2010-2025",
    title: "人口が増え続けるまちはどこ？：2010〜2025年の市区町村ランキング",
    description: "2010・2015・2020・2025年の国勢調査で毎回人口が増えた市区町村。大都市の中心部、新しい鉄道沿いの郊外、沖縄県の町村など、増え続けたまちを見ます。",
    published: "2026-10-17",
    indicators: ["population_total", "population_change_rate"],
    mapIndicator: "population_change_rate",
  },
  {
    slug: "elevation",
    title: "平均標高がマイナスの村はどこ？：市区町村の平均標高ランキング",
    description: "地面の高さの平均（平均標高）が高い市区町村と低い市区町村。長野県の高原の村から、平均が海面より低い秋田県大潟村や濃尾平野のまちまでを比べます。",
    published: "2026-10-17",
    indicators: ["elevation_mean", "elevation_range"],
  },
  {
    slug: "paddy-bamboo",
    title: "8割近くが田んぼの町はどこ？：田んぼ・竹林の割合が高い市区町村",
    description: "土地利用のデータで田の割合が高い市区町村と、植生図で竹林の割合が高い市区町村を見ます。各地の平野の米どころと、瀬戸内や京都の竹林のまちです。",
    published: "2026-10-17",
    indicators: ["land_use_paddy_share", "vegetation_bamboo_share"],
  },
  {
    slug: "population-change-2025",
    title: "人口が増えた都道府県は1つだけ：2025年国勢調査の人口増減ランキング",
    description: "2025年国勢調査で、5年前より人口が増えた市区町村と減った市区町村。全国の約8割が減少するなか、増えたのはどんな地域か、都道府県と市区町村の順位から読みます。",
    published: "2026-10-16",
    indicators: ["population_change_rate", "population_total"],
  },
  {
    slug: "daytime-population",
    title: "昼の人口が住民の17.5倍になる区：昼夜間人口比率のランキング",
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
    title: "車で通う人が8割を超える県はどこ？：通勤・通学の交通手段ランキング",
    description: "2020年国勢調査の通勤・通学の交通手段から、自家用車を使う人の割合と鉄道・電車を使う人の割合を、都道府県と市区町村で比べます。",
    published: "2026-10-16",
    indicators: ["commute_car_share", "commute_rail_share", "commute_walk_share", "commute_bicycle_share"],
  },
  {
    slug: "taxable-income",
    title: "「平均年収」上位に、ほたての村？：所得の高い市区町村ランキング",
    description: "市区町村の所得水準の目安になる「課税対象所得の納税者1人あたり額」の上位と都道府県の違い。平均年収のランキングとして読むときの注意点もまとめます。",
    published: "2026-10-16",
    indicators: ["taxable_income_per_taxpayer", "resident_tax_per_taxpayer"],
  },
  {
    slug: "foreign-residents",
    title: "割合1位は東京でも大阪でもない：外国人住民の割合が高い市区町村",
    description: "住民基本台帳の外国人住民の割合を、都道府県と市区町村で比べます。リゾート地、製造業のまち、大都市の古くからの集住地など、割合が高い地域の背景を国籍別の数字とあわせて読みます。",
    published: "2026-10-16",
    indicators: ["foreign_residents_share", "census_foreign_brazil_share", "census_foreign_korea_share"],
  },
  {
    slug: "furusato-nozei",
    title: "住民1人あたり300万円を超える町はどこ？：ふるさと納税の受入額ランキング",
    description: "ふるさと納税の受入額の上位の自治体と、住民1人あたりにした額の上位。金額の大きさだけでなく、自治体の規模とあわせて見ると違う顔ぶれになります。",
    published: "2026-10-16",
    indicators: ["furusato_amount", "furusato_amount_per_capita"],
  },
  {
    slug: "vacant-houses",
    title: "空き家率70%の町、その正体は？：空き家率の市区町村ランキング",
    description: "住宅・土地統計調査（2023年）の空き家率を、都道府県と市区町村で比べます。空き家率が高い地域には別荘地が多いなど、数字の中身に注意して読みます。",
    published: "2026-10-16",
    indicators: ["vacant_house_rate"],
  },
  {
    slug: "single-households",
    title: "一人暮らしが8割を超えるまちがある：一人暮らし世帯の割合ランキング",
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

/**
 * ビルドする日（日本時間の YYYY-MM-DD）。公開前の記事を確かめるときは ARTICLES_AS_OF=2026-10-30 のように
 * その日の時点として作れる（公開のビルドでは使わない）
 */
export function articlesAsOf(now: Date = new Date()): string {
  const asOf = process.env.ARTICLES_AS_OF;
  if (asOf && /^\d{4}-\d{2}-\d{2}$/.test(asOf)) return asOf;
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

/** 公開日が来た記事（ARTICLES の並びのまま）。一覧・ページ・画像・ほかの寄り道はこれだけを使う */
export function publishedArticles(asOf: string = articlesAsOf()): Article[] {
  return ARTICLES.filter((a) => a.published <= asOf);
}

/** 「2026-10-16」→「2026年10月16日」 */
export function formatDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${y}年${m}月${d}日`;
}
