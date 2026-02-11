from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import pathspec

from .chunk import Chunk, chunk_text
from .store import connect, upsert_chunks
from .util import is_probably_text_file

DEFAULT_IGNORES = [
    ".git/",
    "node_modules/",
    ".venv/",
    "dist/",
    "build/",
    ".next/",
    "__pycache__/",
]

def load_gitignore(root: Path) -> pathspec.PathSpec:
    patterns = list(DEFAULT_IGNORES)
    gi = root / ".gitignore"
    if gi.exists():
        patterns += gi.read_text(encoding="utf-8", errors="ignore").splitlines()
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)

def iter_files(root: Path) -> List[Path]:
    spec = load_gitignore(root)
    files: List[Path] = []

    for p in root.rglob("*"):
        if p.is_dir():
            continue

        rel = p.relative_to(root).as_posix()

        # ignore matches
        if spec.match_file(rel):
            continue

        # v1: only index probable text files
        if not is_probably_text_file(p):
            continue

        files.append(p)

    return files

def ingest(repo_path: Path, db_path: Path) -> Tuple[int, int]:
    repo_path = repo_path.resolve()
    repo_root = str(repo_path)

    files = iter_files(repo_path)

    all_chunks: List[Chunk] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        rel = f.relative_to(repo_path)  # store paths relative to repo root
        all_chunks.extend(chunk_text(rel, text))

    conn = connect(db_path)
    inserted = upsert_chunks(conn, repo_root=repo_root, chunks=all_chunks)
    return len(files), inserted
