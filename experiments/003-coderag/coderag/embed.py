from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer

_MODEL = None

def get_model(model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> SentenceTransformer:
    global _MODEL
    if _MODEL is None:
        _MODEL = SentenceTransformer(model_name)
    return _MODEL

def embed_texts(texts: list[str], model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> np.ndarray:
    """
    Returns float32 array shape (n, d), L2-normalized for cosine via dot product.
    """
    model = get_model(model_name)
    embs = model.encode(texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True)
    return np.asarray(embs, dtype=np.float32)

def to_blob(vec: np.ndarray) -> bytes:
    return vec.astype(np.float32).tobytes()

def from_blob(blob: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32, count=dim)
