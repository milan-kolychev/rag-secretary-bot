"""BGE-M3, dense-only retrieval. Одна модель и для индексации, и для поиска."""

from threading import Lock


class BgeM3Embedder:
    DIMENSION = 1024

    def __init__(self, device: str = "cpu") -> None:
        # Тяжёлый импорт делаем только при создании настоящего движка.
        from FlagEmbedding import BGEM3FlagModel

        self._model = BGEM3FlagModel(
            "BAAI/bge-m3",
            devices=device,
            use_fp16=device.startswith("cuda"),
        )
        self._lock = Lock()

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with self._lock:
            result = self._model.encode(
                texts,
                batch_size=4,
                max_length=1024,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
        vectors = result["dense_vecs"].tolist()
        if any(len(vec) != self.DIMENSION for vec in vectors):
            raise ValueError("BGE-M3 returned a vector with incorrect dimension")
        return vectors
