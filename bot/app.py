"""Сборка бота, диспетчера и клиента сервиса ответов."""

import logging

from aiogram import Bot, Dispatcher

from bot.config import Settings
from bot.handlers import create_router
from bot.middlewares.logging import LoggingMiddleware
from bot.middlewares.roles import RoleMiddleware
from bot.services.answer_client import AnswerClient, StubAnswerClient
from bot.services.http_answer_client import HttpAnswerClient

logger = logging.getLogger(__name__)


def create_bot(settings: Settings) -> Bot:
    """Создаёт клиент Telegram Bot API."""
    return Bot(token=settings.bot_token.get_secret_value())


def create_answer_client(settings: Settings) -> AnswerClient:
    """Создаёт клиент сервиса ответов.

    Если `API_URL` задан, бот ходит в `POST /ask`; иначе работает с заглушкой.
    """
    if settings.api_url is None:
        logger.warning("API_URL is not set, answers come from the stub")
        return StubAnswerClient()
    return HttpAnswerClient(
        base_url=str(settings.api_url),
        token=settings.api_token.get_secret_value(),
        timeout=settings.answer_timeout,
    )


def create_dispatcher(settings: Settings, client: AnswerClient) -> Dispatcher:
    """Создаёт диспетчер с middleware и обработчиками.

    `settings` и `client` попадают в данные диспетчера, обработчики получают их
    параметрами `settings` и `answer_client`.
    """
    dp = Dispatcher(settings=settings, answer_client=client)
    dp.update.outer_middleware(LoggingMiddleware())
    dp.update.outer_middleware(RoleMiddleware(settings.secretary_ids))
    dp.include_router(create_router())
    if isinstance(client, HttpAnswerClient):
        dp.shutdown.register(client.aclose)
    return dp
