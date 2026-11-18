"""Feature tests with in-memory persistence/vector substitutes and model mocks.

No external database, Telegram, Qdrant or Ollama server is contacted.
"""

import asyncio
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from qdrant_client import QdrantClient

from api.app import create_app
from api.config import ApiSettings
from api.engine import RagAnswer
from api.schemas import AskRequest
from bot import texts
from bot.handlers.question import _busy, handle_question
from bot.services.delivery import replace_progress
from core.db import ChatMessage, Database, now
from core.queue import QueueRejected, RequestQueue
from worker.config import WorkerConfig
from worker.documents import DocumentService
from worker.prompt import PromptBuilder
from worker.rag import RagPipeline
from worker.store import DenseStore


@pytest.fixture
def db():
    database = Database()
    yield database
    database.engine.dispose()


class ScriptedEngine:
    def __init__(self):
        self.seen = []

    def answer_with_history(self, question, history):
        self.seen.append((question, history))
        answers = {
            "Когда начинается зимняя сессия?": "Сессия начинается 12 января.",
            "А когда она заканчивается?": "Сессия заканчивается 26 января.",
            "А пересдачи?": "Пересдачи после сессии.",
        }
        return RagAnswer(status="answered", text=answers.get(question, "Ответ"))


def settings(**kwargs):
    return ApiSettings(_env_file=None, api_token="test", **kwargs)


def enqueue(queue, user, question="question", chat=1):
    return queue.submit(AskRequest(question=question, user_id=user, chat_id=chat))


def test_history_followups_isolation_retention_and_restart(db):
    engine = ScriptedEngine()
    queue = RequestQueue(db, settings(), engine)
    for question in (
        "Когда начинается зимняя сессия?",
        "А когда она заканчивается?",
        "А пересдачи?",
    ):
        job = enqueue(queue, 1, question)
        queue.process_one()
        queue.acknowledge(job)
    assert engine.seen[1][1] == [
        {"role": "user", "content": "Когда начинается зимняя сессия?"},
        {"role": "assistant", "content": "Сессия начинается 12 января."},
    ]
    assert len(engine.seen[2][1]) == 4
    restarted = RequestQueue(db, settings(), ScriptedEngine())
    assert len(restarted.history(1, 1)) == 5  # messages, not pairs
    assert restarted.history(1, 2) == []
    assert restarted.history(2, 1) == []
    with db.sessions.begin() as session:
        session.add(
            ChatMessage(
                chat_id=1,
                user_id=2,
                role="user",
                content="expired",
                created_at=now() - timedelta(hours=49),
            )
        )
    assert restarted.history(1, 2) == []
    enqueue(restarted, 3)
    with db.sessions() as session:
        assert not list(session.query(ChatMessage).filter_by(content="expired"))


def test_fifo_spam_capacity_and_error_recovery(db):
    order = []

    class Engine:
        def answer(self, question):
            order.append(question)
            if question == "fail":
                raise ValueError("private data must not be logged")
            return RagAnswer(status="no_answer")

    queue = RequestQueue(db, settings(queue_max_size=3), Engine())
    first = enqueue(queue, 1, "first")
    for _ in range(3):
        with pytest.raises(QueueRejected) as exc:
            enqueue(queue, 1)
        assert exc.value.code == "conflict"
    second = enqueue(queue, 2, "fail")
    third = enqueue(queue, 3, "third")
    with pytest.raises(QueueRejected) as exc:
        enqueue(queue, 4)
    assert exc.value.code == "queue_full"
    for _ in range(3):
        assert queue.process_one()
    assert order == ["first", "fail", "third"]
    assert queue.get(second)["state"] == "failed"
    assert queue.get(third)["state"] == "done"
    with pytest.raises(QueueRejected):
        enqueue(queue, 1)  # locked until final Telegram delivery
    queue.acknowledge(first)
    enqueue(queue, 1)


def test_timeout_never_overlaps_generation(db):
    entered, release = threading.Event(), threading.Event()

    class Engine:
        def answer(self, question):
            entered.set()
            release.wait(3)
            return RagAnswer(status="no_answer")

    queue = RequestQueue(db, settings(rag_timeout=0.03), Engine())
    first = enqueue(queue, 1)
    enqueue(queue, 2)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(queue.process_one)
        assert entered.wait(2)
        try:
            deadline = time.monotonic() + 2
            while queue.get(first)["state"] != "failed" and time.monotonic() < deadline:
                time.sleep(0.01)
            assert queue.get(first)["error"] == "rag_timeout"
            assert not queue.process_one()  # timed-out thread still owns execution lock
        finally:
            release.set()
        future.result()
    assert queue.process_one()


