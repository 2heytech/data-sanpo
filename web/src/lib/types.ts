// 公開ファイル（pipeline/tdm/export.py が生成）の型

export type Status =
  | "observed"
  | "estimated"
  | "derived"
  | "missing"
  | "suppressed"
  | "withheld"
  | "not_applicable";

export type Level = "prefecture" | "municipality" | "small_area";

export interface Period {
  period: string;
  period_end: string;
  period_kind: "point" | "calendar_year" | "fiscal_year" | "month_to_date" | "multi_year";
  /** 複数年の合計（例: 犯罪の直近5年合計）。時点のスライドバーには並べない。 */
  aggregate?: boolean;
  label: string;
  levels: Level[];
  boundary_version: string;
  source_ids: string[];
}

export interface Indicator {
  id: string;
  name: string;
  category: string;
  unit: string;
  kind: "count" | "ratio" | "density" | "change";
  digits: number;
  definition_version: string;
  description: string;
  method: string;
  caveats: string[];
  min_denominator: number | null;
  /** 率の倍率（分子 ÷ 分母 × scale。% なら 100） */
  scale?: number;
  /** zero_blank: 値が0の地域は色を塗らない（犯罪の件数など） */
  /** band: 区分で公表された値（就学援助率の「10%未満」など）の区分の幅。値は区分の上の端 */
  legend: { method: string; classes: number; scheme: string; zero_blank?: boolean; band?: number };
  /** 率の内訳に添える単位（分子, 分母）。省略時は ["人", "人"]。 */
  fraction_units?: [string, string] | null;
  /** 地域の情報に並べて表示する指標（例: 住民当たりと昼間人口当たりの犯罪件数）。 */
  compare_with?: string[] | null;
  /** 画面で1つの指標にまとめる組（例: "crime"）と、その中での切り替え項目（種別 type・基準 basis）。 */
  family?: string | null;
  /** 値のある都道府県のコード（東京都の機関のデータは ["13"] だけ） */
  prefectures?: string[];
  facets?: Record<string, string> | null;
  periods: Period[];
  default_period: string;
}

export interface IndicatorCatalog {
  schema_version: string;
  release_id: string;
  indicators: Indicator[];
}

export interface Municipality {
  id: string;
  name: string;
  /** 都道府県コード2桁 */
  prefecture: string;
  /** 東京都は 区部・多摩・島しょ、政令指定都市の区は市の名前、それ以外は null */
  region: string | null;
  bbox: [number, number, number, number];
  center: [number, number];
  neighbors: string[];
  small_area_count: number;
}

export interface Prefecture {
  id: string;
  code: string;
  name: string;
  bbox: [number, number, number, number];
  /** 地名を置く位置（都道府県の内側の代表点） */
  center: [number, number];
  municipality_count: number;
}

export interface AreasFile {
  schema_version: string;
  release_id: string;
  boundary_version: string;
  prefectures: Prefecture[];
  municipalities: Municipality[];
}

export interface SmallArea {
  id: string;
  name: string;
  bbox: [number, number, number, number];
  center: [number, number];
}

/** 区市町村ごとの町丁・字等の境界（boundaries/<版>/<区市町村コード>.geojson）。名前・範囲・代表点も持つ */
export interface SmallAreasFile {
  type: "FeatureCollection";
  municipality_id: string;
  features: { type: "Feature"; properties: SmallArea; geometry: unknown }[];
}

export interface ValueRow {
  entity_id: string;
  value: number | null;
  status: Status;
  numerator?: number;
  denominator?: number;
  note?: string;
  /** 町丁・字等の全国での順位（書き出し時に数える。母数は legend の small_area.count） */
  national_rank?: number;
}

export interface ValuesFile {
  indicator_id: string;
  period: string;
  level: Level;
  unit: string;
  boundary_version: string;
  rows: ValueRow[];
}

export interface LegendLevel {
  /** 区切り（全国で共通。市区町村・町丁目は最大20区分、#145） */
  breaks: number[];
  min: number | null;
  max: number | null;
  count: number;
}

export interface LegendFile {
  indicator_id: string;
  period: string;
  method: string;
  scheme: string;
  zero_blank?: boolean;
  levels: Partial<Record<Level, LegendLevel>>;
}

export interface Source {
  source_id: string;
  dataset_key: string;
  title: string;
  provider: string;
  url: string | null;
  license: string;
  license_url: string | null;
  attribution: string;
  modification_note: string | null;
  published_at: string | null;
  retrieved_at: string;
  file_sha256: string;
}

