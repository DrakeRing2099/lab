from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from .util import guess_language, sha256_text

@dataclass(frozen=True)
class Chunk:
    path: str
    start_line: int
    end_line: int
    language: str
    content: str
    content_hash: str

def chunk_text(path: Path, text: str, max_lines: int = 120, overlap: int = 20) -> List[Chunk]:
    lines = text.splitlines()
    n = len(lines)

    lang = guess_language(path)

    # Small file => single chunk
    if n <= 250:
        content = "\n".join(lines)
        return [
            Chunk(
                path=str(path.as_posix()),
                start_line=1,
                end_line=max(1, n),
                language=lang,
                content=content,
                content_hash=sha256_text(content),
            )
        ]

    # Large file => sliding window chunks
    chunks: List[Chunk] = []
    step = max(1, max_lines - overlap)

    start = 0
    while start < n:
        end = min(n, start + max_lines)
        content = "\n".join(lines[start:end])
        chunks.append(
            Chunk(
                path=str(path.as_posix()),
                start_line=start + 1,
                end_line=end,
                language=lang,
                content=content,
                content_hash=sha256_text(content),
            )
        )
        if end == n:
            break
        start += step

    return chunks
