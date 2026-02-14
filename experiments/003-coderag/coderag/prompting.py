from __future__ import annotations

from typing import Iterable, Tuple

SYSTEM_INSTRUCTION = (
    "You are a codebase QA assistant. Use ONLY the CONTEXT. "
    "If you cannot answer, output \"INSUFFICIENT_CONTEXT\". "
    "When you use a fact, cite it with [chunk:<id>]. Do not cite chunks you didn't use."
)

OUTPUT_FORMAT = (
    "Answer:\n"
    "- ...\n\n"
    "Citations:\n"
    "- chunk:<id>"
)

ContextChunk = Tuple[int, str, int, int, str]


def format_context_packet(contexts: Iterable[ContextChunk]) -> str:
    parts: list[str] = []
    for chunk_id, path, start_line, end_line, content in contexts:
        header = f"[chunk_id={chunk_id} path={path} lines={start_line}-{end_line}]"
        parts.append(f"{header}\n{content}")
    return "\n\n".join(parts).strip()


def build_prompt(question: str, contexts: Iterable[ContextChunk]) -> str:
    context_text = format_context_packet(contexts)
    return (
        "SYSTEM:\n"
        f"{SYSTEM_INSTRUCTION}\n\n"
        "QUESTION:\n"
        f"{question}\n\n"
        "CONTEXT:\n"
        f"{context_text}\n\n"
        "OUTPUT FORMAT:\n"
        f"{OUTPUT_FORMAT}\n"
    )
