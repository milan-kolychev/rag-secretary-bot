"""Dense retrieval в Qdrant, только активные фрагменты."""

from dataclasses import dataclass
from uuid import UUID

from qdrant_client import QdrantClient, models

from api.engine import RagUnavailableError


@dataclass(frozen=True)
class ChunkHit:
    doc_id: UUID
    title: str
    section: str | None
    text: str
    score: float


class DenseStore:
    def __init__(self, url: str, collection: str) -> None:
        self.client = QdrantClient(url=url, timeout=5)
        self.collection = collection

    def search(self, vector: list[float], limit: int = 20) -> list[ChunkHit]:
        try:
            response = self.client.query_points(
                collection_name=self.collection,
                query=vector,
                using="dense",
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="is_active", match=models.MatchValue(value=True)
                        )
                    ]
                ),
                with_payload=True,
                limit=limit,
            )
        except Exception as exc:
            # Сообщение исключения может содержать закрытые данные; пишем только тип.
            raise RagUnavailableError(f"Qdrant unavailable: {type(exc).__name__}") from None
        found = []
        for hit in response.points:
            p = hit.payload or {}
            try:
                found.append(
                    ChunkHit(
                        doc_id=UUID(str(p["doc_id"])),
                        title=str(p["title"]),
                        section=str(p["section"]) if p.get("section") else None,
                        text=str(p["text"]),
                        score=float(hit.score),
                    )
                )
            except (ValueError, TypeError, KeyError):
                # Не возвращаем невалидную или неполную точку как источник.
                continue
        return found
