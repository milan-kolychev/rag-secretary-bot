"""Настройки API из переменных окружения и файла `.env`."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    """Настройки API.

    Attributes:
        api_token: Сервисный токен; бот и n8n передают его в `Authorization: Bearer`.
        rag_engine: `stub` или путь к фабрике движка в виде `модуль:функция`,
            например `worker.rag:create_engine`.
        rag_timeout: Сколько секунд ждать ответ движка. Должно быть меньше
            `ANSWER_TIMEOUT` бота, чтобы бот получил понятную ошибку, а не обрыв.
        api_host: Адрес, на котором слушает сервер.
        api_port: Порт сервера.
        log_level: Уровень логирования.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_token: SecretStr = Field(default=SecretStr(""), validate_default=True)
    rag_engine: str = "stub"
    rag_timeout: float = Field(default=25.0, gt=0)
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, gt=0, lt=65536)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("api_token")
    @classmethod
    def check_token(cls, value: SecretStr) -> SecretStr:
        """Проверяет, что токен задан."""
        if not value.get_secret_value().strip():
            raise ValueError("API_TOKEN is not set. Copy .env.example to .env and fill it in")
        return value


@lru_cache
def get_settings() -> ApiSettings:
    """Читает настройки один раз.

    Raises:
        pydantic.ValidationError: Если настройки не заданы или заданы неверно.
    """
    return ApiSettings()


def format_errors(exc: ValidationError) -> str:
    """Текст ошибок настроек без введённых значений (в них может быть токен)."""
    lines = []
    for error in exc.errors(include_input=False, include_url=False):
        field = ".".join(str(item) for item in error["loc"]).upper()
        lines.append(f"- {field}: {error['msg']}" if field else f"- {error['msg']}")
    return "\n".join(lines)
