"""Определение роли пользователя."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User


class RoleMiddleware(BaseMiddleware):
    """Добавляет в данные обработчика флаг `is_secretary`.

    Args:
        secretary_ids: Telegram ID секретарей.
    """

    def __init__(self, secretary_ids: set[int]) -> None:
        self.secretary_ids = secretary_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Проставляет `is_secretary` и вызывает обработчик."""
        user: User | None = data.get("event_from_user")
        data["is_secretary"] = user is not None and user.id in self.secretary_ids
        return await handler(event, data)
