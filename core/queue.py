"""Durable FIFO queue; advisory lock covers the entire non-cancellable GPU call."""

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import timedelta

from sqlalchemy import delete, func, select, update

from api.engine import RagAnswer, RagUnavailableError
from api.schemas import AskResponse
from core.db import ChatMessage, Job, now

logger = logging.getLogger(__name__)


class QueueRejected(Exception):
    def __init__(self, code):
        self.code = code


class RequestQueue:
    def __init__(self, db, settings, engine):
        self.db, self.settings, self.engine = db, settings, engine

    def submit(self, request):
        chat_id = request.chat_id if request.chat_id is not None else request.user_id
        with self.db.lock(71001), self.db.sessions.begin() as session:
            self._cleanup(session)
            busy = session.scalar(
                select(Job).where(
                    Job.chat_id == chat_id, Job.user_id == request.user_id, Job.busy.is_(True)
                )
            )
            if busy:
                raise QueueRejected("conflict")
            count = session.scalar(
                select(func.count()).select_from(Job).where(Job.state.in_(["queued", "running"]))
            )
            if count >= self.settings.queue_max_size:
                raise QueueRejected("queue_full")
            job = Job(
                id=str(uuid.uuid4()),
                chat_id=chat_id,
                user_id=request.user_id,
                question=request.question,
            )
            session.add(job)
            session.flush()
            return job.id

    def _cleanup(self, session):
        cutoff = now() - timedelta(hours=self.settings.chat_history_retention_hours)
        session.execute(delete(ChatMessage).where(ChatMessage.created_at < cutoff))
        # Terminal jobs are delivery leases, so a crashed bot cannot leave a user busy forever.
        expired = now() - timedelta(seconds=self.settings.delivery_timeout)
        session.execute(
            update(Job).where(Job.busy.is_(True), Job.finished_at < expired).values(busy=False)
        )
        # Questions/results are personal data too: apply the same retention policy.
        session.execute(delete(Job).where(Job.busy.is_(False), Job.created_at < cutoff))

    def get(self, job_id):
        with self.db.sessions() as session:
            job = session.scalar(select(Job).where(Job.id == str(job_id)))
            if job is None:
                return None
            return {
                "request_id": job.id,
                "state": job.state,
                "result": job.result,
                "error": job.error,
            }

    def acknowledge(self, job_id):
        with self.db.lock(71001), self.db.sessions.begin() as session:
            job = session.scalar(select(Job).where(Job.id == str(job_id)))
            if job:
                job.acknowledged = True
                if job.state == "queued":
                    job.state, job.finished_at = "cancelled", now()
                # Running inference cannot be killed safely; retain its lock until completion.
                if job.state != "running":
                    job.busy = False

    def history(self, chat_id, user_id):
        if not self.settings.chat_history_messages:
            return []
        with self.db.sessions() as session:
            rows = list(
                session.scalars(
                    select(ChatMessage)
                    .where(
                        ChatMessage.chat_id == chat_id,
                        ChatMessage.user_id == user_id,
                        ChatMessage.created_at
                        >= now() - timedelta(hours=self.settings.chat_history_retention_hours),
                    )
                    .order_by(ChatMessage.id.desc())
                    .limit(self.settings.chat_history_messages)
                )
            )
            return [{"role": row.role, "content": row.content} for row in reversed(rows)]

    def _answer(self, job):
        history = self.history(job.chat_id, job.user_id)
        contextual = getattr(self.engine, "answer_with_history", None)
        raw = contextual(job.question, history) if contextual else self.engine.answer(job.question)
        result = RagAnswer.model_validate(raw, from_attributes=True)
        answered = result.status == "answered"
        return AskResponse(
            answer_id=uuid.UUID(job.id),
            status=result.status,
            text=result.text if answered else "",
            sources=result.sources if answered else [],
            ticket_id=None,
        )

    def process_one(self):
        with self.db.lock(71002, blocking=False) as acquired:
            if not acquired:
                return False
            with self.db.lock(71001), self.db.sessions.begin() as session:
                self._cleanup(session)
                # Holding the global execution lock proves no previous owner is alive.
                # Never blindly rerun a job with an ambiguous generation outcome.
                for orphan in session.scalars(select(Job).where(Job.state == "running")):
                    orphan.state, orphan.error = "failed", "rag_unavailable"
                    orphan.finished_at, orphan.busy = now(), False
                job = session.scalar(
                    select(Job).where(Job.state == "queued").order_by(Job.sequence).limit(1)
                )
                if job is None:
                    return False
                job.state = "running"
            started = time.monotonic()
            logger.info(
                "request=%s queue_wait_seconds=%.3f",
                job.id,
                (now() - job.created_at).total_seconds(),
            )
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self._answer, job)
                try:
                    answer = future.result(timeout=self.settings.rag_timeout)
                    with self.db.sessions.begin() as session:
                        saved = session.get(Job, job.sequence)
                        saved.result = answer.model_dump(mode="json")
                        saved.state, saved.finished_at = "done", now()
                        if saved.acknowledged:
                            saved.busy = False
                        # Store both sides atomically, never a half-written exchange.
                        session.add(
                            ChatMessage(
                                chat_id=job.chat_id,
                                user_id=job.user_id,
                                role="user",
                                content=job.question,
                            )
                        )
                        session.add(
                            ChatMessage(
                                chat_id=job.chat_id,
                                user_id=job.user_id,
                                role="assistant",
                                content=answer.text or "В документах нет ответа.",
                            )
                        )
                except Exception as exc:
                    code = (
                        "rag_timeout"
                        if isinstance(exc, FutureTimeout)
                        else "rag_unavailable"
                        if isinstance(exc, RagUnavailableError)
                        else "internal_error"
                    )
                    logger.warning(
                        "request=%s user_id=%s error=%s", job.id, job.user_id, type(exc).__name__
                    )
                    with self.db.sessions.begin() as session:
                        saved = session.get(Job, job.sequence)
                        saved.state, saved.error, saved.finished_at = "failed", code, now()
                        saved.busy = False
                # Executor shutdown waits even after timeout. Do not release advisory lock
                # while a Python thread may still be touching the GPU.
            logger.info("request=%s processing_seconds=%.3f", job.id, time.monotonic() - started)
            return True
