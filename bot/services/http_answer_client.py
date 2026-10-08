"""HTTP-клиент к `POST /ask` API ядра."""

import json

import httpx
from pydantic import ValidationError

from bot.services.answer_client import (
    Answer,
    AnswerClientError,
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


def _error_code(response: httpx.Response) -> str:
    """Достаёт `error.code` из ответа с ошибкой; `-`, если тело не по контракту."""
    try:
        code = response.json()["error"]["code"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return "-"
    return code if isinstance(code, str) else "-"
