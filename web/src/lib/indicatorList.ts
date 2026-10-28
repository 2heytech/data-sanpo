// トップページの指標の一覧（ジャンルごとのカードに指標名を並べる。設計変更記録 #47・#173）。
// 指標を「項目」（名前のボタン1つ）にまとめる。種類が2つ以上ある項目は、押すと種類ごとのリンクが開く
import type { Indicator } from "./types";

export interface ItemLink {
  label: string;
  href: string;
  /** 同じ種類の、基準だけが違う指標（割合・住民100人当たりなど） */
  extras: { label: string; href: string }[];
}
export interface ListItem {
  title: string;
  href: string;
  description: string;
  /** 1つなら名前のボタンがそのままリンク、2つ以上なら種類ごとのリンクを開く */
  members: ItemLink[];
  /** 項目に含まれる指標（範囲の札を付けるのに使う） */
  ids: string[];
}
export interface ListTag { kind: "area" | "pref" | "point"; text: string }

interface IndicatorGroup {
  title: string;
  description: string;
  /** 代表（件数・人数など）の指標の id と、開いたときの種類の名前 */
  ids?: string[];
  labels?: string[];
  /** family で選ぶときは、種別（facets.type）が種類の名前になる */
  family?: string;
  exceptTypes?: string[];
}

