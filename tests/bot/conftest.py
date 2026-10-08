from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher

from bot.app import create_dispatcher
from bot.config import Settings
from tests.bot.helpers import SECRETARY_ID, FakeSession


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "BOT_TOKEN",
        "LOG_LEVEL",
        "SECRETARY_IDS",
        "MAX_QUESTION_LENGTH",
        "API_URL",
        "API_TOKEN",
        "ANSWER_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        bot_token="42:TEST",
        secretary_ids=str(SECRETARY_ID),
        max_question_length=100,
    )


@pytest.fixture
def client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def bot(session: FakeSession) -> Bot:
    return Bot(token="42:TEST", session=session)


@pytest.fixture
def dp(settings: Settings, client: AsyncMock) -> Dispatcher:
    return create_dispatcher(settings, client)
