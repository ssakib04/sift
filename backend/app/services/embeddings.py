import hashlib
import math
import re
from typing import Any, Protocol

from app.core.config import Settings, get_settings
from app.models.policy import EMBEDDING_DIMENSIONS

_TOKEN = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text."""


class HashingEmbedder:
    """Deterministic bag-of-tokens vectors used when the MiniLM model is not selected."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_hash_text(text) for text in texts]


class MiniLMEmbedder:
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: Any = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self._model_name)
        vectors = list(self._model.embed(texts))
        return [_as_unit_list(vector) for vector in vectors]


def create_embedder(settings: Settings | None = None) -> Embedder:
    resolved = settings or get_settings()
    if resolved.embedding_backend == "hashing":
        return HashingEmbedder()
    return MiniLMEmbedder(resolved.embedding_model)


def _hash_text(text: str) -> list[float]:
    buckets = [0.0] * EMBEDDING_DIMENSIONS
    tokens = _TOKEN.findall(text.lower())
    if not tokens:
        buckets[0] = 1.0
        return buckets
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        buckets[index] += sign
    return _normalize(buckets)


def _as_unit_list(vector: Any) -> list[float]:
    values = [float(item) for item in vector]
    if len(values) != EMBEDDING_DIMENSIONS:
        raise RuntimeError("Embedding model returned an unexpected vector size.")
    return _normalize(values)


def _normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return values
    return [value / norm for value in values]
