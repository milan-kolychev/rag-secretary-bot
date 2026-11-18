"""Dense retrieval в Qdrant, только активные фрагменты."""

from dataclasses import dataclass
from uuid import UUID

from qdrant_client import QdrantClient, models
from sqlalchemy import select

from api.engine import RagUnavailableError
from core.db import Document


@dataclass(frozen=True)
class ChunkHit:
    doc_id: UUID
    title: str
    section: str | None
    text: str
    score: float
    version: int = 1


class DenseStore:
    def __init__(self, url: str, collection: str, db=None, *, client=None) -> None:
        self.client = client if client is not None else QdrantClient(url=url, timeout=5)
        self.collection = collection
        self.db = db

    def search(self, vector: list[float], limit: int = 20) -> list[ChunkHit]:
        if self.db is None:
            raise RagUnavailableError("Document metadata database is required")
        with self.db.lock(71003), self.db.sessions() as session:
            active = list(
                session.execute(
                    select(Document.id, Document.active_version).where(
                        Document.active_version.is_not(None)
                    )
                )
            )
            if not active:
                return []
            return self._search(vector, limit, active)

    def _search(self, vector, limit, active):
        try:
            response = self.client.query_points(
                collection_name=self.collection,
                query=vector,
                using="dense",
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(key="is_active", match=models.MatchValue(value=True))
                    ],
                    should=[
                        models.Filter(
                            must=[
                                models.FieldCondition(
                                    key="doc_id", match=models.MatchValue(value=doc_id)
                                ),
                                models.FieldCondition(
                                    key="version", match=models.MatchValue(value=version)
                                ),
                            ]
                        )
                        for doc_id, version in active
                    ],
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
                        version=int(p["version"]),
                    )
                )
            except (ValueError, TypeError, KeyError):
                # Не возвращаем невалидную или неполную точку как источник.
                continue
        return found
