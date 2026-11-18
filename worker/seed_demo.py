"""Только для локального демо: создать коллекцию и один пример документа."""

import uuid

from qdrant_client import QdrantClient, models

from worker.config import WorkerConfig
from worker.embedder import BgeM3Embedder


def main() -> None:
    cfg = WorkerConfig()
    if cfg.qdrant_collection != "fpi_demo":
        raise RuntimeError("Demo indexing permitted only for fpi_demo collection")
    store = QdrantClient(url=cfg.qdrant_url, timeout=10)
    if not store.collection_exists(cfg.qdrant_collection):
        store.create_collection(
            collection_name=cfg.qdrant_collection,
            vectors_config={
                "dense": models.VectorParams(size=1024, distance=models.Distance.COSINE)
            },
        )
    fragment = "Учебные справки выдаются в деканате по будням с 10:00 до 15:00."
    vector = BgeM3Embedder(cfg.embed_device).encode([fragment])[0]
    doc_id = uuid.uuid5(uuid.NAMESPACE_URL, "fpi-rag-demo:spravki")
    point_id = uuid.uuid5(doc_id, "1:0")
    store.upsert(
        collection_name=cfg.qdrant_collection,
        points=[
            models.PointStruct(
                id=str(point_id),
                vector={"dense": vector},
                payload={
                    "doc_id": str(doc_id),
                    "title": "Учебные справки (ДЕМО)",
                    "version": 1,
                    "section": "Порядок выдачи",
                    "text": fragment,
                    "source": "demo",
                    "page": 1,
                    "is_active": True,
                    "chunk_index": 0,
                },
            )
        ],
    )
    print("Демо-фрагмент записан в Qdrant collection=fpi_demo")


if __name__ == "__main__":
    main()
