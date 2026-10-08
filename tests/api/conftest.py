import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.app import create_app
from api.config import ApiSettings
from api.engine import RagEngine, StubRagEngine

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("API_TOKEN", "RAG_ENGINE", "RAG_TIMEOUT", "API_HOST", "API_PORT", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def api_settings() -> ApiSettings:
    return ApiSettings(_env_file=None, api_token=TOKEN, rag_timeout=2)


@pytest.fixture
def engine() -> RagEngine:
    return StubRagEngine()


@pytest.fixture
def app(api_settings: ApiSettings, engine: RagEngine) -> FastAPI:
    return create_app(api_settings, engine)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    # raise_server_exceptions=False: check the 500 response instead of the raised error.
    return TestClient(app, raise_server_exceptions=False)
