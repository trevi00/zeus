from __future__ import annotations


class LocalEmbeddings:
    """Lazy CPU ONNX encoder; no model is loaded by an idle message consumer."""

    def __init__(self, cache_dir: str, model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
        self.cache_dir, self.model_name = cache_dir, model_name
        self._model = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(self.model_name, cache_dir=self.cache_dir, threads=2)
        return [vector.tolist() for vector in self._model.embed(texts, batch_size=8)]
