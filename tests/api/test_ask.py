import logging
import threading
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.app import create_app
from api.config import ApiSettings
from api.engine import RagAnswer, RagUnavailableError, StubRagEngine
from api.schemas import Source
from tests.api.conftest import AUTH
from tests.contract import assert_matches

QUESTION = "Когда пересдача по матанализу?"
DOC_ID = uuid.uuid4()


class FakeEngine:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.questions: list[str] = []

    def answer(self, question: str) -> Any:
        self.questions.append(question)
        if self.error:
            raise self.error
        return self.result


def make_client(settings: ApiSettings, engine: Any) -> TestClient:
    return TestClient(create_app(settings, engine), raise_server_exceptions=False)


def ask(client: TestClient, question: str = QUESTION, **extra: Any) -> Any:
    return client.post("/ask", json={"question": question, "user_id": 42, **extra}, headers=AUTH)


def test_health_without_token(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert_matches("Health", response.json())


def test_answered(api_settings: ApiSettings) -> None:
    engine = FakeEngine(
        RagAnswer(
            status="answered",
            text="Пересдача в феврале.",
            sources=[Source(document_id=DOC_ID, title="График пересдач", section="п. 2")],
        )
    )
    response = ask(make_client(api_settings, engine), f"  {QUESTION}  ")

    assert response.status_code == 200
    body = response.json()
    assert_matches("AskResponse", body)
    assert body["status"] == "answered"
    assert body["text"] == "Пересдача в феврале."
    assert body["sources"] == [
        {"document_id": str(DOC_ID), "title": "График пересдач", "section": "п. 2"}
    ]
    assert body["ticket_id"] is None
    assert engine.questions == [QUESTION]  # stripped before the engine


def test_answer_ids_are_unique(client: TestClient) -> None:
    first, second = ask(client).json(), ask(client).json()
    assert first["answer_id"] != second["answer_id"]


def test_no_answer_drops_text_and_sources(api_settings: ApiSettings) -> None:
    # The engine filled text for no_answer anyway: the API must not leak it to the student.
    engine = FakeEngine(
        RagAnswer(
            status="no_answer",
            text="догадка модели",
            sources=[Source(document_id=DOC_ID, title="Устав")],
        )
    )
    body = ask(make_client(api_settings, engine)).json()
    assert_matches("AskResponse", body)
    assert (body["status"], body["text"], body["sources"]) == ("no_answer", "", [])


def test_engine_may_return_own_model(api_settings: ApiSettings) -> None:
    class OwnSource:
        document_id = str(DOC_ID)
        title = "Положение о практике"
        section = None

    class OwnAnswer:
        status = "answered"
        text = "Ответ."
        sources = [OwnSource()]

    body = ask(make_client(api_settings, FakeEngine(OwnAnswer()))).json()
    assert_matches("AskResponse", body)
    assert body["sources"][0]["title"] == "Положение о практике"


@pytest.mark.parametrize(
    ("headers", "status"),
    [({}, 401), ({"Authorization": "Bearer wrong"}, 401), ({"Authorization": "Basic x"}, 401)],
    ids=["missing", "wrong-token", "wrong-scheme"],
)
def test_token_required(client: TestClient, headers: dict[str, str], status: int) -> None:
    response = client.post("/ask", json={"question": QUESTION, "user_id": 1}, headers=headers)
    assert response.status_code == status
    assert_matches("Error", response.json())
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "", "user_id": 1},
        {"question": "   ", "user_id": 1},
        {"question": "а" * 1001, "user_id": 1},
        {"question": QUESTION},
        {"question": QUESTION, "user_id": 0},
        {"question": QUESTION, "user_id": "abc"},
        {"question": QUESTION, "user_id": 1, "extra": True},
    ],
    ids=["empty", "spaces", "too-long", "no-user", "user-zero", "user-text", "extra-field"],
)
def test_validation_error(client: TestClient, payload: dict[str, Any]) -> None:
    response = client.post("/ask", json=payload, headers=AUTH)
    assert response.status_code == 422
    body = response.json()
    assert_matches("Error", body)
    assert body["error"]["code"] == "validation_error"


