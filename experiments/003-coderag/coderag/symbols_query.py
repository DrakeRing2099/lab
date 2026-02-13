from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List

@dataclass
class SymbolHit:
    symbol_name: str
    symbol_kind: str
    path: str
    start_line: int
    end_line: int
    chunk_id: int

def find_definitions(db_path: Path, repo_root: str, name: str, k: int = 10) -> List[SymbolHit]:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        SELECT symbol_name, symbol_kind, path, start_line, end_line, chunk_id
        FROM symbols
        WHERE repo_root = ? AND symbol_name = ?
        ORDER BY symbol_kind ASC, path ASC, start_line ASC
        LIMIT ?
        """,
        (repo_root, name, k),
    )
    return [SymbolHit(*row) for row in cur.fetchall()]

def find_references(db_path: Path, repo_root: str, name: str, k: int = 20) -> List[tuple[str, int, str]]:
    """
    v1 refs: naive text scan over chunks (fast enough for now).
    Returns (path, line, snippet).
    """
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        SELECT path, start_line, content
        FROM chunks
        WHERE repo_root = ?
        """,
        (repo_root,),
    )
    out: List[tuple[str, int, str]] = []
    needle = name

    for path, start_line, content in cur.fetchall():
        for i, line in enumerate(content.splitlines(), start=0):
            if needle in line and "def " not in line and "class " not in line:
                out.append((path, start_line + i, line.strip()))
                if len(out) >= k:
                    return out
    return out