export interface SearchIndex {
  fields: ["id", "name", "context", "level"];
  entries: [string, string, string, Level][];
}

export interface ReleaseInfo {
  release_id: string;
  created_at: string;
  is_fixture: boolean;
  /** 都道府県を絞って作ったプレビュー */
  is_partial: boolean;
}

/** places/<指標>.json の都道府県ごとの件数と範囲（西・南・東・北）。location_only は値がなく位置だけの点の数 */
export interface PlacePrefecture {
  count: number;
  bbox: [number, number, number, number] | null;
  location_only?: number;
}

/** places/station_passengers.json（駅の点）。values・status は periods と同じ順 */
export interface Station {
  id: string;
  name: string;
  operator: string;
  group: string;
  lines: string[];
  municipality_id: string;
  coord: [number, number];
  values: (number | null)[];
  status: (Status | null)[];
  notes?: Record<string, string>;
  by_line?: Record<string, (number | null)[]>;
}

export interface StationsFile {
  schema_version: string;
  release_id: string;
  indicator_id: string;
  name: string;
  unit: string;
  description: string;
  method: string;
  caveats: string[];
  periods: { period: string; period_end: string; period_kind: string; label: string }[];
  source_ids: string[];
  /** 都道府県ごとの件数と範囲。点の一覧は places/<指標>/<都道府県>.json（#71） */
  prefectures?: Record<string, PlacePrefecture>;
  /** 古い公開版（1ファイルに全件）の一覧 */
  stations?: Station[];
}

export interface School {
  id: string;
  name: string;
  school_type: "elementary" | "junior_high" | "compulsory";
  type_label: string;
  founder: string;
  address: string | null;
  municipality_id: string;
  coord: [number, number] | null;
  precision: "街区" | "町丁目" | null;
  values: (number | null)[];
  status: (Status | null)[];
  by_grade?: Record<string, (number | null)[]>;
  /** 学校ごとの出典（人数の出典、位置の出典の順）。年度は出典ごとに違う（#138） */
  sources?: string[];
  /** 出典の最新の年度の一覧にない（閉校・統合など） */
  closed?: boolean;
  /** 児童・生徒数の公開データがなく、位置だけ（国土数値情報 学校データ） */
  location_only?: boolean;
  as_of?: string | null;
  /** 人数の一覧がある市区町村なのに、その一覧に見つからなかった学校（休校・閉校、名前の違いなど） */
  unlisted?: { year: number; source_id: string };
}

export interface SchoolsFile {
  schema_version: string;
  release_id: string;
  indicator_id: string;
  name: string;
  unit: string;
  description: string;
  method: string;
  caveats: string[];
  periods: { period: string; period_end: string; period_kind: string; label: string }[];
  source_ids: string[];
  /** 都道府県ごとの件数と範囲。点の一覧は places/<指標>/<都道府県>.json（#71） */
  prefectures?: Record<string, PlacePrefecture>;
  /** 古い公開版（1ファイルに全件）の一覧 */
  schools?: School[];
}

export interface LandPoint {
  id: string;
  name: string;
  municipality_id: string;
  coord: [number, number];
  use: string;
  use_label: string;
  address: string | null;
  residential_address: string | null;
  area_m2: number | null;
  current_use: string | null;
  station: string | null;
  station_distance_m: number | null;
  zoning: string | null;
  change_rate: number | null;
  values: (number | null)[];
}

export interface LandPriceFile {
  schema_version: string;
  release_id: string;
  indicator_id: string;
  name: string;
  unit: string;
  description: string;
  method: string;
  caveats: string[];
  periods: { period: string; period_end: string; period_kind: string; label: string }[];
  source_ids: string[];
  /** 都道府県ごとの件数と範囲。点の一覧は places/<指標>/<都道府県>.json（#71） */
  prefectures?: Record<string, PlacePrefecture>;
  /** 古い公開版（1ファイルに全件）の一覧 */
  points?: LandPoint[];
}

export interface NurseryPoint {
  id: string;
  name: string;
  municipality_id: string;
  /** 認可保育所・認定こども園・小規模保育・事業所内保育（#138） */
  facility_type?: string;
  /** 認可定員（東京都の一覧）か利用定員（ここdeサーチ） */
  capacity_kind?: string;
  founder: string;
  address: string | null;
  coord: [number, number] | null;
  precision: string | null;
  values: (number | null)[];
  /** 値のある時点（定員を公表していない施設は "missing"）。施設ごとに時点が違う */
  status?: (Status | null)[];
  /** 利用者数（通っている子どもの数）と年齢別 */
  users?: (number | null)[];
  by_age?: Record<string, (number | null)[]>;
  sources?: string[];
  /** 定員の公開データがなく、位置だけ（古い公開版） */
  location_only?: boolean;
  as_of?: string | null;
}

