/**
 * 全国の市区町村の中で順位が特に高い・低い指標に付ける考察の文（areaInsights で使う）。
 * 「〜と思われます」「〜と考えられます」「〜ようです」で書き、断定しない。
 * high は値が大きい（順位が上の）とき、low は値が小さいときの文。どちらかがない指標はその向きでは出さない。
 * ほかの考察（昼夜間人口比率・年齢構成・一人暮らしなど）がすでに扱う指標と向きは、ここには入れない。
 * 地域や住む人を悪く言うように読める文（犯罪が多い、所得や学歴が低い、寿命が短いなど）は作らない。
 * highTone・lowTone は文の印象（pos: 地域の良いところ、neg: 課題）。ネガティブな文だけのページにしないために使う。
 */
export type Tone = "pos" | "neg";
/**
 * 見出し（特徴を一言で表す文）に使う言い回し。renyou は文の途中（「雪が多く、」）、rentai は「まち」の前（「雪の多い」）。
 * key が同じ言い回しは見出しに2つ並べない。
 * plain は、多くの地域に当てはまり、それだけではまちの特徴が伝わりにくい言い回し（「長生きの人が多い」「車が暮らしの足となる」など）。
 * 見出しでは、ほかに目立つ特徴があればそちらを先にする（設計変更記録 #167）
 */
export interface Tag { key: string; renyou: string; rentai: string; plain?: boolean }
export const tag = (key: string, renyou: string, rentai: string, plain = false): Tag => ({ key, renyou, rentai, ...(plain ? { plain } : {}) });
/**
 * 全国の順位がとても高いときの見出しの言い回し（「製造品出荷額が全国3位の」）。言葉で「盛ん」と書くより、
 * データで言えることをそのまま書く（設計変更記録 #167）
 */
export const rankTag = (t: Tag, title: string, rank: number): Tag => tag(t.key, `${title}が全国${rank}位で`, `${title}が全国${rank}位の`);

export interface RankTemplate {
  high?: string;
  low?: string;
  highTone?: Tone;
  lowTone?: Tone;
  highTag?: Tag;
  lowTag?: Tag;
  /** 全国の順位が特に高いとき、見出しに順位を書くための指標の短い名前（highTag の代わりに rankTag で使う。設計変更記録 #167） */
  title?: string;
  /** low の文は、この指標が全国の上位（top の割合まで）に入る市区町村だけに付ける（文の理由が当てはまる地域に限るため） */
  lowWhen?: { id: string; top: number };
  /** 値の少ない地域を除くために見る件数・人数の指標と、その最小値 */
  minCountOf?: string;
  minCount?: number;
  /**
   * 数え方の癖（指標の注意点のうち、順位の読み方に関わるもの）。考察の文に続けて添える（設計変更記録 #163）。
   * 都道府県のページにも添えるときは、「まち」でなく「地域」と書く
   */
  note?: string;
  /** note を添える向き（省くとどちらにも添える） */
  noteOn?: "high" | "low";
}

/** 学級の人数（小学校・中学校）の数え方の癖 */
const CLASS_NOTE = "学校のある場所で数え、2つの学年をまとめた学級も含むため、小さな学校の多い地域で少なく出ます。";
/** 農業産出額の数え方の癖 */
const AGRI_NOTE = "市町村の値は、県の産出額を作付面積や家畜の頭数などで割り振った推計値です。";
/** 比例代表の得票率（政党ごとに同じ文） */
const VOTE: RankTemplate = { high: "この政党への支持が厚い地域のようです。", note: "1回の選挙の結果なので、そのときの情勢にも左右されます。" };