def test_parallel_consumers_and_atomic_admission(db):
    seen = []
    active = 0
    peak = 0

    class Engine:
        def answer(self, question):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            seen.append(question)
            time.sleep(0.02)
            active -= 1
            return RagAnswer(status="no_answer")

    one = RequestQueue(db, settings(), Engine())
    two = RequestQueue(db, settings(), one.engine)
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: _try_submit(one), range(4)))
    assert outcomes.count("accepted") == 1
    for user in range(2, 7):
        enqueue(one, user, str(user))
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda q: [q.process_one() for _ in range(10)], [one, two]))
    assert peak == 1
    assert seen == ["question", "2", "3", "4", "5", "6"]


def _try_submit(queue):
    try:
        enqueue(queue, 1)
        return "accepted"
    except QueueRejected:
        return "rejected"


class SmallTokenizer:
    """Deterministic test double; real Qwen test below is explicitly separate."""

    def encode(self, text, add_special_tokens=False):
        return list(text.encode("utf-8"))

    def decode(self, ids, skip_special_tokens=True):
        return bytes(ids).decode("utf-8", errors="ignore")

    def apply_chat_template(self, messages, **kwargs):
        return "".join(f"<{m['role']}>{m['content']}</end>" for m in messages) + "<assistant>"


def test_prompt_budget_history_first_and_question_preserved():
    cfg = WorkerConfig(
        _env_file=None,
        num_ctx=1024,
        num_predict=256,
        chat_history_max_tokens=900,
        rag_context_max_tokens=900,
    )
    builder = PromptBuilder(SmallTokenizer(), cfg)
    history = [
        {"role": "user", "content": "old" * 40},
        {"role": "assistant", "content": "new" * 40},
    ]
    prompt = builder.prepare("system", history, "CURRENT", ["A" * 400, "B" * 100])
    assert prompt.tokens <= 768
    assert "CURRENT" in prompt.text and "system" in prompt.text
    assert "old" not in prompt.text
    assert prompt.fragments[0] == "A" * 400
    limited = PromptBuilder(SmallTokenizer(), cfg.model_copy(update={"chat_history_messages": 5}))
    result = limited.prepare(
        "system", [{"role": "user", "content": str(i)} for i in range(8)], "CURRENT", ["A"]
    )
    assert result.history_count == 5


def test_real_qwen_tokenizer():
    path = os.getenv("TEST_QWEN_TOKENIZER")
    if not path:
        pytest.skip("Set TEST_QWEN_TOKENIZER to downloaded official tokenizer (no weights)")
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
    builder = PromptBuilder(tokenizer, WorkerConfig(_env_file=None))
    history = [
        {"role": "user", "content": "Когда начинается зимняя сессия?"},
        {"role": "assistant", "content": "12 января."},
    ]
    prompt = builder.prepare(
        "Answer using documents.",
        history,
        "А когда заканчивается?",
        ["Сессия заканчивается 26 января."],
    )
    assert prompt.tokens == len(tokenizer.encode(prompt.text, add_special_tokens=False))
    assert "<|im_start|>" in prompt.text
    assert prompt.text.endswith("<think>\n\n</think>\n\n")
    assert prompt.tokens + 256 <= 4096


def test_ollama_uses_exact_rendered_prompt_and_statistics(caplog):
    import logging

    from worker.llm import QwenClient

    cfg = WorkerConfig(_env_file=None)
    tokenizer = SmallTokenizer()
    llm = QwenClient("http://ollama", "qwen3.5:9b", 4096, 256, tokenizer=tokenizer, config=cfg)
    bodies = []

    def respond(request):
        import json

        bodies.append(json.loads(request.content))
        return httpx.Response(
            200, json={"response": "26 января", "prompt_eval_count": 123, "eval_count": 9}
        )

    llm._client.close()
    llm._client = httpx.Client(transport=httpx.MockTransport(respond))
    with caplog.at_level(logging.INFO):
        result = llm.generate(
            "А когда заканчивается?",
            ["До 26 января"],
            [{"role": "user", "content": "Когда зимняя сессия?"}],
        )
    assert result == "26 января"
    body = bodies[0]
    assert body["raw"] and body["think"] is False
    assert "Когда зимняя сессия?" in body["prompt"]
    assert body["options"]["num_ctx"] == 4096
    assert body["options"]["num_predict"] == 256
    assert "prompt_eval_count=123 eval_count=9" in caplog.text
    assert "Когда зимняя сессия?" not in caplog.text
    llm._client.close()


