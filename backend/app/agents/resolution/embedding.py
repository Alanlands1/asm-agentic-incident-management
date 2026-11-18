"""Resolution agent, step 3: embeddings for kb_chunks.

`SentenceEmbedder` runs google/embeddinggemma-300m locally through sentence-transformers, truncated to EMBEDDING_DIM
(Matryoshka). It needs the optional dependencies in backend/requirements-embedding.txt. Retrieval uses full text only
for rows whose embedding is still NULL.
"""

from typing import Any, Protocol

from app.core.config import settings


class Embedder(Protocol):
    model_name: str  # recorded on each row, e.g. google/embeddinggemma-300m

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def indexed_text(context: str, content: str) -> str:
    """What gets embedded for a chunk: the context blurb, then the chunk as written."""
    return f"{context}\n\n{content}" if context else content


class SentenceEmbedder:
    """EmbeddingGemma through sentence-transformers. Pass `model` to inject a loaded model (tests)."""

    def __init__(self, model: Any | None = None):
        if model is None:
            from sentence_transformers import SentenceTransformer  # optional dependency, imported only when used

            model = SentenceTransformer(settings.EMBEDDING_MODEL, truncate_dim=settings.EMBEDDING_DIM)
        self._model = model
        self.model_name = settings.EMBEDDING_MODEL

    def _check(self, vectors: list[list[float]]) -> list[list[float]]:
        if any(len(v) != settings.EMBEDDING_DIM for v in vectors):
            raise ValueError(f"embedding size is not EMBEDDING_DIM={settings.EMBEDDING_DIM}")
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # encode_document applies the model's own document prompt; encode_query applies the query prompt
        vectors = self._model.encode_document(texts, normalize_embeddings=True)
        return self._check([v.tolist() for v in vectors])

    def embed_query(self, text: str) -> list[float]:
        return self._check([self._model.encode_query(text, normalize_embeddings=True).tolist()])[0]
