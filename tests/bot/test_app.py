import logging
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import User

from bot import texts
from bot.app import create_answer_client, create_bot, create_dispatcher
from bot.config import Settings
from bot.middlewares.roles import RoleMiddleware
from bot.services.answer_client import StubAnswerClient
from bot.services.http_answer_client import HttpAnswerClient
from bot.states import QuestionFlow
from tests.bot.helpers import SECRETARY_ID, USER_ID, FakeSession, message_update


async def set_waiting_state(dp: Dispatcher, bot: Bot) -> None:
    context = dp.fsm.get_context(bot, chat_id=USER_ID, user_id=USER_ID)
    await context.set_state(QuestionFlow.waiting_question)


def test_create_bot(settings: Settings) -> None:
    assert create_bot(settings).token == "42:TEST"


def test_dispatcher_passes_dependencies(dp: Dispatcher, settings: Settings) -> None:
    assert dp["settings"] is settings
    assert dp["answer_client"] is not None


async def test_start(dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
    await dp.feed_update(bot, message_update("/start"))
    assert session.sent_texts() == [texts.START]


@pytest.mark.parametrize(
    ("text", "reply"),
    [(texts.HELP_BUTTON, texts.HELP), ("/help", texts.HELP), ("/cancel", texts.CANCELLED)],
    ids=["help-button", "help-command", "cancel"],
)
async def test_commands_skip_question_handler(
    dp: Dispatcher, bot: Bot, session: FakeSession, client: AsyncMock, text: str, reply: str
) -> None:
    await set_waiting_state(dp, bot)

    await dp.feed_update(bot, message_update(text))

    client.ask.assert_not_awaited()
    assert session.sent_texts() == [reply]


async def test_cancel_resets_state(dp: Dispatcher, bot: Bot) -> None:
    await set_waiting_state(dp, bot)
    await dp.feed_update(bot, message_update("/cancel"))
    context = dp.fsm.get_context(bot, chat_id=USER_ID, user_id=USER_ID)
    assert await context.get_state() is None


async def test_ask_button_sets_state(dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
    await dp.feed_update(bot, message_update(texts.ASK_BUTTON))
    context = dp.fsm.get_context(bot, chat_id=USER_ID, user_id=USER_ID)
    assert await context.get_state() == QuestionFlow.waiting_question
    assert session.sent_texts() == [texts.ASK_PROMPT]


async def test_unknown_command(
    dp: Dispatcher, bot: Bot, session: FakeSession, client: AsyncMock
) -> None:
    await dp.feed_update(bot, message_update("/foo"))
    client.ask.assert_not_awaited()
    assert session.sent_texts() == [texts.UNKNOWN_COMMAND]


async def test_plain_text_is_question(settings: Settings, bot: Bot, session: FakeSession) -> None:
    dp = create_dispatcher(settings, StubAnswerClient(delay=0))
    await dp.feed_update(bot, message_update("Где взять справку?"))
    assert "Где взять справку?" in session.sent_texts()[0]


async def test_group_text_is_ignored(
    dp: Dispatcher, bot: Bot, session: FakeSession, client: AsyncMock
) -> None:
    await dp.feed_update(bot, message_update("Всем привет", chat_type="group"))
    client.ask.assert_not_awaited()
    assert session.sent_texts() == []


async def test_non_text_message(dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
    update = message_update(
        sticker={
            "file_id": "1",
            "file_unique_id": "1",
            "type": "regular",
            "width": 512,
            "height": 512,
            "is_animated": False,
            "is_video": False,
        }
    )
    await dp.feed_update(bot, update)
    assert session.sent_texts() == [texts.TEXT_ONLY]


async def test_message_text_is_not_logged(
    settings: Settings, bot: Bot, caplog: pytest.LogCaptureFixture
) -> None:
    dp = create_dispatcher(settings, StubAnswerClient(delay=0))
    with caplog.at_level(logging.DEBUG):
        await dp.feed_update(bot, message_update("мой личный вопрос"))
    assert "update=message" in caplog.text
    assert "личный" not in caplog.text


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        (User(id=SECRETARY_ID, is_bot=False, first_name="S"), True),
        (User(id=USER_ID, is_bot=False, first_name="U"), False),
        (None, False),
    ],
)
async def test_role_middleware(user: User | None, expected: bool) -> None:
    handler = AsyncMock()
    await RoleMiddleware({SECRETARY_ID})(handler, object(), {"event_from_user": user})
    assert handler.await_args.args[1]["is_secretary"] is expected


async def test_answer_client_is_stub_without_api_url(settings: Settings) -> None:
    assert isinstance(create_answer_client(settings), StubAnswerClient)


async def test_answer_client_is_http_with_api_url() -> None:
    settings = Settings(
        _env_file=None,
        bot_token="42:TEST",
        api_url="http://api:8000",
        api_token="t",
        answer_timeout=12,
    )
    client = create_answer_client(settings)
    assert isinstance(client, HttpAnswerClient)
    assert client.timeout == 12
    assert str(client._client.base_url) == "http://api:8000/"
    assert client._client.headers["Authorization"] == "Bearer t"
    await client.aclose()
