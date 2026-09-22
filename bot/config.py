"""Настройки бота из переменных окружения и файла `.env`."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки бота.

    Attributes:
        bot_token: Токен Telegram-бота от @BotFather.
        log_level: Уровень логирования.
        secretary_ids: Telegram ID пользователей с ролью секретаря.
        max_question_length: Максимальная длина вопроса в символах.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # The default lets the validator report a missing and an empty token the same way.
    bot_token: SecretStr = Field(default=SecretStr(""), validate_default=True)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    secretary_ids: Annotated[set[int], NoDecode] = Field(default_factory=set)
    max_question_length: int = Field(default=1000, gt=0)

    @field_validator("bot_token")
    @classmethod
    def check_token(cls, value: SecretStr) -> SecretStr:
        """Проверяет, что токен задан."""
        if not value.get_secret_value().strip():
            raise ValueError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in")
        return value

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
