from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np

from .embed import embed_texts, from_blob

@dataclass
class VHit:
    chunk_id: int
    path: str
    start_line: int
    end_line: int
    score: float
    preview: str

def query_vector(db_path: Path, repo_root: str, question: str, k: int = 6) -> List[VHit]:
    q_emb = embed_texts([question])[0]  # normalized float32
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, path, start_line, end_line, content, embedding
        FROM chunks
        WHERE repo_root = ? AND embedding IS NOT NULL
        """,
        (repo_root,),
    )

    rows = cur.fetchall()
    if not rows:
        return []

    # infer dim from first embedding
    first_blob = rows[0][5]
    dim = int(len(first_blob) / 4)

    hits: List[VHit] = []
    for chunk_id, path, start_line, end_line, content, blob in rows:
        v = from_blob(blob, dim)
        score = float(np.dot(q_emb, v))  # cosine (because both normalized)
        preview = "\n".join(content.splitlines()[:30])
        hits.append(VHit(chunk_id, path, start_line, end_line, score, preview))

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]
