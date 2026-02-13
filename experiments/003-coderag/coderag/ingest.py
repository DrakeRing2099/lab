from __future__ import annotations

from pathlib import Path
from typing import List, Tuple, Dict

import pathspec

from .chunk import Chunk, chunk_text
from .embed import embed_texts, to_blob
from .store import (
    connect,
    insert_chunks_with_embeddings,
    list_indexed_paths,
    get_hashes_for_path,
    delete_paths,
    delete_path,
    rebuild_symbols,
)

from .chunk import chunk_file

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

def ingest(repo_path: Path, db_path: Path) -> Tuple[int, int, int, int]:
    """
    Returns: (files_seen, paths_added_or_updated, paths_skipped, paths_deleted)
    """
    repo_path = repo_path.resolve()
    repo_root = str(repo_path)

    files = iter_files(repo_path)

    # group chunks by path (relative)
    by_path: Dict[str, List[Chunk]] = {}

    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        rel = f.relative_to(repo_path).as_posix()
        chunks = chunk_file(Path(rel), text)  # Path for suffix/lang, but stored as posix in Chunk
        by_path[rel] = chunks

    conn = connect(db_path)

    # --- delete removed paths ---
    indexed_paths = list_indexed_paths(conn, repo_root)
    current_paths = set(by_path.keys())
    removed = sorted(indexed_paths - current_paths)
    if removed:
        delete_paths(conn, repo_root, removed)

    # --- decide which paths changed ---
    changed_paths: List[str] = []
    skipped = 0

    for path, chunks in by_path.items():
        new_hashes = {c.content_hash for c in chunks}
        old_hashes = get_hashes_for_path(conn, repo_root, path)

        # if not indexed before => changed
        if not old_hashes:
            changed_paths.append(path)
            continue

        # if chunk hashes identical => skip
        if new_hashes == old_hashes:
            skipped += 1
            continue

        changed_paths.append(path)

    # --- apply updates: delete + insert for changed paths ---
    inserted_chunks = 0

    # batch embeddings for changed chunks only
    changed_chunks: List[Chunk] = []
    for p in changed_paths:
        changed_chunks.extend(by_path[p])

    if changed_chunks:
        # delete old chunks for those paths
        for p in changed_paths:
            delete_path(conn, repo_root, p)

        texts = [c.content for c in changed_chunks]
        embs = embed_texts(texts)
        emb_blobs = [to_blob(embs[i]) for i in range(embs.shape[0])]

        inserted_chunks = insert_chunks_with_embeddings(
            conn,
            repo_root=repo_root,
            chunks=changed_chunks,
            embeddings=emb_blobs,
        )

    conn.commit()
    rebuild_symbols(conn, repo_root)
    return (len(files), len(changed_paths), skipped, len(removed))