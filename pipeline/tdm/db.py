"""管理用 SQLite の接続と書き込み補助。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def tune_for_bulk_load(conn: sqlite3.Connection) -> None:
    """公開版を作るときの一括取込用の設定。全国では観測値が数千万行になるので、既定（2MB）より大きなキャッシュにする。
    並べ替え用の一時領域はディスクのままにする（索引を作るときに数GBになり、メモリに置くとランナーが落ちる）。"""
    conn.execute("PRAGMA cache_size = -262144")   # 256MB（private のランナーはメモリ7GB程度）


# 一括取込の間は外しておく索引（取込中の検索には使わない）。schema.sql と同じ定義
SECONDARY_INDEXES = {
    "idx_obs_lookup": "CREATE INDEX IF NOT EXISTS idx_obs_lookup ON observations(entity_id, indicator_id, period_start)",
    "idx_obs_source": "CREATE INDEX IF NOT EXISTS idx_obs_source ON observations(source_id)",
}


def drop_secondary_indexes(conn: sqlite3.Connection) -> None:
    for name in SECONDARY_INDEXES:
        conn.execute(f"DROP INDEX IF EXISTS {name}")
    conn.execute("DROP INDEX IF EXISTS idx_obs_indicator")   # 旧版の索引（一意制約の索引で足りる）


def create_secondary_indexes(conn: sqlite3.Connection) -> None:
    for sql in SECONDARY_INDEXES.values():
        conn.execute(sql)


def init_schema(conn: sqlite3.Connection) -> None:
    sql = resources.files("tdm").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(sql)


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


def insert_observation(conn: sqlite3.Connection, **obs) -> None:
    obs.setdefault("dimension_key", "all")
    obs.setdefault("updated_at", now_iso())
    cols = ", ".join(obs)
    marks = ", ".join("?" for _ in obs)
    updates = ", ".join(f"{c} = excluded.{c}" for c in obs)
    conn.execute(
        f"""INSERT INTO observations ({cols}) VALUES ({marks})
            ON CONFLICT(entity_id, indicator_id, period_start, period_end, definition_version,
                        source_id, dimension_key) DO UPDATE SET {updates}""",
        tuple(obs.values()),
    )