// 種類だけが違う指標を1つの項目にまとめる組。公開版に2つ以上あるときだけまとめる
export const INDICATOR_GROUPS: IndicatorGroup[] = [
  { title: "住まいの種類別の世帯の割合", ids: ["owner_occupied_share", "private_rented_share", "high_rise_household_share"],
    labels: ["持ち家", "民営の借家", "11階建以上の共同住宅"],
    description: "住宅に住む世帯のうち、持ち家・民営の借家・11階建以上の共同住宅に住む世帯の割合。" },
  { title: "今の場所に住んでいる期間", ids: ["same_residence_5y_share", "residence_under1y_share", "residence_under5y_share", "residence_20y_share"],
    labels: ["5年前と同じ場所", "1年未満", "5年未満", "20年以上"],
    description: "今の住居に住み始めてからの年数ごとの人の割合。短い人が多いほど、人の入れ替わりが多い地域。" },
  { title: "国勢調査の外国人の数（国籍別）", family: "census_foreign", exceptTypes: ["総数"],
    description: "国勢調査で数えた外国人の数（各回10月1日現在）を国籍別に。人口に占める割合も見られます。" },
  { title: "外国人住民の数（国籍別）", family: "foreign", exceptTypes: ["総数"],
    description: "住民基本台帳に記録されている外国人の数（各年1月1日現在）を、東京都の区市町村について国籍・地域別に。" },
  { title: "小学校入学前の子どもの通い先",
    ids: ["preschool_kindergarten_share", "preschool_nursery_share", "preschool_kodomoen_share"],
    labels: ["幼稚園", "保育園・保育所", "認定こども園"],
    description: "小学校に入る前の子どものうち、幼稚園・保育園・認定こども園に通う子どもの割合。" },
  { title: "1学級あたりの人数", ids: ["elem_class_size", "jhs_class_size"], labels: ["小学校", "中学校"],
    description: "公立の小学校・中学校の1学級あたりの児童・生徒数。" },
  { title: "特別支援学級の子どもの割合", ids: ["elem_special_class_share", "jhs_special_class_share"], labels: ["小学校", "中学校"],
    description: "公立の小学校・中学校の児童・生徒のうち、特別支援学級に在籍する子どもの割合。" },
  { title: "高校卒業者の進路", ids: ["hs_grad_university_rate", "hs_grad_vocational_rate", "hs_grad_employment_rate"],
    labels: ["大学等", "専門学校", "就職"],
    description: "高校を卒業した人のうち、大学等・専門学校に進んだ人と、就職した人の割合。" },
  { title: "犯罪の認知件数（罪種別）", family: "crime",
    description: "警察が把握した刑法犯の件数を罪種別に。住民100人当たり・昼間人口100人当たりも見られます。" },
  { title: "犯罪の認知件数（都道府県別）", ids: ["crime_npa_total", "crime_npa_theft", "crime_npa_serious"],
    labels: ["刑法犯の総数", "窃盗犯", "重要犯罪"],
    description: "警察庁の犯罪統計による、都道府県ごとの刑法犯の認知件数。住民100人当たりも見られます。" },
  { title: "窃盗の手口別の認知件数",
    ids: ["street_crime_total", "street_crime_bicycle", "street_crime_motorcycle", "street_crime_car", "street_crime_car_break_in",
      "street_crime_parts", "street_crime_vending", "street_crime_snatch"],
    labels: ["7手口の合計", "自転車盗", "オートバイ盗", "自動車盗", "車上ねらい", "部品ねらい", "自動販売機ねらい", "ひったくり"],
    description: "街頭で起きやすい窃盗7手口の認知件数。住民100人当たりも見られます。" },
  { title: "交通事故の件数（種類別）",
    ids: ["traffic_accidents", "traffic_accidents_pedestrian", "traffic_accidents_bicycle", "traffic_accidents_fatal"],
    labels: ["全体", "歩行者が関係", "自転車が関係", "死亡事故"],
    description: "人身事故の件数を種類別に。住民100人当たり・昼間人口100人当たりも見られます。" },
  { title: "世帯年収の割合", ids: ["household_income_under300_share", "household_income_1000plus_share"],
    labels: ["300万円未満", "1000万円以上"],
    description: "世帯のうち、年収が300万円未満・1000万円以上の世帯の割合。" },
  { title: "住民1人あたりの財政",
    ids: ["expenditure_per_capita", "local_tax_per_capita", "local_debt_per_capita", "reserve_fund_per_capita"],
    labels: ["歳出額", "市区町村税の収入", "地方債の残高", "積立金の残高"],
    description: "市区町村の歳出・税の収入・地方債の残高・積立金の残高を、住民1人あたりにした額。" },
  { title: "農業産出額（品目別）", ids: ["agri_output", "agri_output_rice", "agri_output_vegetables", "agri_output_fruits", "agri_output_livestock"],
    labels: ["合計", "米", "野菜", "果実", "畜産"],
    description: "農業で生み出された農産物の額を、品目別に。" },
  { title: "土地利用の割合（1976年から）", ids: ["land_use_building_share", "land_use_paddy_share", "land_use_field_share", "land_use_forest_share"],
    labels: ["建物用地", "田", "畑など", "森林"],
    description: "土地のうち、建物用地・田・畑など・森林が占める割合。1976年からの変化を追えます。" },
  { title: "まちなかの土地の使われ方",
    ids: ["urban_high_rise_share", "urban_dense_low_rise_share", "urban_factory_share", "urban_park_share"],
    labels: ["高層建物", "低層の住宅の密集", "工場", "公園・緑地"],
    description: "土地のうち、高層建物・低層の住宅が密集した土地・工場・公園や緑地が占める割合。" },
  { title: "農地の区画", ids: ["farmland_paddy_share", "farmland_field_share", "farmland_parcel_area"],
    labels: ["田の区画", "畑の区画", "1区画の平均面積"],
    description: "農地の区画から見た、田・畑の割合と1区画の平均の広さ。" },
  { title: "森林の種類", ids: ["vegetation_natural_forest_share", "vegetation_secondary_forest_share", "vegetation_plantation_share", "vegetation_bamboo_share"],
    labels: ["自然林", "二次林", "植林地", "竹林"],
    description: "土地のうち、自然林・二次林・植林地・竹林が占める割合。" },
  { title: "延べ宿泊者数", ids: ["guest_nights", "guest_nights_japanese", "inbound_guest_nights", "guest_outside_share"],
    labels: ["合計", "日本人", "外国人", "県外からの割合"],
    description: "ホテル・旅館などに泊まった人の延べ人数。日本人・外国人別と、県外から来た人の割合も見られます。" },
  { title: "施設タイプ別の延べ宿泊者数",
    ids: ["guest_nights_ryokan", "guest_nights_resort_hotel", "guest_nights_business_hotel", "guest_nights_city_hotel", "guest_nights_simple_lodging"],
    labels: ["旅館", "リゾートホテル", "ビジネスホテル", "シティホテル", "簡易宿所"],
    description: "旅館・ホテルなど、施設のタイプごとの延べ宿泊者数。" },
  { title: "宿泊業の事業所と働く人", ids: ["accommodation_establishments", "accommodation_employees", "ryokan_hotels", "simple_lodgings"],
    labels: ["宿泊業の事業所", "宿泊業で働く人", "旅館・ホテル", "簡易宿所"],
    description: "宿泊業の事業所の数と働く人の数、旅館・ホテルと簡易宿所の数。" },
  { title: "文化財の数（種類別）",
    ids: ["important_cultural_buildings", "registered_cultural_buildings", "historic_sites", "scenic_places", "natural_monuments", "preservation_districts"],
    labels: ["国宝・重要文化財（建造物）", "登録有形文化財（建造物）", "史跡", "名勝", "天然記念物", "重要伝統的建造物群保存地区"],
    description: "国が指定・登録した文化財の数を、種類別に。" },
];

