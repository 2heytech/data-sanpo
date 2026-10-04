-- 管理用DB（開発者側のみで利用。閲覧者からは接続しない）
-- 設計書 v1 第7・8章に対応。変更点は docs/design-changes.md を参照。
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
  source_id      TEXT PRIMARY KEY,          -- 例: census2020-small-area-boundary@<sha8>
  dataset_key    TEXT NOT NULL,             -- config/sources.toml のキー（版をまたいで同じ）
  title          TEXT NOT NULL,
  provider       TEXT NOT NULL,
  url            TEXT,
  license        TEXT NOT NULL,
  license_url    TEXT,
  attribution    TEXT NOT NULL,             -- 画面に表示する出典表記
  modification_note TEXT,                   -- 加工した旨の表記
  published_at   TEXT,                      -- 出典側の公開・更新日
  retrieved_at   TEXT NOT NULL,             -- 取得日時（ISO 8601）
  file_sha256    TEXT NOT NULL,
  redistributable INTEGER NOT NULL DEFAULT 0 CHECK (redistributable IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_sources_dataset ON sources(dataset_key);

CREATE TABLE IF NOT EXISTS entities (
  entity_id   TEXT PRIMARY KEY,             -- 例: muni-13101, area-13101001001
  entity_type TEXT NOT NULL CHECK (entity_type IN
                ('prefecture', 'municipality', 'small_area', 'station', 'school', 'store', 'land_point', 'nursery')),
  name        TEXT NOT NULL,
  name_kana   TEXT,
  parent_id   TEXT REFERENCES entities(entity_id),
  region      TEXT,                         -- 区部 / 多摩 / 島しょ（市区町村のみ）
  valid_from  TEXT,
  valid_to    TEXT
);
CREATE INDEX IF NOT EXISTS idx_entities_parent ON entities(parent_id);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);

