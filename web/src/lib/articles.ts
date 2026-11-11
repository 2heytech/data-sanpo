// 寄り道（/articles/）の一覧。本文は articles/<slug>.astro に書き、pages/articles/[slug].astro がページにする。
// 公開日（published）が来ていない記事は、ページも一覧も作らない。先にマージしておき、公開日の朝のビルドで出す（設計変更記録 #157）。
// 数値は本文に直接書かず、公開データから出す（components/ArticleValue.astro・ArticleRanking.astro）。
// 本文で名前を挙げた地域は ArticleRanking の expect に入れ、実データで表に出ないときはビルドを止める（設計変更記録 #126）。

/**
 * 記事のテーマ（設計変更記録 #232）。一覧の札・記事の末尾の「あわせて読みたい」・トップページの入口に使う。
 * 指標のジャンル（lib/genres.ts）とは別に、記事の数が偏らないように分けたもの。記事を足すときに1つ選ぶ
 */
export const ARTICLE_THEMES = [
  { id: "population", name: "人口" },
  { id: "life", name: "暮らしと家族" },
  { id: "money", name: "お金と仕事" },
  { id: "land", name: "地形と自然" },
  { id: "travel", name: "観光と交通" },
  { id: "reading", name: "データの読み方" },
] as const;
export type ArticleThemeId = (typeof ARTICLE_THEMES)[number]["id"];

export interface Article {
  slug: string;
  title: string;
  /** 一覧と検索結果の説明文 */
  description: string;
  /** 公開日・更新日（YYYY-MM-DD） */
  published: string;
  updated?: string;
  /** テーマ（ARTICLE_THEMES の id） */
  theme: ArticleThemeId;
  /** 主に使った指標（一覧の見出しの下に並べる） */
  indicators: string[];
  /** 記事の地図の画像に使う指標（ないときは indicators の最初。設計変更記録 #142） */
  mapIndicator?: string;
  /** 「データを地図で見る」の行き先（ないときは地図の画像と同じ。画像と違う指標・時点を見せたいとき。設計変更記録 #157） */
  mapHref?: string;
  /** 広告（楽天アフィリエイト）のリンクを置く記事。冒頭に「広告を含みます」を出す（設計変更記録 #189） */
  affiliate?: boolean;
}

