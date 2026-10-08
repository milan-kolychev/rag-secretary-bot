"""Интерфейс сервиса ответов, модели его ответа и заглушка.

Модели `Answer` и `Source` повторяют `AskResponse` и `Source` из контракта
`api/openapi.yaml` (лишние поля ответа, например `ticket_id`, бот пока не использует).
С API бот работает через `HttpAnswerClient` (`http_answer_client.py`); `StubAnswerClient`
остаётся для запуска бота без API, если `API_URL` не задан.
"""

import asyncio
import hashlib
from typing import Literal, Protocol

from pydantic import BaseModel


class Source(BaseModel):
    """Документ, на котором основан ответ.

    Attributes:
        title: Название документа.
        section: Раздел или пункт документа, если известен.
    """

    title: str
    section: str | None = None


class Answer(BaseModel):
    """Ответ сервиса на вопрос.

    Attributes:
        answer_id: Идентификатор ответа, нужен для оценки и передачи секретарю.
        text: Текст ответа.
        sources: Документы, использованные в ответе.
        status: `answered` — ответ найден; `no_answer` — в документах ответа нет;
            `escalated` — вопрос передан секретарю.
    """

    answer_id: str
    text: str
    sources: list[Source] = []
    status: Literal["answered", "no_answer", "escalated"]


class AnswerClientError(Exception):
    """Техническая ошибка при получении ответа.

    Текст исключения не должен содержать вопрос пользователя: он попадает в логи.
    """


class AnswerTimeoutError(AnswerClientError):
    """Сервис ответов не ответил вовремя."""


class AnswerUnavailableError(AnswerClientError):
    """Сервис ответов недоступен."""


class AnswerClient(Protocol):
    """Интерфейс сервиса ответов, через который бот задаёт вопросы."""

    async def ask(self, question: str, user_id: int) -> Answer:
        """Задаёт вопрос от имени пользователя.

        Args:
            question: Текст вопроса.
            user_id: Telegram ID пользователя.

        Returns:
            Ответ сервиса.

        Raises:
            AnswerClientError: При технической ошибке.
        """
        ...


class StubAnswerClient:
    """Заглушка сервиса ответов для запуска бота без API.

    Отвечает детерминированно, поведение переключается словами в вопросе
    (без учёта регистра, проверяются по порядку):

    - «ошибка» — `AnswerUnavailableError`;
    - «нет ответа» — статус `no_answer`;
    - «секретарь» — статус `escalated`;
    - иначе — статус `answered` с цитатой вопроса и одним выдуманным источником.

    Args:
        delay: Задержка перед ответом в секундах, имитирует работу модели.
    """

    def __init__(self, delay: float = 1.0) -> None:
        self.delay = delay

    async def ask(self, question: str, user_id: int) -> Answer:
        """Возвращает тестовый ответ на вопрос.

        Args:
            question: Текст вопроса.
            user_id: Telegram ID пользователя.

        Returns:
            Тестовый ответ.

        Raises:
            AnswerUnavailableError: Если в вопросе есть слово «ошибка».
        """
        await asyncio.sleep(self.delay)

        lowered = question.lower()
        if "ошибка" in lowered:
            raise AnswerUnavailableError("stub answer service is unavailable")

        answer_id = hashlib.sha256(f"{user_id}:{question}".encode()).hexdigest()[:12]
        if "нет ответа" in lowered:
            return Answer(answer_id=answer_id, text="", status="no_answer")
        if "секретарь" in lowered:
            return Answer(answer_id=answer_id, text="", status="escalated")
        return Answer(
            answer_id=answer_id,
            text=f"Это тестовый ответ на вопрос «{question}». Настоящие ответы появятся позже.",
            sources=[Source(title="Тестовый документ факультета", section="п. 1.1")],
            status="answered",
        )
