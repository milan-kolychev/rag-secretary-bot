"""Сборка бота и диспетчера."""

from aiogram import Bot, Dispatcher

from bot.config import Settings
from bot.handlers import create_router
from bot.middlewares.logging import LoggingMiddleware
from bot.middlewares.roles import RoleMiddleware
from bot.services.answer_client import AnswerClient


def create_bot(settings: Settings) -> Bot:
    """Создаёт клиент Telegram Bot API."""
    return Bot(token=settings.bot_token.get_secret_value())


def create_dispatcher(settings: Settings, client: AnswerClient) -> Dispatcher:
    """Создаёт диспетчер с middleware и обработчиками.

    `settings` и `client` попадают в данные диспетчера, обработчики получают их
    параметрами `settings` и `answer_client`.
    """
    dp = Dispatcher(settings=settings, answer_client=client)
    dp.update.outer_middleware(LoggingMiddleware())
    dp.update.outer_middleware(RoleMiddleware(settings.secretary_ids))
    dp.include_router(create_router())
    return dp
