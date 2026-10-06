import math

from app.core.config import Settings
from app.services.embeddings import HashingEmbedder, MiniLMEmbedder, create_embedder


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def test_hashing_embedder_ranks_related_policy_text_higher() -> None:
    embedder = HashingEmbedder()
    remote, similar, salary = embedder.embed(
        [
            "remote work requires manager approval for all staff",
            "remote work policy manager approval",
            "salary band for junior accountants is confidential",
        ]
    )
    assert _cosine(remote, similar) > _cosine(remote, salary)
    assert math.isclose(math.sqrt(sum(value * value for value in remote)), 1.0, rel_tol=1e-6)


def test_create_embedder_selects_backend() -> None:
    hashing = create_embedder(Settings(_env_file=None, embedding_backend="hashing"))
    minilm = create_embedder(
        Settings(
            _env_file=None,
            embedding_backend="minilm",
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
        )
    )
    assert isinstance(hashing, HashingEmbedder)
    assert isinstance(minilm, MiniLMEmbedder)
