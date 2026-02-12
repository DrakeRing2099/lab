from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import numpy as np

from .embed import embed_texts, from_blob
from .query import normalize_tokens, lexical_score  # reuse v1 logic

@dataclass
class HHit:
    chunk_id: int
    path: str
    start_line: int
    end_line: int
    cos: float
    lex: float
    score: float
    why: str
    preview: str

def query_hybrid(db_path: Path, repo_root: str, question: str, k: int = 6, cand: int = 30) -> List[HHit]:
    q_emb = embed_texts([question])[0]  # normalized
    q_tokens = normalize_tokens(question)

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

    dim = int(len(rows[0][5]) / 4)

    # --- vector stage: score all, keep top cand ---
    vec_scored: List[Tuple[float, tuple]] = []
    for row in rows:
        chunk_id, path, start_line, end_line, content, blob = row
        v = from_blob(blob, dim)
        cos = float(np.dot(q_emb, v))
        vec_scored.append((cos, row))

    vec_scored.sort(key=lambda x: x[0], reverse=True)
    candidates = vec_scored[: max(cand, k)]

    # --- rerank stage: lexical + code boosts ---
    hits: List[HHit] = []
    for cos, row in candidates:
        chunk_id, path, start_line, end_line, content, _blob = row
        lex, why = lexical_score(content, q_tokens, path)

        # combine: keep cosine as recall, lexical as ordering
        # (weights are tuned for codebases; adjust later)
        score = cos * 1.0 + (lex / 10.0) * 1.5

        preview = "\n".join(content.splitlines()[:30])
        hits.append(
            HHit(
                chunk_id=chunk_id,
                path=path,
                start_line=start_line,
                end_line=end_line,
                cos=cos,
                lex=lex,
                score=score,
                why=why,
                preview=preview,
            )
        )

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]
