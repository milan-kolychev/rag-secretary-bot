import logging
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot import texts
from bot.config import Settings
from bot.formatting import MESSAGE_LIMIT
from bot.handlers.question import handle_question
from bot.keyboards import answer_keyboard, secretary_keyboard
from bot.services.answer_client import Answer, AnswerTimeoutError, Source
from bot.states import QuestionFlow

QUESTION = "Когда пересдача по матанализу?"


class FakeClient:
    def __init__(self, answer: Answer | None = None, error: Exception | None = None) -> None:
        self.answer = answer
        self.error = error
        self.questions: list[tuple[str, int]] = []

    async def ask(self, question: str, user_id: int) -> Answer:
        self.questions.append((question, user_id))
        if self.error:
            raise self.error
        assert self.answer is not None
        return self.answer


def make_answer(**kwargs: object) -> Answer:
    fields: dict[str, object] = {
        "answer_id": "a1",
        "text": "Пересдача в феврале.",
        "sources": [Source(title="График пересдач")],
        "status": "answered",
    }
    fields.update(kwargs)
    return Answer.model_validate(fields)


def make_message(text: str | None) -> AsyncMock:
    message = AsyncMock()
    message.text = text
    message.chat.id = 1
    message.from_user.id = 1
    return message


@pytest.fixture
async def state() -> FSMContext:
    context = FSMContext(MemoryStorage(), StorageKey(bot_id=42, chat_id=1, user_id=1))
    await context.set_state(QuestionFlow.waiting_question)
    return context


@pytest.fixture
def bot() -> AsyncMock:
    bot = AsyncMock()
    bot.id = 42
    return bot


async def test_answer_is_sent(state: FSMContext, bot: AsyncMock, settings: Settings) -> None:
    message = make_message(f"  {QUESTION}  ")
    client = FakeClient(answer=make_answer())

    await handle_question(message, state, bot, client, settings)

    assert client.questions == [(QUESTION, 1)]
    message.answer.assert_awaited_once()
    message.answer.assert_awaited_once_with(texts.PROCESSING)
    edited = message.answer.return_value.edit_text
    text = edited.await_args.args[0]
    assert text.startswith("Пересдача в феврале.")
    assert texts.SOURCES_HEADER in text
    assert edited.await_args.kwargs["reply_markup"] == answer_keyboard("a1")
    assert await state.get_state() is None


async def test_long_answer_is_split(state: FSMContext, bot: AsyncMock, settings: Settings) -> None:
    message = make_message(QUESTION)
    client = FakeClient(answer=make_answer(text="абзац\n\n" * MESSAGE_LIMIT))

    await handle_question(message, state, bot, client, settings)

    calls = message.answer.await_args_list
    assert len(calls) > 1
    assert all("reply_markup" not in call.kwargs for call in calls[:-1])
    assert calls[-1].kwargs["reply_markup"] == answer_keyboard("a1")


async def test_no_answer(state: FSMContext, bot: AsyncMock, settings: Settings) -> None:
    message = make_message(QUESTION)
    client = FakeClient(answer=make_answer(status="no_answer", text="", sources=[]))

    await handle_question(message, state, bot, client, settings)

    message.answer.return_value.edit_text.assert_awaited_once_with(
        texts.NO_ANSWER, reply_markup=secretary_keyboard("a1")
    )


async def test_escalated(state: FSMContext, bot: AsyncMock, settings: Settings) -> None:
    message = make_message(QUESTION)
    client = FakeClient(answer=make_answer(status="escalated", text="", sources=[]))

    await handle_question(message, state, bot, client, settings)

    message.answer.return_value.edit_text.assert_awaited_once_with(texts.ESCALATED)


async def test_invalid_question_keeps_state(
    state: FSMContext, bot: AsyncMock, settings: Settings
) -> None:
    message = make_message("   ")
    client = FakeClient(answer=make_answer())

    await handle_question(message, state, bot, client, settings)

    message.answer.assert_awaited_once_with(texts.EMPTY_QUESTION)
    assert client.questions == []
    assert await state.get_state() == QuestionFlow.waiting_question


async def test_client_error(
    state: FSMContext, bot: AsyncMock, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    message = make_message(QUESTION)
    client = FakeClient(error=AnswerTimeoutError("no response in 30 s"))

    with caplog.at_level(logging.DEBUG):
        await handle_question(message, state, bot, client, settings)

    message.answer.return_value.edit_text.assert_awaited_once_with(texts.ANSWER_ERROR)
    assert await state.get_state() == QuestionFlow.waiting_question
    assert "AnswerTimeoutError" in caplog.text
    assert "user_id=1" in caplog.text
    assert QUESTION not in caplog.text


async def test_unexpected_error(
    state: FSMContext, bot: AsyncMock, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    message = make_message(QUESTION)
    client = FakeClient(error=ValueError(f"cannot parse {QUESTION}"))

    with caplog.at_level(logging.DEBUG):
        await handle_question(message, state, bot, client, settings)

    message.answer.return_value.edit_text.assert_awaited_once_with(texts.ANSWER_ERROR)
    assert "ValueError" in caplog.text
    assert "test_question.py" in caplog.text  # traceback is logged
    assert QUESTION not in caplog.text
