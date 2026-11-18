from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PersistenceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str | None = None
    chat_history_messages: int = Field(default=5, ge=0, le=100)
    chat_history_retention_hours: int = Field(default=48, ge=1)
    queue_max_size: int = Field(default=20, ge=1, le=1000)
    queue_poll_interval: float = Field(default=0.25, gt=0, le=10)
    delivery_timeout: float = Field(default=120, gt=0)