def test_postgresql_advisory_lock_with_connection_mock():
    database = Database.__new__(Database)
    database.engine = MagicMock()
    database.engine.dialect.name = "postgresql"
    connection = database.engine.connect.return_value
    connection.scalar.return_value = True
    with pytest.raises(ValueError), database.lock(71002):
        raise ValueError("test")
    assert "pg_try_advisory_lock" in str(connection.scalar.call_args.args[0])
    assert "pg_advisory_unlock" in str(connection.execute.call_args.args[0])
    connection.close.assert_called_once()
    connection.reset_mock()
    connection.scalar.return_value = False
    with database.lock(71002, blocking=False) as acquired:
        assert not acquired
    connection.close.assert_called_once()
    connection.execute.assert_not_called()


def test_migration_structure_without_database():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "initial_migration", Path(__file__).parents[1] / "migrations/versions/0001_persistence.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with patch.object(migration, "op") as operations:
        migration.upgrade()
    tables = {call.args[0]: call.args[1:] for call in operations.create_table.call_args_list}
    assert set(tables) == {"chat_messages", "request_jobs", "documents", "document_versions"}
    assert "acknowledged" in {column.name for column in tables["request_jobs"]}
    assert any(
        call.args[0] == "uq_request_jobs_busy" for call in operations.create_index.call_args_list
    )