export const RANK_TEMPLATES: Record<string, RankTemplate> = {
  // 人口・世帯・住まい
  population_density: { lowTag: tag("density", "山林や農地が広がり", "山林や農地の広がる"), highTag: tag("density", "建物が建ち並び", "建物が建ち並ぶ"), title: "人口密度",
    high: "建物が密集した、全国でも有数の都市部と考えられます。",
    low: "山林や農地が広く、家がまばらに点在するまちと考えられます。",
    note: "公園や河川、山林なども含めた面積で割った値なので、住宅地の混み具合とは違うことがあります。",
  },
  persons_per_household: { lowTag: tag("small", "小さな世帯が多く", "小さな世帯の多い", true), low: "一人暮らしや二人暮らしの小さな世帯が中心のようです。" },
  households_with_children_share: { highTag: tag("kids", "子育て中の家族が多く", "子育て中の家族の多い"),
    high: "子育て中の家族が多く住む地域と思われます。",
    highTone: "pos",
    low: "子育てを終えた世帯や単身の世帯が多いようです。",
  },
  owner_occupied_share: { lowTag: tag("rent", "借家に住む人が多く", "借家に住む人の多い", true), low: "借家や賃貸マンションに住む人が多く、人の入れ替わりが多い地域のようです。" },
  high_rise_household_share: { highTag: tag("highrise", "高層の住宅が多く", "高層の住宅が建ち並ぶ"), title: "高層住宅に住む世帯の割合", high: "タワーマンションなど高層の住宅が多く建つ地域と思われます。" },
  same_residence_5y_share: { lowTag: tag("new", "新しく住み始める人が多く", "新しく住み始める人の多い"), highTag: tag("settled", "長く住み続ける人が多く", "長く住み続ける人の多い", true),
    high: "引っ越す人が少なく、長く住み続ける人の多い落ち着いた地域と考えられます。",
    highTone: "pos",
    low: "転入・転出が多く、新しく住み始める人の多い地域のようです。",
  },
  residence_under1y_share: { highTag: tag("new", "新しい住民が多く", "新しい住民の多い"), high: "この1年で移り住んだ人が多く、新しい住民が次々に加わる地域のようです。" },
  // 仕事・学び
  self_employed_share: { highTag: tag("selfemp", "自分で事業をする人が多く", "自分で事業をする人の多い"),
    high: "農家や商店、職人など、自分で事業をしている人が多い地域と思われます。",
    low: "会社や役所などに勤める人が中心の地域のようです。",
  },
  professional_share: { highTag: tag("pro", "専門的な仕事の人が多く", "専門的な仕事の人の多い"), high: "研究所や病院、IT 企業など、専門的な仕事をする人が多く住んでいると考えられます。" },
  manager_share: { high: "会社の役員や管理職の人が多く住む地域と思われます。" },
  commute_walk_share: { highTag: tag("walk", "歩いて通う人が多く", "歩いて通う人の多い"), title: "歩いて通う人の割合", high: "職場や学校が住まいの近くにあり、歩いて通える暮らしのようです。", highTone: "pos" },
  commute_bicycle_share: { highTag: tag("bicycle", "自転車で通う人が多く", "自転車で通う人の多い"), title: "自転車で通う人の割合", high: "平らな土地が多く、自転車で通勤・通学しやすいまちと考えられます。" },
  commute_bus_share: { highTag: tag("bus", "路線バスで通う人が多く", "路線バスで通う人の多い"), title: "バスで通う人の割合", high: "鉄道より路線バスが通勤・通学の足になっている地域のようです。" },
  commute_car_share: { lowTag: tag("transit", "車を使わずに通う人が多く", "車を使わずに通う人の多い"), low: "車を使わずに通勤・通学できる、公共交通の便利な地域と思われます。", lowTone: "pos" },
  university_graduate_share: { highTag: tag("univ", "大学を出た人が多く", "大学を出た人の多い"), high: "大学を出た人が多く住む地域と考えられます。" },
  preschool_kindergarten_share: { highTag: tag("kinder", "幼稚園に通う子が多く", "幼稚園に通う子の多い", true), high: "小学校に入る前は幼稚園に通うのが一般的な地域のようです。" },
  preschool_nursery_share: { highTag: tag("nursery", "保育園に通う子が多く", "保育園に通う子の多い", true), high: "共働きの家庭が多く、保育園を使う家庭が多いと考えられます。" },
  preschool_kodomoen_share: { high: "幼稚園や保育園の認定こども園への切り替えが進んだ地域のようです。" },
  jhs_students_private: { high: "私立中学校に通う子どもが多く、中学受験が盛んな地域と思われます。",
    note: "学校のある場所で数えるため、私立中学校のある地域では、ほかの地域から通う生徒の分だけ高くなります。" },
  // 学級の人数は学校の大きさや子どもの多さではなく、学年の児童を何学級に分けるか（学級編制）で決まる
  elem_class_size: { lowTag: tag("small_class", "少人数の学級が多く", "少人数の学級が多い", true),
    high: "1つの学級の児童が多く、上限（小学校は35人）に近い人数で学級を編制している学校が多いと考えられます。",
    low: "1つの学級の児童が少なく、先生の目が一人ひとりに届きやすい環境と考えられます。",
    note: CLASS_NOTE, noteOn: "low",
  },
  hs_grad_vocational_rate: { high: "まちにある高校では、専門学校で資格や技術を身につける進路を選ぶ人が多いようです。" },
  // 暮らし・健康
  total_fertility_rate: { highTag: tag("kids", "子どもの多い家庭が目立ち", "子どもの多い家庭が目立つ"), title: "出生率",
    high: "子どもを多く持つ家庭が多い地域と考えられます。",
    highTone: "pos",
    low: "若い単身の人が多い都市部などで低くなりやすく、その影響があると考えられます。",
    lowTone: "neg",
    // 「都市部などで低くなりやすい」は人口密度の高い市区町村だけに書く（山あいの町村などには当てはまらないため）
    lowWhen: { id: "population_density", top: 0.25 },
    note: "5年間の出生をまとめ、周りの地域の状況も使って推定した値です。",
  },
  life_expectancy_male: { highTag: tag("long", "長生きの人が多く", "長生きの人が多い", true), title: "男性の平均寿命", high: "健康で長生きの男性が多い地域のようです。", highTone: "pos",
    note: "国勢調査の年の前後の死亡の状況から計算した値で、住む人の実際の寿命の平均ではありません。" },
  life_expectancy_female: { highTag: tag("long", "長生きの人が多く", "長生きの人が多い", true), title: "女性の平均寿命", high: "健康で長生きの女性が多い地域のようです。", highTone: "pos",
    note: "国勢調査の年の前後の死亡の状況から計算した値で、住む人の実際の寿命の平均ではありません。" },
  taxable_income_per_taxpayer: { high: "所得の高い人が多く住む地域と考えられます。",
    note: "株式の売却益なども含むため、所得のとても大きい一部の人で値が大きく変わることがあります。" },
  income_levy_taxpayer_share: { high: "働いて所得を得ている人の割合が高い、現役世代の多い地域と思われます。" },
  vacant_house_rate: { lowTag: tag("demand", "住まいの需要が高く", "住まいの需要が高い", true), low: "空き家が少なく、住まいの需要が高い地域のようです。", lowTone: "pos",
    note: "標本調査の推計値で、入居者を募集中の賃貸住宅や別荘も空き家に含みます。" },
  // 安全（犯罪・事故が多い方は、住む人が悪く見られかねないので文にしない。少ない方だけ。設計変更記録 #133）
  traffic_accidents_per_100_residents: { lowTag: tag("calm", "交通事故が少なく", "交通事故の少ない", true),
    low: "住民の数に比べて事故が少ない、落ち着いた地域のようです。",
    lowTone: "pos",
  },
  street_crime_total_per_100_residents: { lowTag: tag("calm", "犯罪の件数が少なく", "落ち着いた", true), low: "住民の数に比べて件数が少ない、落ち着いた地域のようです。", lowTone: "pos" },
  residence_20y_share: { highTag: tag("settled", "長く住み続ける人が多く", "長く住み続ける人の多い", true),
    high: "20年以上住み続けている人が多く、地域に根づいた暮らしが続いていると考えられます。", highTone: "pos" },
  residence_under5y_share: { high: "この5年の間に移り住んだ人が多く、新しい住民が加わり続けている地域のようです。" },
  jhs_class_size: {
    high: "1つの学級の生徒が多く、上限に近い人数で学級を編制している学校が多いと考えられます。",
    low: "1つの学級の生徒が少なく、先生の目が一人ひとりに届きやすい環境と考えられます。",
    note: CLASS_NOTE, noteOn: "low",
  },
  childcare_usage_rate: { high: "保育サービスを使う家庭が多く、共働きの子育て世帯が多いと考えられます。" },
  voter_turnout: { high: "選挙への関心が高い地域のようです。", highTone: "pos" },
  // 観光（外国人の宿泊者。住む人ではなく、泊まった人の数）
  inbound_guest_nights: { highTag: tag("tourism", "海外からの旅行者が多く訪れ", "海外からの旅行者が訪れる"), title: "外国人の宿泊者数",
    high: "海外からの旅行者が多く泊まる、全国でも有数の観光地と考えられます。", highTone: "pos",
    note: "ホテルや旅館などに泊まった延べの人数で、日帰りで訪れた人は含みません。" },
  inbound_guest_share: { highTag: tag("tourism", "海外からの旅行者に人気で", "海外からの旅行者に人気の"),
    high: "泊まる人のうち海外からの旅行者の割合が高く、海外で知られた観光地のようです。", highTone: "pos" },
  // 産業（規模の大きさがそのまま出る件数・金額は、上位だけを見る）
  agri_output_rice: { highTag: tag("agri", "米づくりが盛んで", "米どころの"), title: "米の産出額", high: "全国有数の米どころと思われます。", highTone: "pos", note: AGRI_NOTE },
  agri_output_vegetables: { highTag: tag("agri", "野菜づくりが盛んで", "野菜づくりの盛んな"), title: "野菜の産出額", high: "全国有数の野菜の産地と思われます。", highTone: "pos", note: AGRI_NOTE },
  agri_output_fruits: { highTag: tag("agri", "果物づくりが盛んで", "果物の産地の"), title: "果物の産出額", high: "果物の産地として知られる地域と考えられます。", highTone: "pos", note: AGRI_NOTE },
  agri_output_livestock: { highTag: tag("agri", "畜産が盛んで", "畜産の盛んな"), title: "畜産の産出額", high: "牛や豚、鶏などの畜産が盛んな地域と思われます。", highTone: "pos", note: AGRI_NOTE },
  manufacturing_shipments: { highTag: tag("mfg", "ものづくりが盛んで", "ものづくりの盛んな"), title: "製造品出荷額", high: "大きな工場が集まる、全国有数のものづくりの拠点と考えられます。", highTone: "pos",
    note: "工場のある場所で数えるため、大きな工場が1つあるだけでも大きくなります。" },
  // 卸売に限らず、企業の拠点としての役割として読む（運営者の指摘。設計変更記録 #163）
  wholesale_sales: { highTag: tag("commerce", "企業や問屋が集まり", "企業や問屋の集まる"), title: "卸売業の販売額", high: "企業の本社や支店、問屋が集まる、ビジネスの拠点と考えられます。", highTone: "pos",
    note: "本社でまとめて販売額を計上する会社が多いため、本社や支店の集まる都市で大きくなりやすい値です。" },
  // 選挙（値が大きいときだけ）
  vote_share_ldp: VOTE,
  vote_share_cdp: VOTE,
  vote_share_komeito: VOTE,
  vote_share_ishin: VOTE,
  vote_share_dpfp: VOTE,
  vote_share_jcp: VOTE,
  vote_share_reiwa: VOTE,
  vote_share_sanseito: VOTE,
  vote_share_sdp: VOTE,
  vote_share_hoshu: VOTE,
  vote_share_mirai: VOTE,
  vote_share_chudo: VOTE,
};

/** 国勢調査の国籍別の外国人の割合（census_foreign_<国>_share）。人数が少ない地域は除く */
export function nationalityTemplate(id: string, indicatorName: string): RankTemplate | null {
  const m = id.match(/^census_foreign_(\w+)_share$/);
  if (!m) return null;
  const country = indicatorName.match(/（([^（）]+)）$/)?.[1];
  if (!country) return null;
  return {
    high: `${country}の人が比較的多く暮らしている地域のようです。`,
    minCountOf: `census_foreign_${m[1]}`,
    minCount: 20,
  };
}
