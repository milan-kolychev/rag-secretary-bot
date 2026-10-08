"""Интерфейс RAG-движка и его загрузка.

RAG-движок (поиск в Qdrant, эмбеддинги BGE-M3, генерация Qwen3.5-9B) пишет участник A.
API знает о нём только этот интерфейс: движок подключается переменной `RAG_ENGINE`
в виде `модуль:фабрика`, где фабрика без аргументов возвращает объект с методом
`answer`. Пока движка нет, работает `StubRagEngine`.

Метод `answer` синхронный: модель эмбеддингов работает через PyTorch, и API вызывает
движок в пуле потоков, чтобы не блокировать обработку других запросов.
"""

import importlib
import uuid
from collections.abc import Callable
from typing import Literal, Protocol

from pydantic import BaseModel, model_validator

from api.schemas import Source

STUB_DOCUMENT_ID = uuid.uuid5(uuid.NAMESPACE_URL, "fpi-rag/stub-document")


class RagAnswer(BaseModel):
    """Результат работы движка.

    Attributes:
        status: `answered`, если оценка найденных фрагментов не ниже порога;
            иначе `no_answer`.
        text: Текст ответа, обязателен при `answered`.
        sources: Документы, на которых основан ответ.
    """

    status: Literal["answered", "no_answer"]
    text: str = ""
    sources: list[Source] = []

    @model_validator(mode="after")
    def check_text(self) -> "RagAnswer":
        """Ответ со статусом `answered` не может быть пустым."""
        if self.status == "answered" and not self.text.strip():
            raise ValueError("answered RagAnswer must have non-empty text")
        return self


class RagUnavailableError(Exception):
    """Движок не может ответить: недоступны LLM, Qdrant или модель эмбеддингов.

    Текст исключения не должен содержать вопрос пользователя: он попадает в логи.
    """


class RagEngine(Protocol):
    """Интерфейс RAG-движка."""

    def answer(self, question: str) -> RagAnswer:
        """Ищет фрагменты документов и формирует ответ.

        Args:
            question: Текст вопроса без пробелов по краям.

        Returns:
            Ответ движка.

        Raises:
            RagUnavailableError: Если зависимость движка недоступна.
        """
        ...


class StubRagEngine:
    """Заглушка движка для MVP без RAG-ядра.

    Поведение переключается словами в вопросе (без учёта регистра, по порядку):

    - «ошибка»: `RagUnavailableError`;
    - «нет ответа»: статус `no_answer`;
    - иначе: статус `answered` с цитатой вопроса и одним выдуманным источником.
    """

    def answer(self, question: str) -> RagAnswer:
        """Возвращает тестовый ответ."""
        lowered = question.lower()
        if "ошибка" in lowered:
            raise RagUnavailableError("stub RAG engine is unavailable")
        if "нет ответа" in lowered:
            return RagAnswer(status="no_answer")
        return RagAnswer(
            status="answered",
            text=f"Это тестовый ответ API на вопрос «{question}». Настоящие ответы появятся "
            "после подключения RAG-ядра.",
            sources=[
                Source(
                    document_id=STUB_DOCUMENT_ID,
                    title="Тестовый документ факультета",
                    section="п. 1.1",
                )
            ],
        )


def load_engine(spec: str) -> RagEngine:
    """Создаёт движок по значению `RAG_ENGINE`.

    Args:
        spec: `stub` или `модуль:фабрика`.

    Returns:
        Движок.

    Raises:
        ValueError: Если строка в неверном формате или фабрика не найдена.
    """
    if spec == "stub":
        return StubRagEngine()
    module_name, sep, attr = spec.partition(":")
    if not sep or not module_name or not attr:
        raise ValueError(f"RAG_ENGINE must be 'stub' or 'module:factory', got {spec!r}")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(f"RAG_ENGINE module {module_name!r} cannot be imported: {exc}") from exc
    factory: object = getattr(module, attr, None)
    if not callable(factory):
        raise ValueError(f"RAG_ENGINE factory {spec!r} is not found or not callable")
    engine: object = _call(factory)
    if not callable(getattr(engine, "answer", None)):
        raise ValueError(f"RAG_ENGINE factory {spec!r} returned an object without answer()")
    return engine  # type: ignore[return-value]


def _call(factory: Callable[[], object]) -> object:
    return factory()
