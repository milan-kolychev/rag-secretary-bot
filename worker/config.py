"""Настройки RAG из локального .env и переменных окружения Docker/Windows."""

from pydantic import Field, model_validator
from pydantic_settings import SettingsConfigDict

from core.config import PersistenceSettings


class WorkerConfig(PersistenceSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "fpi_demo"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:9b"
    embed_device: str = "cpu"
    # Только для прототипа; калибруется на тестовом наборе.
    min_dense_score: float = Field(default=0.60, ge=-1.0, le=1.0)
    retrieval_limit: int = Field(default=20, ge=1, le=100)
    prompt_chunks: int = Field(default=4, ge=1, le=20)
    num_ctx: int = Field(default=4096, ge=1024)
    num_predict: int = Field(default=256, ge=32, le=2048)
    chat_history_max_tokens: int = Field(default=400, ge=0)
    rag_context_max_tokens: int = Field(default=1200, ge=0)
    qwen_tokenizer: str = "Qwen/Qwen3.5-9B"
    ollama_timeout: float = Field(default=120, gt=0)

    @model_validator(mode="after")
    def check_context(self):
        if self.num_predict >= self.num_ctx:
            raise ValueError("NUM_PREDICT must be smaller than NUM_CTX")
        return self
