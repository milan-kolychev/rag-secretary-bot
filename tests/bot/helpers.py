from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

USER_ID = 1001
SECRETARY_ID = 2002


class FakeSession(BaseSession):
    """Records Bot API calls instead of sending them to Telegram."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[Any] = []

    async def make_request(
        self,
        bot: Bot,
        method: Any,
        timeout: int | None = None,  # noqa: ASYNC109 - signature of BaseSession
    ) -> Any:
        self.requests.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=99,
                date=datetime.now(UTC),
                chat=Chat(id=method.chat_id, type="private"),
                text=method.text,
            ).as_(bot)
        return True

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes, None]:
        raise NotImplementedError
        yield b""

    async def close(self) -> None:
        pass

    def sent_texts(self) -> list[str]:
        return [
            r.text
            for r in self.requests
            if isinstance(r, (SendMessage, EditMessageText))
            and r.text != "⏳ Обрабатываю ваш запрос, пожалуйста, подождите"
        ]


def make_message(text: str | None = None, *, chat_type: str = "private", **kwargs: Any) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=USER_ID, type=chat_type),
        from_user=User(id=USER_ID, is_bot=False, first_name="Test"),
        text=text,
        **kwargs,
    )


def message_update(text: str | None = None, **kwargs: Any) -> Update:
    return Update(update_id=1, message=make_message(text, **kwargs))


def callback_update(data: str) -> Update:
    callback = CallbackQuery(
        id="1",
        from_user=User(id=USER_ID, is_bot=False, first_name="Test"),
        chat_instance="1",
        data=data,
        message=make_message("ответ"),
    )
    return Update(update_id=1, callback_query=callback)
