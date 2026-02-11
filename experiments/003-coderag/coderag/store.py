from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from .chunk import Chunk

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_root TEXT NOT NULL,
  path TEXT NOT NULL,
  start_line INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  language TEXT NOT NULL,
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_chunks_repo_path ON chunks(repo_root, path);
CREATE INDEX IF NOT EXISTS idx_chunks_repo_hash ON chunks(repo_root, path, content_hash);
"""

def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(SCHEMA)
    return conn

def upsert_chunks(conn: sqlite3.Connection, repo_root: str, chunks: Iterable[Chunk]) -> int:
    # v1 simple approach: delete then insert per file path group later.
    # For now: insert everything; we'll add incremental/cleanup in v1.5.
    cur = conn.cursor()
    count = 0
    for c in chunks:
        cur.execute(
            """
            INSERT INTO chunks (repo_root, path, start_line, end_line, language, content, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (repo_root, c.path, c.start_line, c.end_line, c.language, c.content, c.content_hash),
        )
        count += 1
    conn.commit()
    return count
