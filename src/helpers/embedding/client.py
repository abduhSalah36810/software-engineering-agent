"""
Local embedding client using FastEmbed.

Replaces the previous HTTP-based external embedding service.
FastEmbed runs entirely locally — no network dependency.

Model: BAAI/bge-small-en-v1.5
Vector dimensions: 384

If you change the model, update VECTOR_SIZE to match and recreate
existing Qdrant collections (the store handles dimension mismatch automatically).
"""

from fastembed import TextEmbedding

# Vector size produced by this model.
# MUST match VECTOR_SIZE in src/helpers/qdrant/collection.py.
VECTOR_SIZE = 384
MODEL_NAME = "BAAI/bge-small-en-v1.5"


class EmbeddingClient:
    """
    Local embedding client backed by FastEmbed.

    Lazy-initializes the model on first use (downloads once, cached locally).
    """

    def __init__(self):
        self._model: TextEmbedding | None = None

    @property
    def model(self) -> TextEmbedding:
        if self._model is None:
            print(f"⏳ Loading embedding model: {MODEL_NAME} ...")
            self._model = TextEmbedding(MODEL_NAME)
            print("✅ Embedding model loaded")
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts. Returns list of float vectors."""
        embeddings = list(self.model.embed(texts))
        return [emb.tolist() for emb in embeddings]

    @staticmethod
    def vector_size() -> int:
        return VECTOR_SIZE
