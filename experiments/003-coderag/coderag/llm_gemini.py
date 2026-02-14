from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from google import genai

DEFAULT_MODEL = "gemini-3-flash-preview"
DEFAULT_TEMPERATURE = 0.1


def _maybe_load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    env_path = Path(__file__).with_name(".env")
    if env_path.exists():
        load_dotenv(env_path)


def _build_config(temperature: Optional[float]):
    if temperature is None:
        return None
    try:
        from google.genai import types

        return types.GenerateContentConfig(temperature=temperature)
    except Exception:
        return {"temperature": temperature}


def generate_answer(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
) -> str:
    _maybe_load_dotenv()
    if not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError(
            "GEMINI_API_KEY not found. Put it in coderag/.env or export it in your shell."
        )
    client = genai.Client()
    config = _build_config(temperature)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=config,
    )
    text = getattr(response, "text", None)
    if text is None:
        return str(response)
    return text.strip()
