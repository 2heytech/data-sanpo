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
  /** zero_blank: 値が0の地域は色を塗らない（犯罪の件数など） */
  legend: { method: string; classes: number; scheme: string; zero_blank?: boolean };
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

export interface SmallAreasFile {
  municipality_id: string;
  areas: SmallArea[];
}

export interface ValueRow {
  entity_id: string;
  value: number | null;
  status: Status;
  numerator?: number;
  denominator?: number;
  note?: string;
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
  breaks: number[];
  min: number | null;
  max: number | null;
  count: number;
  /** 市区町村の、都道府県ごとの区切り（全国の公開版。地図は都道府県ごとの区切りで塗る） */
  by_prefecture?: Record<string, number[]>;
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
  /** 東京都以外: 児童・生徒数の公開データがなく、位置だけ（国土数値情報 学校データ） */
  location_only?: boolean;
  as_of?: string | null;
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
  founder: string;
  address: string | null;
  coord: [number, number] | null;
  precision: string | null;
  values: (number | null)[];
  /** 東京都以外: 定員の公開データがなく、位置だけ（国土数値情報 福祉施設データ） */
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