export interface NurseryFile {
  schema_version: string;
  release_id: string;
  indicator_id: string;
  name: string;
  unit: string;
  description: string;
  method: string;
  caveats: string[];
  periods: { period: string; period_end: string; period_kind: string; label: string }[];
  source_ids: string[];
  /** 都道府県ごとの件数と範囲。点の一覧は places/<指標>/<都道府県>.json（#71） */
  prefectures?: Record<string, PlacePrefecture>;
  /** 古い公開版（1ファイルに全件）の一覧 */
  points?: NurseryPoint[];
}

/** 天気の指標（気象庁の平年値）の1つ。places/weather_normals.json の elements */
export interface WeatherElement {
  id: string;
  name: string;
  unit: string;
  digits: number;
  description: string;
  method: string;
  caveats: string[];
  scheme: string;
  count: number;
  breaks: number[];
  min: number;
  max: number;
}

/** 気象庁の観測所。値・月の値・統計期間（開始年・終了年・資料年数）は指標IDごと。値のない指標は含まない */
export interface WeatherStation {
  id: string;
  name: string;
  kana: string | null;
  municipality_id: string;
  coord: [number, number];
  altitude_m: number | null;
  values: Record<string, number>;
  monthly: Record<string, (number | null)[]>;
  years: Record<string, [number, number, number]>;
}

/** places/weather_normals.json（全国で約1,300地点なので都道府県に分けない。#94） */
export interface WeatherFile {
  schema_version: string;
  release_id: string;
  name: string;
  description: string;
  periods: { period: string; label: string }[];
  elements: WeatherElement[];
  source_ids: string[];
  stations: WeatherStation[];
}

/** 空港・港の1か所（places/airport_passengers.json・port_passengers.json の points）。値は periods の順 */
export interface TransportPoint {
  id: string;
  name: string;
  municipality_id: string;
  coord: [number, number];
  /** 合計（乗降客数・船舶乗降人員） */
  values: (number | null)[];
  /** 国内線・国内航路 */
  domestic: (number | null)[];
  /** 国際線・外国航路 */
  international: (number | null)[];
}

/** places/airport_passengers.json・port_passengers.json（全国で数百か所なので都道府県に分けない） */
export interface TransportFile {
  schema_version: string;
  release_id: string;
  indicator_id: string;
  name: string;
  unit: string;
  description: string;
  method: string;
  caveats: string[];
  periods: { period: string; period_end: string; period_kind: string; label: string }[];
  source_ids: string[];
  points: TransportPoint[];
}

/** 値のない施設の1か所（道の駅・国指定文化財。places/michi_no_eki.json などの points） */
export interface FacilityPoint {
  id: string;
  name: string;
  /** 所在地の市区町村（政令指定都市は区）。分からなければ null */
  municipality_id: string | null;
  /** 2つ以上の市区町村にまたがる施設のときだけ、すべての市区町村 */
  municipality_ids?: string[];
  /** 位置が分からない施設は null（地図には描かない） */
  coord: [number, number] | null;
  address?: string;
  /** 道の駅の登録回と登録年月（「1993年4月」） */
  round?: number;
  registered?: string;
  url?: string;
  /** 位置の注記（おおよその位置など） */
  location_note?: string;
  /** 文化財の分類（「国宝（建造物）」「史跡・名勝」など）と、件数を数える種類 */
  kind?: string;
  types?: string[];
  /** 文化財の建造物・町並みの種類（「近代／文化施設」「港町」） */
  subtype?: string;
  era?: string;
  /** 指定・登録・選定の年月日（「1989年5月19日指定」）と国宝の指定 */
  date?: string;
  treasure?: string;
  /** 国宝・重要文化財の棟の名前 */
  buildings?: string[];
  /** 国指定文化財等データベースの詳細のページ（heritage/detail/ の後ろ） */
  db?: string;
}

/** places/michi_no_eki.json（全国で約1,200か所なので都道府県に分けない）・places/cultural_properties.json（都道府県ごとのファイル） */
export interface FacilityFile {
  schema_version: string;
  release_id: string;
  indicator_id: string;
  name: string;
  unit: string;
  description: string;
  method: string;
  caveats: string[];
  periods: { period: string; period_end: string; period_kind: string; label: string }[];
  source_ids: string[];
  prefectures?: Record<string, PlacePrefecture>;
  points?: FacilityPoint[];
}
