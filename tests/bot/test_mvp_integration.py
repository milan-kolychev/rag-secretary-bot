"""MVP v1.0 (задача 12): бот через HTTP-клиент обращается к настоящему приложению API.

Сеть не используется: httpx отправляет запросы прямо в ASGI-приложение.
Вместо RAG-ядра участника A подключён движок с заранее заданными ответами.
"""

import uuid

import httpx
import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import InlineKeyboardMarkup

from api.app import create_app
from api.config import ApiSettings
from api.engine import RagAnswer, RagEngine, RagUnavailableError
from api.schemas import Source as ApiSource
from bot import texts
from bot.app import create_dispatcher
from bot.config import Settings
from bot.keyboards import Action, AnswerCallback
from bot.services.answer_client import AnswerClientError, AnswerUnavailableError
from bot.services.http_answer_client import HttpAnswerClient
from tests.bot.helpers import USER_ID, FakeSession, message_update

TOKEN = "integration-token"
DOC_ID = uuid.uuid4()


class ScriptedEngine:
    """Отвечает в зависимости от вопроса, как заглушка, но с настоящими источниками."""

    def __init__(self) -> None:
        self.questions: list[str] = []

    def answer(self, question: str) -> RagAnswer:
        self.questions.append(question)
        if "недоступ" in question:
            raise RagUnavailableError("llm is down")
        if "не знаю" in question:
            return RagAnswer(status="no_answer")
        return RagAnswer(
            status="answered",
            text="Справку об обучении выдаёт деканат в течение трёх рабочих дней.",
            sources=[ApiSource(document_id=DOC_ID, title="Регламент деканата", section="п. 4.2")],
        )


def http_client(engine: RagEngine, token: str = TOKEN) -> HttpAnswerClient:
    app = create_app(ApiSettings(_env_file=None, api_token=TOKEN), engine)
    return HttpAnswerClient("http://api", token, timeout=5, transport=httpx.ASGITransport(app=app))


async def test_client_gets_answer_from_api() -> None:
    engine = ScriptedEngine()
    answer = await http_client(engine).ask("Как получить справку?", USER_ID)
    assert answer.status == "answered"
    assert answer.sources[0].title == "Регламент деканата"
    assert uuid.UUID(answer.answer_id)
    assert engine.questions == ["Как получить справку?"]


async def test_no_answer_from_api() -> None:
    answer = await http_client(ScriptedEngine()).ask("Я не знаю, что спросить", USER_ID)
    assert (answer.status, answer.text, answer.sources) == ("no_answer", "", [])


async def test_engine_down_is_unavailable() -> None:
    with pytest.raises(AnswerUnavailableError, match="503 rag_unavailable"):
        await http_client(ScriptedEngine()).ask("Сервис недоступен?", USER_ID)


async def test_wrong_token_is_client_error() -> None:
    with pytest.raises(AnswerClientError, match="401 unauthorized"):
        await http_client(ScriptedEngine(), token="wrong").ask("Вопрос", USER_ID)


def bot_settings() -> Settings:
    return Settings(
        _env_file=None,
        bot_token="42:TEST",
        api_url="http://api",
        api_token=TOKEN,
    )


async def test_student_gets_answer_with_sources_and_buttons(bot: Bot, session: FakeSession) -> None:
    dp = create_dispatcher(bot_settings(), http_client(ScriptedEngine()))

    await dp.feed_update(bot, message_update("Как получить справку об обучении?"))

    (sent,) = [r for r in session.requests if isinstance(r, SendMessage)]
    assert sent.text.startswith("Справку об обучении выдаёт деканат")
    assert f"{texts.SOURCES_HEADER}\n• Регламент деканата, п. 4.2" in sent.text
    assert isinstance(sent.reply_markup, InlineKeyboardMarkup)
    buttons = [b for row in sent.reply_markup.inline_keyboard for b in row]
    assert [b.text for b in buttons] == [
        texts.LIKE_BUTTON,
        texts.DISLIKE_BUTTON,
        texts.SECRETARY_BUTTON,
    ]
    for button in buttons:
        assert button.callback_data is not None
        # Telegram rejects callback data longer than 64 bytes.
        assert len(button.callback_data.encode()) <= 64
        data = AnswerCallback.unpack(button.callback_data)
        assert uuid.UUID(data.answer_id)


async def test_student_sees_no_answer_text(bot: Bot, session: FakeSession) -> None:
    dp = create_dispatcher(bot_settings(), http_client(ScriptedEngine()))
    await dp.feed_update(bot, message_update("не знаю"))
    assert session.sent_texts() == [texts.NO_ANSWER]


async def test_student_sees_error_text_when_api_fails(bot: Bot, session: FakeSession) -> None:
    dp = create_dispatcher(bot_settings(), http_client(ScriptedEngine()))
    await dp.feed_update(bot, message_update("всё недоступно"))
    assert session.sent_texts() == [texts.ANSWER_ERROR]


def test_uuid_answer_id_fits_callback_data() -> None:
    for action in Action:
        packed = AnswerCallback(answer_id=str(uuid.uuid4()), action=action).pack()
        assert len(packed.encode()) <= 64


async def test_dispatcher_closes_http_client_on_shutdown(bot: Bot) -> None:
    client = http_client(ScriptedEngine())
    dp: Dispatcher = create_dispatcher(bot_settings(), client)
    await dp.emit_shutdown(bot=bot)
    assert client._client.is_closed
