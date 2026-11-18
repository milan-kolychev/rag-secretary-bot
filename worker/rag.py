"""Точка интеграции с существующим API: RAG_ENGINE=worker.rag:create_engine."""

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
    def generate(self, question: str, fragments: str) -> str: ...


class RagPipeline:
    def __init__(self, embedder: Embedder, store: Store, llm: LLM, config: WorkerConfig):
        self.embedder = embedder
        self.store = store
        self.llm = llm
        self.config = config
        # Один запрос на GPU, иначе модель может вылететь из VRAM.
        self._slot = BoundedSemaphore(1)

    def answer(self, question: str) -> RagAnswer:
        # Не ставим неограниченную очередь: API рассчитан на синхронные ответы.
        if not self._slot.acquire(blocking=False):
            raise RagUnavailableError("RAG model is busy")
        try:
            try:
                vector = self.embedder.encode([question])[0]
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
                fragments = "\n\n".join(
                    f"[{i}] Документ: {h.title}; раздел: {h.section or '-'}\n{h.text}"
                    for i, h in enumerate(unique, 1)
                )
                text = self.llm.generate(question, fragments)
                if not text or "NO_ANSWER" in text.upper():
                    return RagAnswer(status="no_answer")
                sources = []
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
    embedder = BgeM3Embedder(cfg.embed_device)
    store = DenseStore(cfg.qdrant_url, cfg.qdrant_collection)
    llm = QwenClient(cfg.ollama_url, cfg.ollama_model, cfg.num_ctx, cfg.num_predict)
    return RagPipeline(embedder, store, llm, cfg)
