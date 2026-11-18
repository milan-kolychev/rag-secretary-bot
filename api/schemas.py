"""Модели запросов и ответов API.

Повторяют схемы из `api/openapi.yaml`; соответствие проверяется тестами
`tests/api/test_contract.py`.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MAX_QUESTION_LENGTH = 1000

AnswerStatus = Literal["answered", "no_answer", "escalated"]
ErrorCode = Literal[
    "unauthorized",
    "not_found",
    "method_not_allowed",
    "conflict",
    "queue_full",
    "too_large",
    "validation_error",
    "rag_unavailable",
    "rag_timeout",
    "internal_error",
]

TelegramId = Annotated[int, Field(ge=1, le=2**63 - 1)]
Question = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_LENGTH),
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Health(_Strict):
    """Ответ `GET /health`."""

    status: Literal["ok"] = "ok"


class AskRequest(_Strict):
    """Тело `POST /ask`.

    Attributes:
        question: Текст вопроса; пробелы по краям обрезаются до проверки длины.
        user_id: Telegram ID студента.
    """

    question: Question
    user_id: TelegramId
    chat_id: Annotated[int, Field(ge=-(2**63), le=2**63 - 1)] | None = None


class Source(_Strict):
    """Документ, на котором основан ответ.

    Attributes:
        document_id: Идентификатор документа (UUID).
        title: Название документа.
        section: Раздел или пункт документа, если известен.
    """

    document_id: UUID
    title: Annotated[str, Field(min_length=1)]
    section: str | None = None


class AskResponse(_Strict):
    """Ответ `POST /ask`.

    Attributes:
        answer_id: Идентификатор ответа (UUID).
        status: `answered`, `no_answer` или `escalated`.
        text: Текст ответа; пустой при `no_answer` и `escalated`.
        sources: Документы, использованные в ответе.
        ticket_id: Идентификатор обращения при `escalated`.
    """

    answer_id: UUID
    status: AnswerStatus
    text: str
    sources: list[Source]
    ticket_id: UUID | None


class ErrorDetail(_Strict):
    """Код и описание ошибки."""

    code: ErrorCode
    message: str


class Error(_Strict):
    """Тело ответа с ошибкой."""

    error: ErrorDetail