export const ARTICLES: Article[] = [
  {
    slug: "snowfall-normals",
    title: "雪が1年に17m降る場所はどこ？：降雪量・最深積雪の平年値ランキング",
    description: "気象庁の平年値（1991〜2020年）で、雪がたくさん降る場所と深く積もる場所を観測所ごとに比べます。1年の降雪量が17mを超える観測所、積もる深さの1位、平地で2mを超える所、都道府県庁のある市も見ます。",
    published: "2026-11-20",
    theme: "land",
    // 天気の平年値は地図に重ねる観測所の点で、色分けの指標ではないので、記事の地図の画像はない。「データを地図で見る」は酸ケ湯を選んだ地図
    indicators: [],
    mapHref: "/map/?ws=wx-31482&wx=snowfall_normal",
  },
  {
    slug: "total-fertility-rate",
    title: "出生率が高い市区町村：合計特殊出生率の市区町村ランキング",
    description: "厚生労働省の2018〜2022年の合計特殊出生率で、出生率が高い市区町村を見ます。1位の徳之島町をはじめ2.0以上の11市町村、過去4回の1位、市と人口20万人以上の市区町村、都道府県の順位も見ます。",
    published: "2026-11-18",
    theme: "life",
    indicators: ["total_fertility_rate"],
    mapHref: "/map/?i=total_fertility_rate&p=2018-01-01&a=muni-46530&l=municipality",
  },
  {
    slug: "slope-building",
    title: "坂の多いまちはどこ？：建物用地の平均傾斜の市区町村ランキング",
    description: "家や店などが建つ土地（建物用地）の地面の傾きの平均で、坂の多いまちを比べます。1位の山あいの村、市の1位の熱海市、大きな市の1位の長崎市、都道府県の順位、地面全体の傾きとの違いも見ます。",
    published: "2026-11-16",
    theme: "land",
    indicators: ["slope_building_mean", "slope_building_steep_share", "slope_mean"],
    mapHref: "/map/?i=slope_building_mean&p=2021-04-01&a=muni-39364&l=municipality",
  },
  {
    slug: "life-expectancy",
    title: "平均寿命の長い都道府県・市区町村はどこ？",
    description: "厚生労働省の生命表（2020年）で、平均寿命の長い都道府県と市区町村を男女別に見ます。都道府県の1位の移り変わり、男女とも1位になった市区町村、上位に多い長野県の町村、2015年からの延びも見ます。",
    published: "2026-11-13",
    theme: "life",
    indicators: ["life_expectancy_male", "life_expectancy_female"],
    mapHref: "/map/?i=life_expectancy_male&p=2020-01-01&a=muni-14137&l=municipality",
  },
  {
    slug: "inbound-guest-share",
    title: "宿泊者の半分以上が外国人の都道府県はどこ？：延べ宿泊者に占める外国人の割合",
    description: "観光庁の宿泊旅行統計調査（2025年）で、ホテル・旅館の延べ宿泊者に占める外国人の割合を都道府県で比べます。半分を超えたのはどこか、コロナ禍の前からの移り変わり、日本人の宿泊者の増減も見ます。",
    published: "2026-11-11",
    theme: "travel",
    // 都道府県の値だけの指標なので、記事の地図の画像は都道府県別の図になる（#185）
    indicators: ["inbound_guest_share", "inbound_guest_nights", "guest_nights_japanese"],
    mapHref: "/map/?i=inbound_guest_share&p=2025-01-01&a=pref-13&l=prefecture",
  },
  {
    slug: "manufacturing-share",
    title: "働く人の7割が工場で働く町：製造業で働く人の割合ランキング",
    description: "経済センサス（2021年）で、働く人のうち製造業の事業所で働く人の割合を市区町村ごとに比べます。7割を超える3つの町村、市の1位、人数が最も多い豊田市とトヨタ町、出荷額、都道府県の順位も見ます。",
    published: "2026-11-09",
    updated: "2026-11-11",
    theme: "money",
    indicators: ["employees_manufacturing_share", "employees_manufacturing", "manufacturing_shipments"],
    mapHref: "/map/?i=employees_manufacturing_share&p=2021-06-01&a=muni-20521&l=municipality",
  },
  {
    slug: "agri-output-2024",
    title: "農業産出額の日本一は北海道でも九州でもない：市町村ランキング",
    description: "2024年の市町村別の農業産出額で1位になったのは、北海道でも九州でもないまちでした。6年ぶりに入れ替わった1位と2位の宮崎県都城市の違い、米・野菜・果実・畜産それぞれの1位、都道府県の順位も見ます。",
    published: "2026-11-06",
    updated: "2026-11-11",
    theme: "money",
    indicators: ["agri_output", "agri_output_vegetables", "agri_output_livestock", "agri_output_rice", "agri_output_fruits"],
    mapHref: "/map/?i=agri_output&p=2024-01-01&a=muni-23231&l=municipality",
  },
  {
    slug: "households-with-children",
    title: "いちばん小さい村は子育て世帯の割合1位：子どものいる世帯の割合",
    description: "2025年国勢調査で、18歳未満の子どもがいる世帯の割合を市区町村と都道府県で比べます。1位は面積が日本一小さい村で、上位には大きな市のとなりのまちが並びます。人で数えた15歳未満の割合との違いも見ます。",
    published: "2026-11-04",
    updated: "2026-11-11",
    theme: "life",
    indicators: ["households_with_children_share", "children_0_14_share"],
    mapHref: "/map/?i=households_with_children_share&p=2025-10-01&a=muni-16321&l=municipality",
  },
  {
    slug: "street-trees-ginkgo",
    title: "都道のイチョウが最も多い区はどこ？：東京の街路樹の本数",
    description: "東京都が公開している都道の街路樹のデータで、都の木イチョウの本数を市区町村ごとに数えます。イチョウが最も多い区、街路樹の4割以上がイチョウの市、町丁目で見た多い場所、ケヤキやサクラが多いまちも見ます。",
    published: "2026-11-02",
    updated: "2026-11-11",
    theme: "land",
    // 東京都だけの指標なので、記事の地図の画像は東京都の形に合わせた図になる（#168）
    indicators: ["street_trees_ginkgo", "street_trees", "street_trees_zelkova", "street_trees_cherry", "street_tree_species"],
    mapHref: "/map/?i=street_trees_ginkgo&p=2026-04-01&a=muni-13105&l=municipality",
  },
  {
    slug: "cultural-properties",
    title: "国宝・重要文化財の建造物：京都・奈良の次は大津市",
    description: "国宝・重要文化財の建造物を市区町村ごとに数えると、京都市・奈良市の次は滋賀県大津市です。登録有形文化財が最も多い愛知県犬山市、史跡の多い鎌倉市など、文化財の多いまちを、それぞれの上位10位の表で見ます。",
    published: "2026-10-30",
    updated: "2026-11-11",
    theme: "travel",
    indicators: ["important_cultural_buildings", "registered_cultural_buildings", "historic_sites"],
    mapHref: "/map/?i=important_cultural_buildings&a=muni-25201&l=municipality",
  },
  {
    slug: "lodging-hakuba",
    title: "旅館・ホテルが最も多い白馬村：宿と温泉のまち",
    description: "2021年の経済センサスで、旅館・ホテルの数が最も多い市区町村は長野県白馬村（381事業所）です。簡易宿所の多いまち、入湯税の多い温泉地（1位は箱根町）、働く人の半分近くが宿で働くまちを、上位の表で見ます。",
    published: "2026-10-28",
    updated: "2026-11-11",
    theme: "travel",
    indicators: ["ryokan_hotels", "simple_lodgings", "onsen_tax", "accommodation_employees"],
    mapHref: "/map/?i=ryokan_hotels&p=2021-06-01&a=muni-20485&l=municipality",
  },
  {
    slug: "stations-2019-2024",
    title: "急増したのは、あのテーマパークの駅：コロナ禍前より利用が増えた駅",
    description: "コロナ禍前の2019年度と2024年度の駅の乗降客数を比べます。多くの駅はまだ戻っていませんが、愛・地球博記念公園駅や河口湖駅、新幹線が延びた敦賀駅などは大きく増えています。",
    published: "2026-10-26",
    updated: "2026-11-11",
    theme: "travel",
    // 駅の乗降客数は地図に重ねる点で、色分けの指標ではないので、記事の地図の画像はない。「データを地図で見る」は駅を選んだ地図
    indicators: [],
    mapHref: "/map/?s=station-005422-9745e8",
  },
  {
    slug: "population-1920-2025",
    title: "100年前より人口が少ない県：1920年と2025年の都道府県の人口",
    description: "第1回国勢調査の1920年と2025年の人口を都道府県で比べます。100年で約7倍になった県がある一方、1920年より人口が少ない県もあります。人口がいちばん多かった年や順位の移り変わりも見ます。",
    published: "2026-10-23",
    updated: "2026-11-11",
    theme: "population",
    indicators: ["population_history", "population_total"],
    // 「人口（1920年からの推移）」は都道府県の値だけなので、記事の地図の画像は市区町村の人口（2025年）にする
    mapIndicator: "population_total",
    mapHref: "/map/?i=population_history&p=1920-10-01",
  },
  {
    slug: "area-largest-smallest",
    title: "日本一広い市・いちばん小さい村：市区町村の面積ランキング",
    description: "市区町村の面積ランキング。日本一広い市は東京都とほぼ同じ広さの岐阜県高山市（2,177.61km²）、いちばん小さい市は埼玉県蕨市（5.11km²）。広い・小さい上位10位と町・村の1位、都道府県の順位も表で紹介。",
    published: "2026-10-17",
    updated: "2026-11-11",
    theme: "land",
    indicators: ["area", "population_density"],
  },
  {
    slug: "fiscal-strength",
    title: "財政力指数1位は○○村？：財政力指数のランキング",
    description: "財政力指数（2024年度）の市町村ランキング。1以上の市町村は全国の1割に満たず、1位は1.99です。上位15位と、1以上の全市町村の表で、工場・発電所・空港のあるまちや別荘地など、どんなまちが並ぶかを見ます。",
    published: "2026-10-17",
    updated: "2026-11-11",
    theme: "money",
    indicators: ["fiscal_strength_index", "taxable_income_per_taxpayer"],
  },
  {
    slug: "population-growth-2010-2025",
    title: "人口が増え続けるまちはどこ？：2010〜2025年の市区町村ランキング",
    description: "2010・2015・2020・2025年の国勢調査で毎回人口が増えた市区町村は、全国の1割ほどです。大都市の中心部、新しい鉄道沿いの郊外、大きな都市に近いまち、沖縄県の町村など、増え続けたまちを増加率の上位の表で見ます。",
    published: "2026-10-17",
    updated: "2026-11-11",
    theme: "population",
    indicators: ["population_total", "population_change_rate"],
    mapIndicator: "population_change_rate",
  },
  {
    slug: "elevation",
    title: "平均標高がマイナスの村はどこ？：市区町村の平均標高ランキング",
    description: "市区町村の平均標高ランキング。1位は長野県川上村（1,624.6m）で、平均が海面より低いまちも4つあります。高い・低い上位10位と高低差の大きいまち、都道府県の上位・下位5位（1位は長野県）を表で紹介。",
    published: "2026-10-17",
    updated: "2026-11-11",
    theme: "land",
    indicators: ["elevation_mean", "elevation_range"],
  },
  {
    slug: "paddy-bamboo",
    title: "8割近くが田んぼの町はどこ？：田んぼ・竹林の割合が高い市区町村",
    description: "田の割合（2021年度の土地利用）と竹林の割合（植生図）が高い市区町村の上位10位。田の1位は79.8%の町、竹林の1位は山口県周防大島町（17.3%）です。都道府県の上位5位（田は佐賀県、竹林は山口県が1位）も紹介。",
    published: "2026-10-17",
    updated: "2026-11-11",
    theme: "land",
    indicators: ["land_use_paddy_share", "vegetation_bamboo_share"],
  },
  {
    slug: "population-change-2025",
    title: "人口が増えた都道府県は1つだけ：2025年国勢調査の人口増減ランキング",
    description: "2025年国勢調査の人口増減ランキング。5年前より人口が増えた都道府県は1つだけで、市区町村の8割以上で減りました。都道府県の上位10位・下位5位と、増えた・減った市区町村の上位の表で、増えたのはどんな地域かを読みます。",
    published: "2026-10-16",
    updated: "2026-11-11",
    theme: "population",
    indicators: ["population_change_rate", "population_total"],
  },
  {
    slug: "daytime-population",
    title: "昼の人口が住民の17.5倍になる区：昼夜間人口比率のランキング",
    description: "昼夜間人口比率（2020年）のランキング。昼の人口が住民の17.5倍になる区から、昼に人が出ていくベッドタウンまで、高い・低い市区町村の上位10位と、都道府県の上位・下位5位を表で比べます。",
    published: "2026-10-16",
    updated: "2026-11-11",
    theme: "population",
    indicators: ["daytime_night_ratio", "daytime_population"],
  },
  {
    slug: "aging-rate",
    title: "65歳以上の割合（高齢化率）が高い市区町村・低い市区町村",
    description: "2025年国勢調査の高齢化率（65歳以上の割合）ランキング。1位は群馬県南牧村（68.9%）で、半分以上が65歳以上のまちは100を超えます。高い・低い市区町村の上位10位、都道府県の上位・下位5位、町丁目で見た差も紹介。",
    published: "2026-10-16",
    updated: "2026-11-11",
    theme: "life",
    indicators: ["aged_65_plus_share", "children_0_14_share"],
  },
  {
    slug: "commute-rail-car",
    title: "車で通う人が8割を超える県はどこ？：通勤・通学の交通手段ランキング",
    description: "2020年国勢調査の通勤・通学の交通手段ランキング。自家用車を使う人の割合は、8割を超える県から東京都の1割まで差があります。車・鉄道・自転車の割合が高い市区町村の上位6位と、都道府県の上位・下位5位を表で紹介。",
    published: "2026-10-16",
    updated: "2026-11-11",
    theme: "money",
    indicators: ["commute_car_share", "commute_rail_share", "commute_walk_share", "commute_bicycle_share"],
  },
  {
    slug: "taxable-income",
    title: "「平均年収」上位に、ほたての村？：所得の高い市区町村ランキング",
    description: "課税対象所得の納税者1人あたり額（2025年度）のランキング。1位の東京都港区は約1,810万円で、都道府県でも東京都が突出しています。市区町村と都道府県の上位10位の表と、「平均年収」として読むときの注意を紹介。",
    published: "2026-10-16",
    updated: "2026-11-11",
    theme: "money",
    indicators: ["taxable_income_per_taxpayer", "resident_tax_per_taxpayer"],
  },
  {
    slug: "foreign-residents",
    title: "割合1位は東京でも大阪でもない：外国人住民の割合が高い市区町村",
    description: "住民基本台帳（2026年1月1日現在）の外国人住民の割合ランキング。1位の村は3割を超えます。市区町村の上位10位と都道府県の上位5位の表で、リゾート地・製造業のまち・大都市の古くからの集住地という3つの背景を読みます。",
    published: "2026-10-16",
    updated: "2026-11-11",
    theme: "life",
    indicators: ["foreign_residents_share", "census_foreign_brazil_share", "census_foreign_korea_share"],
  },
  {
    slug: "furusato-nozei",
    title: "住民1人あたり300万円を超える町はどこ？：ふるさと納税の受入額ランキング",
    description: "ふるさと納税の受入額（2025年度）のランキング。受入額の1位は大阪府泉佐野市（約230億円）、住民1人あたりの1位は300万円を超えます。市区町村の上位10位と、県と県内の市区町村を合わせた都道府県の上位5位を表で紹介。",
    published: "2026-10-16",
    updated: "2026-11-11",
    theme: "money",
    indicators: ["furusato_amount", "furusato_amount_per_capita"],
    affiliate: true,
  },
  {
    slug: "vacant-houses",
    title: "空き家率70%の町、その正体は？：空き家率の市区町村ランキング",
    description: "住宅・土地統計調査（2023年）の空き家率ランキング。空き家率が7割を超える町があり、市区町村の上位には別荘地が並びます。高い・低い市区町村の上位8位と、都道府県の上位・下位5位の表で、数字の中身に注意して読みます。",
    published: "2026-10-16",
    updated: "2026-11-11",
    theme: "life",
    indicators: ["vacant_house_rate"],
  },
  {
    slug: "single-households",
    title: "一人暮らしが8割を超えるまちがある：一人暮らし世帯の割合ランキング",
    description: "2025年国勢調査の一人暮らし世帯の割合ランキング。東京都は一般世帯の半分を超え、市区町村では8割を超えるまちもあります。割合の高い方12位・低い方8位までの市区町村と、都道府県の上位・下位5位を表で紹介します。",
    published: "2026-10-16",
    updated: "2026-11-11",
    theme: "life",
    indicators: ["single_person_household_share", "persons_per_household"],
  },
  {
    slug: "reading-public-data",
    title: "公開データを地図で読むときの5つの注意",
    description: "数と割合、時点、地域の単位、値がない地域、相関と因果。統計を地図や順位で見るときに気をつけたいことを、データさんぽの実例で説明します。",
    published: "2026-10-16",
    updated: "2026-11-11",
    theme: "reading",
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

/** テーマの名前（「暮らしと家族」など） */
export const themeName = (id: ArticleThemeId): string => ARTICLE_THEMES.find((t) => t.id === id)!.name;

/** テーマで絞り込んだ一覧のアドレス（一覧ページのスクリプトが ?theme= を読む） */
export const themeHref = (id: ArticleThemeId): string => `/articles/?theme=${id}`;

/** 記事のあるテーマと、その本数（ARTICLE_THEMES の並びのまま） */
export function themeCounts(list: Article[]): { id: ArticleThemeId; name: string; count: number }[] {
  return ARTICLE_THEMES.map((t) => ({ ...t, count: list.filter((a) => a.theme === t.id).length })).filter((t) => t.count > 0);
}

/** 公開の新しい順。本文を直した日（updated）では並べ替えない。同じ日の記事は一覧（ARTICLES）の並びのまま */
export function newestFirst(list: Article[]): Article[] {
  return [...list].sort((a, b) => b.published.localeCompare(a.published));
}

/** 「2026-10-16」→「2026年10月16日」 */
export function formatDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${y}年${m}月${d}日`;
}