// 種別・基準で切り替える指標（犯罪・交通事故など）は、基準（件数・100人当たり）の違いを1つの項目にまとめる
const COUNT_BASES = new Set(["件数", "人数", "割合"]);
// 種別だけが違い基準が1つの組（政党別の得票率・教科別の学力テストなど）は、種別も1つの項目にまとめる。
// 名前が「共通の名前（種別）」の形の組だけが対象（住民税と課税対象所得のような組は分ける）
export const groupName = (i: Indicator) => i.name.replace(/（[^（）]*）$/, "");
function groupable(members: Indicator[]): boolean {
  const name = groupName(members[0]);
  return new Set(members.map((m) => m.facets!.type)).size >= 2 &&
    new Set(members.map((m) => m.facets!.basis)).size === 1 &&
    members.every((m) => m.name === name || m.name === `${name}（${m.facets!.type}）`);
}
// 種別をまとめた項目の説明。ないときは「総数」など組の名前そのものの指標の説明を使う
const FAMILY_DESCRIPTIONS: Record<string, string> = {
  vote_share: "衆議院・参議院の比例代表選挙で、有効投票のうち各政党が得た票の割合。",
  zairyu_foreign: "在留外国人統計による、市区町村ごとの国籍・地域別の在留外国人の数（各年12月末現在）。",
  gakuryoku: "全国学力・学習状況調査の平均正答率（小学6年生の国語・算数、中学3年生の国語・数学）。その都道府県の公立学校の児童・生徒の結果。",
  commute: "その地域に住む15歳以上の通勤者・通学者のうち、ふだんの通勤・通学にそれぞれの交通手段を使う人の割合。",
  jhs_progress: "市区町村の公立小学校を卒業した子どもの進学先（公立・都内の私立・都内の国立・都外の中学校等）の割合。",
  street_trees: "都道沿いに植えられている街路樹（高木・中木）の本数。総数と、主な樹種ごとの本数。",
};

interface Row { main: Indicator; variants: Indicator[]; grouped?: boolean }
function rowsOf(list: Indicator[]): Row[] {
  const rows: Row[] = [];
  for (const ind of list) {
    if (!ind.family || !ind.facets) {
      rows.push({ main: ind, variants: [] });
      continue;
    }
    const members = list.filter((o) => o.family === ind.family);
    if (groupable(members)) {
      if (members[0] === ind) rows.push({ main: ind, variants: members, grouped: true });
      continue;
    }
    // 同じ種別の指標のうち、件数・人数・割合の基準のもの（なければ最初のもの）を項目の代表にする
    const same = list.filter((o) => o.family === ind.family && o.facets?.type === ind.facets!.type);
    const main = same.find((o) => COUNT_BASES.has(o.facets!.basis)) ?? same[0];
    if (main !== ind) continue;
    rows.push({ main, variants: same.filter((o) => o !== main) });
  }
  return rows;
}

