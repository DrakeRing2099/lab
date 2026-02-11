from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from .util import sha256_text

import re

@dataclass
class Hit:
    chunk_id: int
    path: str
    start_line: int
    end_line: int
    score: float
    why: str
    preview: str

STOPWORDS = {
    "a","an","and","are","as","at","be","by","for","from","has","have","how",
    "i","in","is","it","its","me","of","on","or","that","the","this","to","was",
    "were","what","when","where","which","who","why","with","do","does","did",
}

_token_re = re.compile(r"[a-z0-9_]+")

def normalize_tokens(q: str) -> list[str]:
    # Extract word-ish tokens, keep underscores for snake_case
    toks = _token_re.findall(q.lower())
    return [t for t in toks if t and t not in STOPWORDS]

def lexical_score(content: str, tokens: list[str], path: str) -> tuple[float, str]:
    """
    Code-aware lexical scoring.

    Signals:
    - token in file path/name (often strong)
    - token in "definition-ish" lines (def, class, function, export, const)
    - token anywhere in content

    Also: stopwords already removed; tokens are cleaned.
    """
    if not tokens:
        return (0.0, "no usable tokens")

    text = content.lower()
    lines = text.splitlines()

    # definition-ish lines: likely where semantics live
    def_lines = []
    for ln in lines[:200]:  # cap for speed
        if (
            ln.lstrip().startswith(("def ", "class ", "export ", "function ", "const ", "let "))
            or "->" in ln
            or "validate" in ln  # small bias, optional, keeps v1 good for code Qs
        ):
            def_lines.append(ln)
    defs = "\n".join(def_lines)

    p = path.lower()
    hits = []
    score = 0.0

    for t in tokens:
        s = 0.0
        if t in p:
            s += 6.0  # filename/path hit is strong for codebase navigation
        if t in defs:
            s += 5.0  # definitions are strong evidence
        if t in text:
            s += 2.0  # general presence
        if s > 0:
            hits.append(t)
            score += s

    if not hits:
        return (0.0, "no token overlap")

    return (score, f"matched={hits}")

def query_lexical(db_path: Path, repo_root: str, question: str, k: int = 6) -> List[Hit]:
    tokens = normalize_tokens(question)

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, path, start_line, end_line, content
        FROM chunks
        WHERE repo_root = ?
        """,
        (repo_root,),
    )

    hits: List[Hit] = []
    for chunk_id, path, start_line, end_line, content in cur.fetchall():
        score, why = lexical_score(content, tokens, path)
        if score <= 0:
            continue

        preview_lines = content.splitlines()[:30]
        preview = "\n".join(preview_lines)

        hits.append(
            Hit(
                chunk_id=chunk_id,
                path=path,
                start_line=start_line,
                end_line=end_line,
                score=score,
                why=why,
                preview=preview,
            )
        )

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]
