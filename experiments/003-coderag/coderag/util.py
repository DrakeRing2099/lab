from __future__ import annotations

import hashlib
from pathlib import Path

EXT_LANG = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".env": "env",
    ".toml": "toml",
}

TEXT_EXT_ALLOWLIST = set(EXT_LANG.keys()) | {
    ".txt", ".css", ".html", ".sql"
}


def guess_language(path: Path) -> str:
    return EXT_LANG.get(path.suffix.lower(), "text")

def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()

def is_probably_text_file(path: Path) -> bool:
    # quick filter by extension (good enough for v1)
    suf = path.suffix.lower()
    if path.name.startswith(".") and suf == "":
        # allow dot files like .env.example
        return True
    return suf in TEXT_EXT_ALLOWLIST or path.name.endswith(".env.example")