-- 駅の事業者・路線など、種別ごとに異なる属性（JSON）
CREATE TABLE IF NOT EXISTS entity_attributes (
  entity_id  TEXT PRIMARY KEY REFERENCES entities(entity_id),
  attributes TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_keys (
  source_id  TEXT NOT NULL REFERENCES sources(source_id),
  source_key TEXT NOT NULL,                 -- 出典側のコード（文字列で保持し先頭0を残す）
  entity_id  TEXT NOT NULL REFERENCES entities(entity_id),
  PRIMARY KEY (source_id, source_key)
);
CREATE INDEX IF NOT EXISTS idx_source_keys_entity ON source_keys(entity_id);

CREATE TABLE IF NOT EXISTS boundaries (
  boundary_id     TEXT PRIMARY KEY,         -- 例: census2020:area-13101001001
  boundary_version TEXT NOT NULL,           -- 例: census2020
  entity_id       TEXT NOT NULL REFERENCES entities(entity_id),
  reference_date  TEXT NOT NULL,
  source_id       TEXT NOT NULL REFERENCES sources(source_id),
  geometry        TEXT NOT NULL,            -- 元の精度の GeoJSON geometry（簡略化しない）
  area_m2         REAL,                     -- 元の境界から算出、または出典の公表面積
  area_m2_source  TEXT CHECK (area_m2_source IN ('published', 'computed')),
  bbox_west REAL NOT NULL, bbox_south REAL NOT NULL,
  bbox_east REAL NOT NULL, bbox_north REAL NOT NULL,
  UNIQUE (boundary_version, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_boundaries_entity ON boundaries(entity_id);

CREATE TABLE IF NOT EXISTS locations (
  location_id    TEXT PRIMARY KEY,
  entity_id      TEXT NOT NULL REFERENCES entities(entity_id),
  role           TEXT NOT NULL DEFAULT 'main',  -- 校舎・出入口など複数地点の区別
  lon REAL NOT NULL CHECK (lon BETWEEN 122 AND 154),
  lat REAL NOT NULL CHECK (lat BETWEEN 20 AND 46),
  reference_date TEXT,
  source_id      TEXT NOT NULL REFERENCES sources(source_id)
);
CREATE INDEX IF NOT EXISTS idx_locations_entity ON locations(entity_id);

CREATE TABLE IF NOT EXISTS indicators (
  indicator_id       TEXT NOT NULL,
  definition_version TEXT NOT NULL,
  name               TEXT NOT NULL,
  category           TEXT NOT NULL,
  unit               TEXT NOT NULL,
  kind               TEXT NOT NULL CHECK (kind IN ('count', 'ratio', 'density', 'change')),
  definition_json    TEXT NOT NULL,         -- カタログ全体（計算式・分母・注意点・凡例）
  PRIMARY KEY (indicator_id, definition_version)
);

-- 観測値。全国では数千万行になるので、文字列（地域ID・指標ID・時点・出典など）は keys の番号で持ち、
-- 1行を小さくする（2026-10-04、design-changes #69）。読むときは下の observations ビューで文字列に戻る。
-- 書き込みは tdm.db.insert_observation だけが行う（値の検査もそこで行う）。
CREATE TABLE IF NOT EXISTS keys (
  key_id INTEGER PRIMARY KEY,
  key    TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS obs (
  -- 指標を先頭にする。取込は指標ごとにまとめて書くので、全国でも書き込みが局所的になる。指標・時点での検索もこれで引ける
  indicator_k            INTEGER NOT NULL,
  definition_version_k   INTEGER NOT NULL,
  period_start_k         INTEGER NOT NULL,
  period_end_k           INTEGER NOT NULL,
  source_k               INTEGER NOT NULL,
  dimension_k            INTEGER NOT NULL,
  entity_k               INTEGER NOT NULL,
  period_kind_k          INTEGER NOT NULL,
  -- 値がない行は value を NULL にし、ゼロに置き換えない
  value                  REAL,
  numerator              REAL,
  denominator            REAL,
  status_k               INTEGER NOT NULL,
  denominator_source_k   INTEGER,
  boundary_k             INTEGER,
  coverage_note_k        INTEGER,
  method_note_k          INTEGER,
  updated_at_k           INTEGER NOT NULL,
  PRIMARY KEY (indicator_k, definition_version_k, period_start_k, period_end_k, source_k,
               dimension_k, entity_k)
) WITHOUT ROWID;
-- 次は一括取込の間は外し、取込の最後に作り直す（tdm.db.SECONDARY_INDEXES）
CREATE INDEX IF NOT EXISTS idx_obs_entity ON obs(entity_k, indicator_k, period_start_k);

CREATE VIEW IF NOT EXISTS observations AS
SELECT ke.key AS entity_id, ki.key AS indicator_id, kd.key AS definition_version,
       kps.key AS period_start, kpe.key AS period_end, kpk.key AS period_kind,
       kdim.key AS dimension_key, o.value, o.numerator, o.denominator, kst.key AS status,
       ksrc.key AS source_id, kds.key AS denominator_source_id, kb.key AS boundary_id,
       kcn.key AS coverage_note, kmn.key AS method_note, ku.key AS updated_at
FROM obs o
JOIN keys ki ON ki.key_id = o.indicator_k
JOIN keys kd ON kd.key_id = o.definition_version_k
JOIN keys kps ON kps.key_id = o.period_start_k
JOIN keys kpe ON kpe.key_id = o.period_end_k
JOIN keys ksrc ON ksrc.key_id = o.source_k
JOIN keys kdim ON kdim.key_id = o.dimension_k
JOIN keys ke ON ke.key_id = o.entity_k
JOIN keys kpk ON kpk.key_id = o.period_kind_k
JOIN keys kst ON kst.key_id = o.status_k
LEFT JOIN keys kds ON kds.key_id = o.denominator_source_k
LEFT JOIN keys kb ON kb.key_id = o.boundary_k
LEFT JOIN keys kcn ON kcn.key_id = o.coverage_note_k
LEFT JOIN keys kmn ON kmn.key_id = o.method_note_k
JOIN keys ku ON ku.key_id = o.updated_at_k;

CREATE TABLE IF NOT EXISTS releases (
  release_id    TEXT PRIMARY KEY,
  created_at    TEXT NOT NULL,
  git_commit    TEXT,
  manifest_sha256 TEXT NOT NULL,
  note          TEXT
);