const href = (i: Indicator) => `/indicators/${i.id}/`;
const basisLabel = (i: Indicator) => i.facets?.basis.replace("あたり", "当たり") ?? i.name;
const extrasOf = (r: Row) => r.variants.map((v) => ({ label: basisLabel(v), href: href(v) }));
const idsOf = (r: Row) => [r.main.id, ...r.variants.filter((v) => v !== r.main).map((v) => v.id)];

function inGroup(g: IndicatorGroup, ind: Indicator): boolean {
  if (g.ids) return g.ids.includes(ind.id);
  return !!g.family && ind.family === g.family && !(g.exceptTypes ?? []).includes(ind.facets?.type ?? "");
}

function rowItem(r: Row): ListItem {
  if (r.grouped) {
    const total = r.variants.find((m) => m.name === groupName(r.main));
    return {
      title: groupName(r.main), href: href(r.variants[0]),
      description: FAMILY_DESCRIPTIONS[r.main.family!] ?? (total ?? r.main).description,
      members: r.variants.map((v) => ({ label: v.facets!.type, href: href(v), extras: [] })),
      ids: r.variants.map((v) => v.id),
    };
  }
  return {
    title: r.main.name, href: href(r.main), description: r.main.description,
    members: [{ label: r.main.name, href: href(r.main), extras: extrasOf(r) }], ids: idsOf(r),
  };
}

/** あるカテゴリの指標を、一覧の項目の並びにする（指標の並びは indicators.json の順） */
export function listItems(indicators: Indicator[], category: string): ListItem[] {
  const rows = rowsOf(indicators.filter((i) => i.category === category));
  const groupOf = new Map<Row, IndicatorGroup>();
  for (const g of INDICATOR_GROUPS) {
    const members = rows.filter((r) => !r.grouped && inGroup(g, r.main));
    if (members.length >= 2) members.forEach((r) => groupOf.set(r, g));
  }
  const items: ListItem[] = [];
  const done = new Set<IndicatorGroup>();
  for (const r of rows) {
    const g = groupOf.get(r);
    if (!g) {
      items.push(rowItem(r));
      continue;
    }
    if (done.has(g)) continue;
    done.add(g);
    const members = rows.filter((x) => groupOf.get(x) === g);
    if (g.ids) members.sort((a, b) => g.ids!.indexOf(a.main.id) - g.ids!.indexOf(b.main.id));
    items.push({
      title: g.title, href: href(members[0].main), description: g.description,
      members: members.map((m) => ({
        label: g.ids ? g.labels![g.ids.indexOf(m.main.id)] : m.main.facets!.type, href: href(m.main), extras: extrasOf(m),
      })),
      ids: members.flatMap(idsOf),
    });
  }
  return items;
}

/**
 * 項目の範囲の札。一部の都道府県だけの指標は「東京都」「41都道府県」、都道府県別の値だけの指標は「県別」。
 * 項目のすべての指標が当てはまるときだけ付ける（prefectureCount は公開版の都道府県の数）
 */
export function listTags(item: ListItem, byId: Map<string, Indicator>, prefectureCount: number,
  prefectureName: (code: string) => string): ListTag[] {
  const inds = item.ids.map((id) => byId.get(id)).filter((i): i is Indicator => !!i);
  if (!inds.length) return [];
  const tags: ListTag[] = [];
  const coverage = (i: Indicator) => i.prefectures ?? [];
  const partial = (i: Indicator) => coverage(i).length > 0 && coverage(i).length < prefectureCount;
  if (prefectureCount > 1 && inds.every(partial)) {
    const keys = new Set(inds.map((i) => coverage(i).join(",")));
    const first = coverage(inds[0]);
    tags.push({ kind: "area", text: keys.size > 1 ? "一部の都道府県" : first.length === 1 ? prefectureName(first[0]) : `${first.length}都道府県` });
  }
  if (inds.every((i) => i.periods.every((p) => p.levels.length === 1 && p.levels[0] === "prefecture"))) {
    tags.push({ kind: "pref", text: "県別" });
  }
  return tags;
}
