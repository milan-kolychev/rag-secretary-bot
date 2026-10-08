import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from bot.services.answer_client import (
    AnswerClientError,
    AnswerTimeoutError,
    AnswerUnavailableError,
)
from bot.services.http_answer_client import HttpAnswerClient
from tests.contract import assert_matches

QUESTION = "Когда пересдача по матанализу?"
ANSWER_ID = str(uuid.uuid4())
DOC_ID = str(uuid.uuid4())


def answered_body(**kwargs: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "answer_id": ANSWER_ID,
        "status": "answered",
        "text": "Пересдача в феврале.",
        "sources": [{"document_id": DOC_ID, "title": "График пересдач", "section": "п. 2"}],
        "ticket_id": None,
    }
    body.update(kwargs)
    return body


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> HttpAnswerClient:
    return HttpAnswerClient(
        "http://api:8000", "secret-token", timeout=3, transport=httpx.MockTransport(handler)
    )


def error_body(code: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": "details"}}


async def test_request_follows_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=answered_body())

    answer = await make_client(handler).ask(QUESTION, user_id=42)

    (request,) = requests
    assert request.method == "POST"
    assert str(request.url) == "http://api:8000/ask"
    assert request.headers["Authorization"] == "Bearer secret-token"
    payload = json.loads(request.content)
    assert payload == {"question": QUESTION, "user_id": 42}
    assert_matches("AskRequest", payload)

    assert answer.answer_id == ANSWER_ID
    assert answer.status == "answered"
    assert answer.text == "Пересдача в феврале."
    assert [(s.title, s.section) for s in answer.sources] == [("График пересдач", "п. 2")]


@pytest.mark.parametrize(
    "body",
    [
        answered_body(),
        answered_body(status="no_answer", text="", sources=[]),
        answered_body(status="escalated", text="", sources=[], ticket_id=str(uuid.uuid4())),
    ],
    ids=["answered", "no_answer", "escalated"],
)
async def test_parses_every_contract_status(body: dict[str, Any]) -> None:
    assert_matches("AskResponse", body)  # the fixture itself follows the contract
    answer = await make_client(lambda _: httpx.Response(200, json=body)).ask(QUESTION, 1)
    assert answer.status == body["status"]


@pytest.mark.parametrize(
    ("status", "body", "error", "detail"),
    [
        (503, error_body("rag_unavailable"), AnswerUnavailableError, "503 rag_unavailable"),
        (503, error_body("rag_timeout"), AnswerUnavailableError, "503 rag_timeout"),
        (502, b"<html>Bad Gateway</html>", AnswerUnavailableError, "502 -"),
        (401, error_body("unauthorized"), AnswerClientError, "401 unauthorized"),
        (422, error_body("validation_error"), AnswerClientError, "422 validation_error"),
        (500, error_body("internal_error"), AnswerClientError, "500 internal_error"),
        (500, {"error": "oops"}, AnswerClientError, "500 -"),
    ],
)
async def test_error_statuses(status: int, body: Any, error: type[Exception], detail: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, bytes):
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=body)

    with pytest.raises(error) as exc_info:
        await make_client(handler).ask(QUESTION, 1)
    assert detail in str(exc_info.value)
    if error is AnswerClientError:
        assert not isinstance(exc_info.value, AnswerUnavailableError)


async def test_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(AnswerTimeoutError, match="in 3 s"):
        await make_client(handler).ask(QUESTION, 1)


async def test_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(AnswerUnavailableError, match="ConnectError"):
        await make_client(handler).ask(QUESTION, 1)


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        json.dumps({"status": "answered", "text": QUESTION}).encode(),
        json.dumps(answered_body(status="unknown", text=QUESTION)).encode(),
    ],
    ids=["not-json", "missing-fields", "unknown-status"],
)
async def test_response_not_matching_contract(content: bytes) -> None:
    client = make_client(lambda _: httpx.Response(200, content=content))
    with pytest.raises(AnswerClientError) as exc_info:
        await client.ask(QUESTION, 1)
    assert "does not match the contract" in str(exc_info.value)
    assert QUESTION not in str(exc_info.value)


async def test_connect_timeout_is_capped() -> None:
    client = HttpAnswerClient("http://api:8000", "t", timeout=30)
    timeout = client._client.timeout
    assert (timeout.connect, timeout.read) == (5.0, 30)
    await client.aclose()


async def test_aclose() -> None:
    client = make_client(lambda _: httpx.Response(200, json=answered_body()))
    await client.aclose()
    assert client._client.is_closed
