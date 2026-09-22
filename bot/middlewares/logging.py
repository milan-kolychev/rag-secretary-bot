"""Логирование апдейтов."""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update, User

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """Пишет в лог тип апдейта, ID пользователя и время обработки.

    Текст сообщений не логируется: это персональные данные.
    Регистрируется как outer-middleware на `dp.update`.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Вызывает обработчик и логирует результат."""
        started = time.perf_counter()
        try:
            return await handler(event, data)
        finally:
            latency_ms = (time.perf_counter() - started) * 1000
            update_type = event.event_type if isinstance(event, Update) else type(event).__name__
            user: User | None = data.get("event_from_user")
            logger.info(
                "update=%s user_id=%s latency=%.0fms",
                update_type,
                user.id if user else None,
                latency_ms,
            )