def test_cancelled_queued_and_acknowledged_running_request(db):
    entered, release = threading.Event(), threading.Event()

    class Engine:
        def answer(self, question):
            entered.set()
            release.wait(2)
            return RagAnswer(status="no_answer")

    queue = RequestQueue(db, settings(), Engine())
    cancelled = enqueue(queue, 1)
    queue.acknowledge(cancelled)
    assert queue.get(cancelled)["state"] == "cancelled"
    running = enqueue(queue, 1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(queue.process_one)
        assert entered.wait(2)
        try:
            queue.acknowledge(running)
            with pytest.raises(QueueRejected):
                enqueue(queue, 1)
        finally:
            release.set()
        future.result()
    enqueue(queue, 1)


def test_large_emoji_answers_respect_telegram_utf16_limit():
    from bot.formatting import split_message

    text = "🙂" * 5000
    parts = split_message(text)
    assert "".join(parts) == text
    assert all(len(part.encode("utf-16-le")) // 2 <= 4096 for part in parts)


class Embedder:
    fail = False

    def encode(self, texts):
        if self.fail:
            raise RuntimeError("test indexing failure")
        return [[1.0] + [0.0] * 1023 for _ in texts]


def document_service(db):
    store = DenseStore("http://unused", "isolated_test", db, client=QdrantClient(":memory:"))
    return DocumentService(db, store, Embedder(), SmallTokenizer())


def test_document_versions_search_failure_dedup_and_restore(db):
    service = document_service(db)
    v1 = service.upload("Каникулы начинаются 28 декабря".encode(), "holidays.txt", "Каникулы")
    doc_id = v1["document_id"]
    vector = Embedder().encode(["question"])[0]
    assert "28 декабря" in service.store.search(vector)[0].text
    v2 = service.upload(
        "Каникулы начинаются 30 декабря".encode(), "holidays.txt", "Каникулы", doc_id
    )
    assert v2["version"] == 2 and v2["is_active"]
    hits = service.store.search(vector)
    assert len(hits) == 1 and "30 декабря" in hits[0].text
    assert all("28 декабря" not in hit.text for hit in hits)

    class LLM:
        def generate(self, question, fragments, history):
            assert "30 декабря" in "".join(fragments)
            assert "28 декабря" not in "".join(fragments)
            return "Каникулы начинаются 30 декабря."

    rag = RagPipeline(service.embedder, service.store, LLM(), WorkerConfig(_env_file=None))
    assert "30 декабря" in rag.answer("Когда начинаются зимние каникулы?").text
    assert (
        service.upload("Каникулы начинаются 30 декабря".encode(), "other.txt", "same", doc_id)[
            "version"
        ]
        == 2
    )
    service.embedder.fail = True
    failed = service.upload(b"new date", "holidays.txt", "Каникулы", doc_id)
    assert failed["status"] == "failed"
    assert service.versions(doc_id)["active_version"] == 2
    assert "30 декабря" in service.store.search(vector)[0].text
    service.embedder.fail = False
    retry = service.upload(b"new date", "holidays.txt", "Каникулы", doc_id)
    assert retry["version"] == 3 and retry["status"] == "indexed"
    service.restore(doc_id, 1)
    assert "28 декабря" in service.store.search(vector)[0].text
    # Same filename without doc_id creates a separate logical document.
    assert service.upload(b"different", "holidays.txt", "Other")["document_id"] != doc_id
    service.store.client.close()


def test_staged_chunks_and_stale_flags_never_override_sql_version(db):
    service = document_service(db)
    first = service.upload(b"old official date", "calendar.txt", "Calendar")
    doc_id = first["document_id"]
    original_encode = service.embedder.encode
    calls = 0

    def fail_after_first_batch(texts):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("partial indexing failure")
        return original_encode(texts)

    service.embedder.encode = fail_after_first_batch
    result = service.upload(b"staging text " * 250, "calendar.txt", "Calendar", doc_id)
    assert result["status"] == "failed"
    assert service.versions(doc_id)["active_version"] == 1
    vector = original_encode(["question"])[0]
    assert [hit.text for hit in service.store.search(vector)] == ["old official date"]
    service.embedder.encode = original_encode
    # Simulate a cleanup failure AFTER successful SQL activation.
    with patch.object(service, "_reconcile", side_effect=RuntimeError("cleanup failed")):
        repaired = service.retry(doc_id, 2)
    assert repaired["status"] == "indexed" and repaired["is_active"]
    hits = service.store.search(vector)
    assert hits and all(hit.version == 2 for hit in hits)
    assert all("old official date" not in hit.text for hit in hits)
    with (
        patch.object(service, "_index", side_effect=RuntimeError("restore failed")),
        pytest.raises(RuntimeError),
    ):
        service.restore(doc_id, 1)
    assert service.versions(doc_id)["active_version"] == 2
    duplicate_old = service.upload(b"old official date", "calendar.txt", "Calendar", doc_id)
    assert duplicate_old["version"] == 1 and not duplicate_old["is_active"]
    assert service.versions(doc_id)["active_version"] == 2
    service.store.client.close()


async def test_async_api_admission_poll_delivery_and_documents(db):
    service = document_service(db)
    app = create_app(settings(), ScriptedEngine(), database=db, documents=service)
    async with app.router.lifespan_context(app):  # noqa: SIM117 - keep lifecycle scope explicit
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer test"},
        ) as client:
            job = (
                await client.post(
                    "/requests", json={"question": "q", "user_id": 1, "chat_id": -100}
                )
            ).json()["request_id"]
            assert (
                await client.post(
                    "/requests", json={"question": "q2", "user_id": 1, "chat_id": -100}
                )
            ).status_code == 409
            for _ in range(200):
                response = await client.get(f"/requests/{job}")
                if response.json()["state"] == "done":
                    break
                await asyncio.sleep(0.01)
            assert response.json()["result"]["text"] == "Ответ"
            assert (await client.delete(f"/requests/{job}")).status_code == 204
            upload = await client.post(
                "/documents", data={"title": "Test"}, files={"file": ("test.txt", b"document")}
            )
            assert upload.status_code == 201
            doc_id = upload.json()["document_id"]
            versions = await client.get(f"/documents/{doc_id}/versions")
            assert versions.json()["active_version"] == 1
            assert (
                await client.post(
                    "/documents",
                    headers={"Authorization": "Bearer wrong"},
                    data={"title": "Test"},
                    files={"file": ("test.txt", b"document")},
                )
            ).status_code == 401
    service.store.client.close()


async def test_bot_four_messages_only_one_generation_and_unlock():
    from bot.config import Settings

    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    class Client:
        async def ask(self, question, user_id):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            raise TimeoutError()

    def message():
        msg = AsyncMock()
        msg.text, msg.chat.id, msg.from_user.id = "question", 1, 1
        return msg

    bot, state = AsyncMock(), AsyncMock()
    bot.id = 42
    cfg = Settings(_env_file=None, bot_token="42:TEST")
    first = message()
    task = asyncio.create_task(handle_question(first, state, bot, Client(), cfg))
    await entered.wait()
    extras = [message() for _ in range(3)]
    await asyncio.gather(*(handle_question(m, state, bot, Client(), cfg) for m in extras))
    assert calls == 1
    assert sum(m.answer.await_count for m in extras) == 1
    release.set()
    await task
    assert not _busy
    first.answer.return_value.edit_text.assert_awaited_with(texts.ANSWER_ERROR)
    await handle_question(message(), state, bot, Client(), cfg)
    assert calls == 2 and not _busy


async def test_telegram_edit_failure_falls_back_and_removes_progress():
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import EditMessageText

    progress, original = AsyncMock(), AsyncMock()
    progress.edit_text.side_effect = TelegramBadRequest(
        method=EditMessageText(text="answer"), message="message can't be edited"
    )
    await replace_progress(progress, original, "answer")
    progress.delete.assert_awaited_once()
    original.answer.assert_awaited_once_with("answer")
