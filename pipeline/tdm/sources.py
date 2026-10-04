"""出典の版（ファイルhash）を sources テーブルへ記録する。"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from .db import now_iso


def find_files(directory: Path, patterns: list[str]) -> list[Path]:
    found: set[Path] = set()
    for pattern in patterns:
        found.update(p for p in directory.rglob(pattern) if p.is_file())
    return sorted(found)


def hash_files(files: list[Path]) -> str:
    h = hashlib.sha256()
    for f in sorted(files, key=lambda p: p.name):
        h.update(f.name.encode())
        h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def register_source(conn: sqlite3.Connection, dataset_key: str, cfg: dict, files: list[Path],
                    overrides: dict | None = None) -> str:
    """出典を登録し source_id を返す。同じ内容のファイルなら同じ source_id になる。"""
    if not files:
        raise FileNotFoundError(f"{dataset_key}: 元ファイルが見つかりません")
    meta = {**cfg, **(overrides or {})}
    sha = hash_files(files)
    source_id = f"{dataset_key}@{sha[:12]}"
    conn.execute(
        """INSERT INTO sources (source_id, dataset_key, title, provider, url, license, license_url,
                                attribution, modification_note, published_at, retrieved_at,
                                file_sha256, redistributable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(source_id) DO NOTHING""",
        (source_id, dataset_key, meta["title"], meta["provider"], meta.get("url"),
         meta["license"], meta.get("license_url"), meta["attribution"],
         meta.get("modification_note"), meta.get("published_at"), now_iso(), sha,
         1 if meta.get("redistributable") else 0),
    )
    return source_id
