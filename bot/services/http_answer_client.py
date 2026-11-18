"""HTTP-клиент к `POST /ask` API ядра."""

import asyncio
import json
from contextlib import suppress

import httpx
from pydantic import ValidationError

from bot.services.answer_client import (
    Answer,
    AnswerBusyError,
    AnswerClientError,
    AnswerQueueFullError,
    AnswerTimeoutError,
    AnswerUnavailableError,
)

CONNECT_TIMEOUT = 5.0
# Gateway-type statuses: the API itself or the RAG engine behind it is down.
UNAVAILABLE_STATUSES = {502, 503, 504}


class HttpAnswerClient:
    """Клиент сервиса ответов поверх REST API (контракт: `api/openapi.yaml`).

    Тексты исключений содержат только HTTP-код и код ошибки из ответа API,
    но не вопрос пользователя: они попадают в логи.

    Args:
        base_url: Адрес API, например `http://api:8000`.
        token: Сервисный токен API.
        timeout: Сколько секунд ждать ответ.
        transport: Транспорт httpx; в тестах подменяется, чтобы не ходить в сеть.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.timeout = timeout
        self._pending: dict[tuple[int, int], str] = {}
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(timeout, connect=min(CONNECT_TIMEOUT, timeout)),
            transport=transport,
        )

    async def ask(self, question: str, user_id: int) -> Answer:
        """Отправляет вопрос в `POST /ask`.

        Args:
            question: Текст вопроса.
            user_id: Telegram ID пользователя.

        Returns:
            Ответ сервиса.

        Raises:
            AnswerTimeoutError: API не ответил за `timeout` секунд.
            AnswerUnavailableError: API недоступен или вернул 502, 503, 504.
            AnswerClientError: Другой код ответа или ответ не по контракту.
        """
        try:
            response = await self._client.post(
                "/ask", json={"question": question, "user_id": user_id}
            )
        except httpx.TimeoutException as exc:
            raise AnswerTimeoutError(f"no response from answer API in {self.timeout:g} s") from exc
        except httpx.HTTPError as exc:
            raise AnswerUnavailableError(
                f"answer API request failed: {type(exc).__name__}"
            ) from exc

        if response.status_code != 200:
            detail = f"answer API returned {response.status_code} {_error_code(response)}"
            if response.status_code in UNAVAILABLE_STATUSES:
                raise AnswerUnavailableError(detail)
            raise AnswerClientError(detail)

        try:
            return Answer.model_validate_json(response.content)
        except ValidationError:
            # The validation error text quotes the response, which contains the question.
            raise AnswerClientError("answer API response does not match the contract") from None

    async def aclose(self) -> None:
        """Закрывает HTTP-соединения. Вызывается при остановке бота."""
        await self._client.aclose()

    async def ask_in_chat(self, question: str, user_id: int, chat_id: int) -> Answer:
        """Short submission followed by polling; queue wait has no generation deadline."""
        try:
            response = await self._client.post(
                "/requests",
                json={
                    "question": question,
                    "user_id": user_id,
                    "chat_id": chat_id,
                },
            )
            if response.status_code == 409:
                raise AnswerBusyError("Previous request is busy")
            if response.status_code == 429:
                raise AnswerQueueFullError("Request queue is full")
            if response.status_code != 202:
                raise AnswerUnavailableError(f"submission failed: {response.status_code}")
            request_id = response.json()["request_id"]
            self._pending[(chat_id, user_id)] = request_id
            while True:
                response = await self._client.get(f"/requests/{request_id}")
                if response.status_code != 200:
                    raise AnswerUnavailableError(f"poll failed: {response.status_code}")
                data = response.json()
                if data["state"] == "done":
                    return Answer.model_validate(data["result"])
                if data["state"] in {"failed", "cancelled"}:
                    raise AnswerUnavailableError(f"request failed: {data['error']}")
                await asyncio.sleep(0.25)
        except httpx.TimeoutException:
            raise AnswerTimeoutError("Answer API transport timed out") from None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise AnswerUnavailableError("Invalid or unavailable answer API") from None

    async def finish_in_chat(self, chat_id: int, user_id: int) -> None:
        request_id = self._pending.pop((chat_id, user_id), None)
        if request_id:
            with suppress(httpx.HTTPError):
                await self._client.delete(f"/requests/{request_id}")


def _error_code(response: httpx.Response) -> str:
    """Достаёт `error.code` из ответа с ошибкой; `-`, если тело не по контракту."""
    try:
        code = response.json()["error"]["code"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return "-"
    return code if isinstance(code, str) else "-"
