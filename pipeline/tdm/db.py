"""管理用 SQLite の接続と書き込み補助。"""
from __future__ import annotations

import json
import sqlite3

import shapely
from shapely.geometry import shape
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path


class Connection(sqlite3.Connection):
    """観測値の文字列を keys の番号に置き換えるための対応表を持つ接続（schema.sql の obs）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.key_ids: dict[str, int] = {}


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, factory=Connection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def tune_for_bulk_load(conn: sqlite3.Connection) -> None:
    """公開版を作るときの一括取込用の設定。全国では観測値が数千万行になるので、既定（2MB）より大きなキャッシュにする。
    並べ替え用の一時領域はディスクのままにする（索引を作るときに数GBになり、メモリに置くとランナーが落ちる）。"""
    conn.execute("PRAGMA cache_size = -262144")   # 256MB（private のランナーはメモリ7GB程度）


# 一括取込の間は外しておく索引（取込中の検索には使わない）。schema.sql と同じ定義
SECONDARY_INDEXES = {
    "idx_obs_entity": "CREATE INDEX IF NOT EXISTS idx_obs_entity ON obs(entity_k, indicator_k, period_start_k)",
}


def drop_secondary_indexes(conn: sqlite3.Connection) -> None:
    for name in SECONDARY_INDEXES:
        conn.execute(f"DROP INDEX IF EXISTS {name}")


def create_secondary_indexes(conn: sqlite3.Connection) -> None:
    for sql in SECONDARY_INDEXES.values():
        conn.execute(sql)


def init_schema(conn: sqlite3.Connection) -> None:
    old = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'observations'").fetchone()
    if old:
        # 観測値を番号の表に分ける前の DB（design-changes #69）。元ファイルから作り直せるので移し替えはしない
        raise RuntimeError("管理用DBが古い形式です。DB のファイルを消してから取り込み直してください。")
    sql = resources.files("tdm").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(sql)


def dump_geometry(geom) -> bytes:
    """境界を管理用DBに書く形（WKB）。GeoJSON の文字列より小さく、読み込みも速い。座標の精度は変えない。"""
    return shapely.to_wkb(geom)


def load_geometry(value):
    """管理用DBの境界（WKB、古い版の DB や試験では GeoJSON の文字列）を shapely の図形にする。"""
    if isinstance(value, (bytes, memoryview)):
        return shapely.from_wkb(bytes(value))
    return shape(json.loads(value))


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def upsert_entity(conn: sqlite3.Connection, entity_id: str, entity_type: str, name: str,
                  parent_id: str | None = None, region: str | None = None) -> None:
    conn.execute(
        """INSERT INTO entities (entity_id, entity_type, name, parent_id, region)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(entity_id) DO UPDATE SET
             name = excluded.name, parent_id = excluded.parent_id,
             region = COALESCE(excluded.region, entities.region)""",
        (entity_id, entity_type, name, parent_id, region),
    )


def upsert_indicators(conn: sqlite3.Connection, catalog: dict[str, dict]) -> None:
    for indicator_id, d in catalog.items():
        conn.execute(
            """INSERT INTO indicators (indicator_id, definition_version, name, category, unit,
                                       kind, definition_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(indicator_id, definition_version) DO UPDATE SET
                 name = excluded.name, category = excluded.category, unit = excluded.unit,
                 kind = excluded.kind, definition_json = excluded.definition_json""",
            (indicator_id, d["definition_version"], d["name"], d["category"], d["unit"],
             d["kind"], json.dumps(d, ensure_ascii=False)),
        )


# 観測値の列（obs の番号の列 ← observations ビューの文字列の列）
_KEY_COLUMNS = {
    "indicator_k": "indicator_id", "definition_version_k": "definition_version",
    "period_start_k": "period_start", "period_end_k": "period_end", "source_k": "source_id",
    "dimension_k": "dimension_key", "entity_k": "entity_id", "period_kind_k": "period_kind",
    "status_k": "status", "denominator_source_k": "denominator_source_id", "boundary_k": "boundary_id",
    "coverage_note_k": "coverage_note", "method_note_k": "method_note", "updated_at_k": "updated_at",
}
_REQUIRED = {"entity_id", "indicator_id", "definition_version", "period_start", "period_end",
             "period_kind", "status", "source_id"}
_VALUE_COLUMNS = ("value", "numerator", "denominator")
PERIOD_KINDS = {"point", "calendar_year", "fiscal_year", "month_to_date", "multi_year"}
STATUSES = {"observed", "estimated", "derived", "missing", "suppressed", "withheld", "not_applicable"}
NO_VALUE_STATUSES = {"missing", "suppressed", "withheld", "not_applicable"}
_OBS_COLUMNS = list(_KEY_COLUMNS) + list(_VALUE_COLUMNS)
_INSERT_OBS = (
    f"INSERT INTO obs ({', '.join(_OBS_COLUMNS)}) VALUES ({', '.join('?' for _ in _OBS_COLUMNS)})"
    " ON CONFLICT DO UPDATE SET "
    + ", ".join(f"{c} = excluded.{c}" for c in _OBS_COLUMNS if c not in
                ("indicator_k", "definition_version_k", "period_start_k", "period_end_k", "source_k",
                 "dimension_k", "entity_k")))


def key_id(conn: sqlite3.Connection, key: str | None) -> int | None:
    """文字列の番号（keys）。なければ作る。"""
    if key is None:
        return None
    cache = getattr(conn, "key_ids", None)
    if cache is not None and key in cache:
        return cache[key]
    row = conn.execute("SELECT key_id FROM keys WHERE key = ?", (key,)).fetchone()
    kid = row[0] if row else conn.execute("INSERT INTO keys (key) VALUES (?)", (key,)).lastrowid
    if cache is not None:
        cache[key] = kid
    return kid


def insert_observation(conn: sqlite3.Connection, **obs) -> None:
    """観測値を1行書く。同じ指標・定義・時点・出典・内訳・地域の行があれば置き換える。
    制約に合わない行は、表の CHECK 制約と同じく sqlite3.IntegrityError にする。"""
    obs.setdefault("dimension_key", "all")
    obs.setdefault("updated_at", now_iso())
    unknown = set(obs) - set(_KEY_COLUMNS.values()) - set(_VALUE_COLUMNS)
    if unknown:
        raise sqlite3.IntegrityError(f"観測値に知らない列があります: {sorted(unknown)}")
    missing = [c for c in _REQUIRED if obs.get(c) is None]
    if missing:
        raise sqlite3.IntegrityError(f"観測値に必須の列がありません: {missing}")
    if obs["period_kind"] not in PERIOD_KINDS:
        raise sqlite3.IntegrityError(f"期間の種類が不正です: {obs['period_kind']}")
    if obs["status"] not in STATUSES:
        raise sqlite3.IntegrityError(f"状態が不正です: {obs['status']}")
    # 値がない行は value を NULL にし、ゼロに置き換えない（値がある行は status も値ありにする）
    if (obs["status"] in NO_VALUE_STATUSES) != (obs.get("value") is None):
        raise sqlite3.IntegrityError(f"状態 {obs['status']} と値 {obs.get('value')} が合いません"
                         f"（{obs['indicator_id']} {obs['entity_id']} {obs['period_start']}）")
    params = [key_id(conn, obs.get(text)) for text in _KEY_COLUMNS.values()]
    params += [obs.get(c) for c in _VALUE_COLUMNS]
    conn.execute(_INSERT_OBS, params)
