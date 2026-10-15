/**
 * 全国の市区町村の中で順位が特に高い・低い指標に付ける考察の文（areaInsights で使う）。
 * 「〜と思われます」「〜と考えられます」「〜ようです」で書き、断定しない。
 * high は値が大きい（順位が上の）とき、low は値が小さいときの文。どちらかがない指標はその向きでは出さない。
 * ほかの考察（昼夜間人口比率・年齢構成・一人暮らしなど）がすでに扱う指標と向きは、ここには入れない。
 * 地域や住む人を悪く言うように読める文（犯罪が多い、所得や学歴が低い、寿命が短いなど）は作らない。
 * highTone・lowTone は文の印象（pos: 地域の良いところ、neg: 課題）。ネガティブな文だけのページにしないために使う。
 */
export type Tone = "pos" | "neg";

export interface RankTemplate {
  high?: string;
  low?: string;
  highTone?: Tone;
  lowTone?: Tone;
  /** 値の少ない地域を除くために見る件数・人数の指標と、その最小値 */
  minCountOf?: string;
  minCount?: number;
}

export const RANK_TEMPLATES: Record<string, RankTemplate> = {
  // 人口・世帯・住まい
  population_density: {
    high: "建物が密集した、全国でも有数の都市部と考えられます。",
    low: "山林や農地が広く、家がまばらに点在するまちと考えられます。",
  },
  persons_per_household: { low: "一人暮らしや二人暮らしの小さな世帯が中心のようです。" },
  households_with_children_share: {
    high: "子育て中の家族が多く住む地域と思われます。",
    highTone: "pos",
    low: "子育てを終えた世帯や単身の世帯が多いようです。",
  },
  owner_occupied_share: { low: "借家や賃貸マンションに住む人が多く、人の入れ替わりが多い地域のようです。" },
  high_rise_household_share: { high: "タワーマンションなど高層の住宅が多く建つ地域と思われます。" },
  same_residence_5y_share: {
    high: "引っ越す人が少なく、長く住み続ける人の多い落ち着いた地域と考えられます。",
    highTone: "pos",
    low: "転入・転出が多く、新しく住み始める人の多い地域のようです。",
  },
  residence_under1y_share: { high: "この1年で移り住んだ人が多く、新しい住民が次々に加わる地域のようです。" },
  // 仕事・学び
  self_employed_share: {
    high: "農家や商店、職人など、自分で事業をしている人が多い地域と思われます。",
    low: "会社や役所などに勤める人が中心の地域のようです。",
  },
  professional_share: { high: "研究所や病院、IT 企業など、専門的な仕事をする人が多く住んでいると考えられます。" },
  manager_share: { high: "会社の役員や管理職の人が多く住む地域と思われます。" },
  commute_walk_share: { high: "職場や学校が住まいの近くにあり、歩いて通える暮らしのようです。", highTone: "pos" },
  commute_bicycle_share: { high: "平らな土地が多く、自転車で通勤・通学しやすいまちと考えられます。" },
  commute_bus_share: { high: "鉄道より路線バスが通勤・通学の足になっている地域のようです。" },
  commute_car_share: { low: "車を使わずに通勤・通学できる、公共交通の便利な地域と思われます。", lowTone: "pos" },
  university_graduate_share: { high: "大学を出た人が多く住む地域と考えられます。" },
  preschool_kindergarten_share: { high: "小学校に入る前は幼稚園に通うのが一般的な地域のようです。" },
  preschool_nursery_share: { high: "共働きの家庭が多く、保育園を使う家庭が多いと考えられます。" },
  preschool_kodomoen_share: { high: "幼稚園や保育園の認定こども園への切り替えが進んだ地域のようです。" },
  jhs_students_private: { high: "私立中学校に通う子どもが多く、中学受験が盛んな地域と思われます。" },
  // 学級の人数は学校の大きさや子どもの多さではなく、学年の児童を何学級に分けるか（学級編制）で決まる
  elem_class_size: {
    high: "1つの学級の児童が多く、上限（小学校は35人）に近い人数で学級を編制している学校が多いと考えられます。",
    low: "1つの学級の児童が少なく、先生の目が一人ひとりに届きやすい環境と考えられます。",
  },
  hs_grad_vocational_rate: { high: "まちにある高校では、専門学校で資格や技術を身につける進路を選ぶ人が多いようです。" },
  // 暮らし・健康
  total_fertility_rate: {
    high: "子どもを多く持つ家庭が多い地域と考えられます。",
    highTone: "pos",
    low: "若い単身の人が多い都市部などで低くなりやすく、その影響があると考えられます。",
    lowTone: "neg",
  },
  life_expectancy_male: { high: "健康で長生きの男性が多い地域のようです。", highTone: "pos" },
  life_expectancy_female: { high: "健康で長生きの女性が多い地域のようです。", highTone: "pos" },
  taxable_income_per_taxpayer: { high: "所得の高い人が多く住む地域と考えられます。" },
  income_levy_taxpayer_share: { high: "働いて所得を得ている人の割合が高い、現役世代の多い地域と思われます。" },
  vacant_house_rate: { low: "空き家が少なく、住まいの需要が高い地域のようです。", lowTone: "pos" },
  // 安全（犯罪が多い方は、住む人が悪く見られかねないので文にしない。少ない方だけ）
  traffic_accidents_per_100_residents: {
    high: "住民の数に比べて事故が多く、通過する車や観光客の多い道路があると考えられます。",
    highTone: "neg",
    low: "住民の数に比べて事故が少ない、落ち着いた地域のようです。",
    lowTone: "pos",
  },
  street_crime_total_per_100_residents: { low: "住民の数に比べて件数が少ない、落ち着いた地域のようです。", lowTone: "pos" },
  // 産業（規模の大きさがそのまま出る件数・金額は、上位だけを見る）
  agri_output_rice: { high: "全国有数の米どころと思われます。", highTone: "pos" },
  agri_output_vegetables: { high: "全国有数の野菜の産地と思われます。", highTone: "pos" },
  agri_output_fruits: { high: "果物の産地として知られる地域と考えられます。", highTone: "pos" },
  agri_output_livestock: { high: "牛や豚、鶏などの畜産が盛んな地域と思われます。", highTone: "pos" },
  manufacturing_shipments: { high: "大きな工場が集まる、全国有数のものづくりの拠点と考えられます。", highTone: "pos" },
  wholesale_sales: { high: "企業の本社や問屋が集まる、卸売の拠点と考えられます。", highTone: "pos" },
  // 選挙（値が大きいときだけ）
  vote_share_ldp: { high: "この政党への支持が厚い地域のようです。" },
  vote_share_cdp: { high: "この政党への支持が厚い地域のようです。" },
  vote_share_komeito: { high: "この政党への支持が厚い地域のようです。" },
  vote_share_ishin: { high: "この政党への支持が厚い地域のようです。" },
  vote_share_dpfp: { high: "この政党への支持が厚い地域のようです。" },
  vote_share_jcp: { high: "この政党への支持が厚い地域のようです。" },
  vote_share_reiwa: { high: "この政党への支持が厚い地域のようです。" },
  vote_share_sanseito: { high: "この政党への支持が厚い地域のようです。" },
  vote_share_sdp: { high: "この政党への支持が厚い地域のようです。" },
  vote_share_hoshu: { high: "この政党への支持が厚い地域のようです。" },
  vote_share_mirai: { high: "この政党への支持が厚い地域のようです。" },
  vote_share_chudo: { high: "この政党への支持が厚い地域のようです。" },
};

/** 国勢調査の国籍別の外国人の割合（census_foreign_<国>_share）。人数が少ない地域は除く */
export function nationalityTemplate(id: string, indicatorName: string): RankTemplate | null {
  const m = id.match(/^census_foreign_(\w+)_share$/);
  if (!m) return null;
  const country = indicatorName.match(/（([^（）]+)）$/)?.[1];
  if (!country) return null;
  return {
    high: `${country}の人が多く暮らす地域のようです。働く場や学ぶ場を通じたつながりがあると考えられます。`,
    minCountOf: `census_foreign_${m[1]}`,
    minCount: 20,
  };
}
