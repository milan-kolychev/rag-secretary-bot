import sys
import types
from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from api.config import ApiSettings, format_errors
from api.engine import RagAnswer, StubRagEngine, load_engine

MODULE = "fake_rag_engine_module"


class GoodEngine:
    def answer(self, question: str) -> RagAnswer:
        return RagAnswer(status="no_answer")


@pytest.fixture
def fake_module() -> Iterator[types.ModuleType]:
    module = types.ModuleType(MODULE)
    module.create_engine = GoodEngine  # type: ignore[attr-defined]
    module.not_callable = 42  # type: ignore[attr-defined]
    module.bad_factory = lambda: object()  # type: ignore[attr-defined]
    sys.modules[MODULE] = module
    yield module
    del sys.modules[MODULE]


def test_load_stub() -> None:
    assert isinstance(load_engine("stub"), StubRagEngine)


def test_load_factory(fake_module: types.ModuleType) -> None:
    assert isinstance(load_engine(f"{MODULE}:create_engine"), GoodEngine)


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("worker.rag", "must be 'stub' or 'module:factory'"),
        (":create_engine", "must be 'stub' or 'module:factory'"),
        ("no_such_module_xyz:create", "cannot be imported"),
        (f"{MODULE}:missing", "not found or not callable"),
        (f"{MODULE}:not_callable", "not found or not callable"),
        (f"{MODULE}:bad_factory", "without answer()"),
    ],
)
def test_load_errors(fake_module: types.ModuleType, spec: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_engine(spec)


def test_answered_requires_text() -> None:
    with pytest.raises(ValidationError, match="non-empty text"):
        RagAnswer(status="answered", text="  ")


def test_settings_defaults() -> None:
    settings = ApiSettings(_env_file=None, api_token="t")
    assert (settings.rag_engine, settings.rag_timeout, settings.api_port) == ("stub", 130.0, 8000)


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_TOKEN", "t")
    monkeypatch.setenv("RAG_ENGINE", "worker.rag:create_engine")
    monkeypatch.setenv("RAG_TIMEOUT", "12.5")
    settings = ApiSettings(_env_file=None)
    assert settings.rag_engine == "worker.rag:create_engine"
    assert settings.rag_timeout == 12.5


@pytest.mark.parametrize("token", [None, "", "   "])
def test_settings_token_required(monkeypatch: pytest.MonkeyPatch, token: str | None) -> None:
    if token is not None:
        monkeypatch.setenv("API_TOKEN", token)
    with pytest.raises(ValidationError, match="API_TOKEN is not set"):
        ApiSettings(_env_file=None)


def test_settings_token_hidden_in_repr() -> None:
    assert "SECRET" not in repr(ApiSettings(_env_file=None, api_token="SECRET"))


def test_format_errors_hides_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_TOKEN", "t")
    monkeypatch.setenv("RAG_TIMEOUT", "-1")
    with pytest.raises(ValidationError) as exc_info:
        ApiSettings(_env_file=None)
    assert format_errors(exc_info.value) == "- RAG_TIMEOUT: Input should be greater than 0"