def test_validation_error_does_not_echo_question(client: TestClient) -> None:
    secret = "мой личный вопрос " * 60  # longer than 1000 characters
    response = client.post("/ask", json={"question": secret, "user_id": 1}, headers=AUTH)
    assert response.status_code == 422
    assert "личный" not in response.text


def test_question_of_max_length_is_accepted(client: TestClient) -> None:
    assert ask(client, "а" * 1000).status_code == 200


def test_invalid_json(client: TestClient) -> None:
    response = client.post(
        "/ask", content="{", headers={**AUTH, "Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert_matches("Error", response.json())


def test_engine_unavailable(api_settings: ApiSettings) -> None:
    engine = FakeEngine(error=RagUnavailableError("qdrant is down"))
    response = ask(make_client(api_settings, engine))
    assert response.status_code == 503
    assert_matches("Error", response.json())
    assert response.json()["error"]["code"] == "rag_unavailable"


def test_engine_timeout() -> None:
    release = threading.Event()

    class SlowEngine:
        def answer(self, question: str) -> RagAnswer:
            release.wait(5)
            return RagAnswer(status="no_answer")

    settings = ApiSettings(_env_file=None, api_token="test-token", rag_timeout=0.1)
    try:
        response = ask(make_client(settings, SlowEngine()))
    finally:
        release.set()
    assert response.status_code == 503
    assert_matches("Error", response.json())
    assert response.json()["error"]["code"] == "rag_timeout"


@pytest.mark.parametrize(
    "error",
    [ValueError(f"cannot parse {QUESTION}"), None],
    ids=["engine-raises", "engine-returns-garbage"],
)
def test_engine_failure_is_500_without_question_in_logs(
    api_settings: ApiSettings, caplog: pytest.LogCaptureFixture, error: Exception | None
) -> None:
    engine = FakeEngine(result={"status": "answered", "text": ""}, error=error)
    with caplog.at_level(logging.DEBUG):
        response = ask(make_client(api_settings, engine))
    assert response.status_code == 500
    assert_matches("Error", response.json())
    assert response.json()["error"]["code"] == "internal_error"
    assert "user_id=42" in caplog.text
    assert QUESTION not in caplog.text
    assert QUESTION not in response.text


def test_question_is_not_logged(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        ask(client)
    assert "POST /ask status=200" in caplog.text
    assert "status=answered" in caplog.text
    assert QUESTION not in caplog.text


def test_unknown_path(client: TestClient) -> None:
    response = client.get("/nope", headers=AUTH)
    assert response.status_code == 404
    assert_matches("Error", response.json())


@pytest.mark.parametrize(
    ("question", "status", "code"),
    [
        ("Когда сессия?", 200, None),
        ("Тут НЕТ ОТВЕТА", 200, None),
        ("ошибка", 503, "rag_unavailable"),
    ],
)
def test_stub_engine_through_api(
    client: TestClient, question: str, status: int, code: str | None
) -> None:
    response = ask(client, question)
    assert response.status_code == status
    if code:
        assert response.json()["error"]["code"] == code
    else:
        assert_matches("AskResponse", response.json())


def test_stub_engine_statuses() -> None:
    stub = StubRagEngine()
    assert stub.answer("Где справка?").status == "answered"
    assert stub.answer("нет ответа").status == "no_answer"
    with pytest.raises(RagUnavailableError) as exc_info:
        stub.answer("ошибка в личном вопросе")
    assert "личном" not in str(exc_info.value)


def test_wrong_method(client: TestClient) -> None:
    response = client.get("/ask", headers=AUTH)
    assert response.status_code == 405
    assert_matches("Error", response.json())
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_unexpected_error_outside_engine(
    app: FastAPI, client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError(f"secret {QUESTION}")

    with caplog.at_level(logging.DEBUG):
        response = client.get("/boom")
    assert response.status_code == 500
    assert_matches("Error", response.json())
    assert QUESTION not in caplog.text
