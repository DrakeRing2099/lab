from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from .chunk import Chunk
from .util import guess_language, sha256_text

# We will support these first; everything else falls back to line-window chunking.
SUPPORTED = {"python", "typescript", "javascript"}

# Node types we want as “semantic chunks”
PY_NODES = {"function_definition", "class_definition"}
TS_NODES = {"function_declaration", "method_definition", "class_declaration", "lexical_declaration"}


def _byte_slice(text: str, start_byte: int, end_byte: int) -> str:
    b = text.encode("utf-8", errors="ignore")
    return b[start_byte:end_byte].decode("utf-8", errors="ignore")

def _line_range(node) -> tuple[int, int]:
    srow = node.start_point[0] + 1
    erow = node.end_point[0] + 1
    return srow, erow

def _node_kind_set(lang: str) -> set[str]:
    if lang == "python":
        return PY_NODES
    return TS_NODES

def _find_identifier(node) -> object | None:
    if node.type in ("identifier", "property_identifier", "type_identifier"):
        return node
    for c in node.children:
        found = _find_identifier(c)
        if found is not None:
            return found
    return None

def _identifier_text(node, text: str) -> str:
    name = None
    try:
        name = node.child_by_field_name("name")
    except Exception:
        name = None
    if name is not None:
        return _byte_slice(text, name.start_byte, name.end_byte)

    ident = _find_identifier(node)
    if ident is None:
        return ""
    return _byte_slice(text, ident.start_byte, ident.end_byte)


def chunk_code_by_ast(path: Path, text: str) -> Optional[List[Chunk]]:
    """
    Returns list[Chunk] if AST chunking succeeded, else None.
    """
    lang = guess_language(path)
    if lang not in SUPPORTED:
        return None
    
    # tree-sitter-languages used "typescript" for both .ts/.tsx and "javascript" for .js/.jsx
    try:
        from tree_sitter_languages import get_parser
    except Exception:
        return None

    try:
        parser = get_parser(lang)
    except Exception:
        return None

    tree = parser.parse(text.encode("utf-8", errors="ignore"))
    root = tree.root_node
    if root is None:
        return None
    
    wanted = _node_kind_set(lang)
    chunks: List[Chunk] = []

    # 1) Always include a “top-of-file” chunk: imports + constants + module doc.
    # This helps questions like “where is X configured / imported”.

    head_lines = text.splitlines()
    head_n = min(len(head_lines), 60)
    head_content = "\n".join(head_lines[:head_n]).strip()
    if head_content:
        chunks.append(
            Chunk(
                path=str(path.as_posix()),
                start_line=1,
                end_line=head_n,
                language=lang,
                content=head_content,
                content_hash=sha256_text(head_content),
            )
        )


    # 2) Add function/class chunks
    # We walk descendants and pice certain node types.
    # We also avoid tiny chunks (e.g., empty nodes).
    def walk(node):
        yield node
        for c in node.children:
            yield from walk(c)
    
    for node in walk(root):
        if node.type not in wanted:
            continue

        start_line, end_line = _line_range(node)
        if end_line - start_line + 1 < 3:
            continue

        content = _byte_slice(text, node.start_byte, node.end_byte).strip()
        if not content:
            continue

        # symbol kind + name (best-effort)
        symbol_kind = None
        symbol_name = None

        if lang == "python":
            if node.type == "function_definition":
                symbol_kind = "function"
                symbol_name = _identifier_text(node, text) or ""
            elif node.type == "class_definition":
                symbol_kind = "class"
                symbol_name = _identifier_text(node, text) or ""

        else:  # typescript/javascript
            if node.type in ("function_declaration",):
                symbol_kind = "function"
                symbol_name = _identifier_text(node, text) or ""
            elif node.type in ("class_declaration",):
                symbol_kind = "class"
                symbol_name = _identifier_text(node, text) or ""
            elif node.type in ("method_definition",):
                symbol_kind = "method"
                symbol_name = _identifier_text(node, text) or ""

        chunks.append(
            Chunk(
                path=str(path.as_posix()),
                start_line=start_line,
                end_line=end_line,
                language=lang,
                content=content,
                content_hash=sha256_text(content),
                symbol_kind=symbol_kind,
                symbol_name=symbol_name if symbol_name else None,
            )
        )

    # If we onl got a head chunk and no semantic nodes, treat as failure
    if len(chunks) <= 1:
        return None
    
    # Optional: sort by start_line for stable output
    chunks.sort(key=lambda c: (c.start_line, c.end_line))
    return chunks
