"""Настройки бота из переменных окружения и файла `.env`."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import (
    AnyHttpUrl,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки бота.

    Attributes:
        bot_token: Токен Telegram-бота от @BotFather.
        log_level: Уровень логирования.
        secretary_ids: Telegram ID пользователей с ролью секретаря.
        max_question_length: Максимальная длина вопроса в символах. Не больше 1000:
            столько принимает `POST /ask` (см. `api/openapi.yaml`).
        api_url: Адрес API ядра. Если не задан, бот работает с заглушкой.
        api_token: Сервисный токен API, обязателен при заданном `api_url`.
        answer_timeout: Сколько секунд ждать ответ `POST /ask`.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # The default lets the validator report a missing and an empty token the same way.
    bot_token: SecretStr = Field(default=SecretStr(""), validate_default=True)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    secretary_ids: Annotated[set[int], NoDecode] = Field(default_factory=set)
    max_question_length: int = Field(default=1000, gt=0, le=1000)
    api_url: AnyHttpUrl | None = None
    api_token: SecretStr = SecretStr("")
    answer_timeout: float = Field(default=30.0, gt=0)

    @field_validator("bot_token")
    @classmethod
    def check_token(cls, value: SecretStr) -> SecretStr:
        """Проверяет, что токен задан."""
        if not value.get_secret_value().strip():
            raise ValueError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in")
        return value

    @field_validator("api_url", mode="before")
    @classmethod
    def empty_url_is_none(cls, value: object) -> object:
        """Пустой `API_URL=` в `.env` означает работу с заглушкой."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def check_api_token(self) -> "Settings":
        """Без токена API отвечает 401, поэтому ошибка видна сразу при запуске."""
        if self.api_url is not None and not self.api_token.get_secret_value().strip():
            raise ValueError("API_TOKEN is required when API_URL is set")
        return self

    @field_validator("secretary_ids", mode="before")
    @classmethod
    def parse_secretary_ids(cls, value: object) -> object:
        """Разбирает список ID через запятую: `" 123, 456"` -> `{123, 456}`."""
        if not isinstance(value, str):
            return value
        ids = set()
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.add(int(part))
            except ValueError:
                raise ValueError(
                    f"SECRETARY_IDS must be comma-separated Telegram user IDs, got {part!r}"
                ) from None
        return ids


@lru_cache
def get_settings() -> Settings:
    """Читает настройки один раз и возвращает один и тот же объект.

    Raises:
        pydantic.ValidationError: Если настройки не заданы или заданы неверно.
    """
    return Settings()


def format_errors(exc: ValidationError) -> str:
    """Текст ошибок настроек без введённых значений.

    Стандартный текст `ValidationError` для проверок на уровне модели содержит все
    значения настроек, включая токены, поэтому выводятся только поле и сообщение.
    """
    lines = []
    for error in exc.errors(include_input=False, include_url=False):
        field = ".".join(str(item) for item in error["loc"]).upper()
        lines.append(f"- {field}: {error['msg']}" if field else f"- {error['msg']}")
    return "\n".join(lines)
