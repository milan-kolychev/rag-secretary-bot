"""Точка интеграции с существующим API: RAG_ENGINE=worker.rag:create_engine."""

import logging
from threading import BoundedSemaphore
from typing import Protocol

import httpx

from api.engine import RagAnswer, RagUnavailableError
from api.schemas import Source
from worker.config import WorkerConfig
from worker.embedder import BgeM3Embedder
from worker.llm import QwenClient
from worker.store import ChunkHit, DenseStore


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> list[list[float]]: ...


class Store(Protocol):
    def search(self, vector: list[float], limit: int = 20) -> list[ChunkHit]: ...


class LLM(Protocol):
    def generate(
        self, question: str, fragments: list[str], history: list[dict[str, str]]
    ) -> str: ...


class RagPipeline:
    def __init__(self, embedder: Embedder, store: Store, llm: LLM, config: WorkerConfig):
        self.embedder = embedder
        self.store = store
        self.llm = llm
        self.config = config
        # Один запрос на GPU, иначе модель может вылететь из VRAM.
        self._slot = BoundedSemaphore(1)

    def answer(self, question: str) -> RagAnswer:
        return self.answer_with_history(question, [])

    def close(self):
        self.llm._client.close()
        self.store.client.close()
        if self.store.db:
            self.store.db.engine.dispose()

    def answer_with_history(self, question: str, history: list[dict[str, str]]) -> RagAnswer:
        # Defence for direct callers; the API owns the bounded durable FIFO queue.
        if not self._slot.acquire(blocking=False):
            raise RagUnavailableError("RAG model is busy")
        try:
            try:
                query = "\n".join(
                    [question] + [m["content"] for m in reversed(history) if m["role"] == "user"]
                )
                vector = self.embedder.encode([query])[0]
                hits = self.store.search(vector, self.config.retrieval_limit)
                # Порог 0.60 — временный для демо, НЕ процент уверенности.
                hits = [h for h in hits if h.score >= self.config.min_dense_score]
                # Убираем повторяющиеся фрагменты, не подменяя ранжирование.
                unique = []
                seen = set()
                for hit in hits:
                    key = (hit.doc_id, hit.text)
                    if key not in seen:
                        unique.append(hit)
                        seen.add(key)
                    if len(unique) >= self.config.prompt_chunks:
                        break
                if not unique:
                    return RagAnswer(status="no_answer")
                fragments = [
                    f"[{i}] Документ: {h.title}; раздел: {h.section or '-'}\n{h.text}"
                    for i, h in enumerate(unique, 1)
                ]
                logging.getLogger(__name__).info(
                    "retrieved=%d documents=%s",
                    len(unique),
                    [(str(h.doc_id), h.version) for h in unique],
                )
                text = self.llm.generate(question, fragments, history)
                if not text or "NO_ANSWER" in text.upper():
                    return RagAnswer(status="no_answer")
                sources = []
                used_fragments = getattr(self.llm, "used_fragments", fragments)
                unique = [
                    hit
                    for hit, fragment in zip(unique, fragments, strict=True)
                    if fragment in used_fragments
                ]
                logging.getLogger(__name__).info(
                    "used_documents=%s", [(str(h.doc_id), h.version) for h in unique]
                )
                used_doc_ids = set()
                for hit in unique:
                    if hit.doc_id not in used_doc_ids:
                        sources.append(
                            Source(
                                document_id=hit.doc_id,
                                title=hit.title,
                                section=hit.section,
                            )
                        )
                        used_doc_ids.add(hit.doc_id)
                return RagAnswer(status="answered", text=text, sources=sources)
            except RagUnavailableError:
                raise
            except (httpx.HTTPError, ConnectionError, TimeoutError) as exc:
                raise RagUnavailableError(f"RAG dependency: {type(exc).__name__}") from None
        finally:
            self._slot.release()


def create_engine() -> RagPipeline:
    """Фабрика без аргументов, требуемая api.engine.load_engine."""
    cfg = WorkerConfig()
    from core.db import Database

    if not cfg.database_url:
        raise ValueError("DATABASE_URL is required for the real RAG engine")
    embedder = BgeM3Embedder(cfg.embed_device)
    store = DenseStore(cfg.qdrant_url, cfg.qdrant_collection, Database(cfg.database_url))
    llm = QwenClient(cfg.ollama_url, cfg.ollama_model, cfg.num_ctx, cfg.num_predict, config=cfg)
    return RagPipeline(embedder, store, llm, cfg)
