"""Проверки самого контракта и его соответствия коду API и бота."""

import typing
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from api import schemas
from bot.config import Settings
from bot.services.answer_client import Answer
from tests.api.conftest import AUTH
from tests.contract import is_valid, load_spec

METHODS = {"get", "post", "put", "patch", "delete"}


def operations() -> Iterator[tuple[str, str, dict[str, Any]]]:
    for path, item in load_spec()["paths"].items():
        for method, operation in item.items():
            if method in METHODS:
                yield path, method, operation


def collect_refs(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref":
                yield value
            else:
                yield from collect_refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from collect_refs(value)


def resolve(ref: str) -> Any:
    assert ref.startswith("#/"), ref
    node: Any = load_spec()
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def test_spec_version() -> None:
    assert load_spec()["openapi"].startswith("3.1")


def test_all_refs_resolve() -> None:
    for ref in set(collect_refs(load_spec())):
        resolve(ref)


@pytest.mark.parametrize("name", sorted(load_spec()["components"]["schemas"]))
def test_component_schema_is_valid_json_schema(name: str) -> None:
    Draft202012Validator.check_schema(load_spec()["components"]["schemas"][name])


@pytest.mark.parametrize(
    ("path", "method", "operation"),
    list(operations()),
    ids=[f"{m.upper()} {p}" for p, m, _ in operations()],
)
def test_operation_is_complete(path: str, method: str, operation: dict[str, Any]) -> None:
    assert operation.get("operationId")
    assert operation.get("x-sprint") in {2, 3, 4, 5}
    assert operation.get("responses")
    protected = operation.get("security", load_spec()["security"]) != []
    if protected:
        assert "401" in operation["responses"], "protected operation must document 401"


def test_operation_ids_are_unique() -> None:
    ids = [operation["operationId"] for _, _, operation in operations()]
    assert len(ids) == len(set(ids))


def test_sprint2_operations_are_implemented(app: FastAPI) -> None:
    implemented = {
        (route.path, method.lower())
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    planned = {(p, m) for p, m, op in operations() if op["x-sprint"] == 2}
    assert planned == {("/health", "get"), ("/ask", "post")}
    assert planned <= implemented
    # Nothing is implemented outside the contract.
    assert implemented <= {(p, m) for p, m, _ in operations()}


def schema_enum(name: str) -> set[str]:
    return set(load_spec()["components"]["schemas"][name]["enum"])


def test_answer_statuses_match_code() -> None:
    expected = schema_enum("AnswerStatus")
    assert set(typing.get_args(schemas.AnswerStatus)) == expected
    bot_status = Answer.model_fields["status"].annotation
    assert set(typing.get_args(bot_status)) == expected


def test_error_codes_match_code() -> None:
    spec_codes = set(
        load_spec()["components"]["schemas"]["Error"]["properties"]["error"]["properties"]["code"][
            "enum"
        ]
    )
    assert set(typing.get_args(schemas.ErrorCode)) == spec_codes


def test_question_length_limits_agree() -> None:
    spec_max = load_spec()["components"]["schemas"]["AskRequest"]["properties"]["question"][
        "maxLength"
    ]
    assert spec_max == schemas.MAX_QUESTION_LENGTH
    # The bot must not accept questions the API would reject.
    bot_limit = Settings.model_fields["max_question_length"].metadata
    assert any(getattr(item, "le", None) == spec_max for item in bot_limit)


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "Когда сессия?", "user_id": 1},
        {"question": "а" * 1000, "user_id": 2**63 - 1},
        {"question": "", "user_id": 1},
        {"question": "а" * 1001, "user_id": 1},
        {"question": "x", "user_id": 0},
        {"question": "x", "user_id": 2**63},
        {"question": "x"},
        {"user_id": 1},
        {"question": "x", "user_id": 1, "chat_id": 1},
        {"question": 5, "user_id": 1},
    ],
)
def test_api_accepts_exactly_what_spec_accepts(client: TestClient, payload: dict[str, Any]) -> None:
    response = client.post("/ask", json=payload, headers=AUTH)
    assert (response.status_code == 200) == is_valid("AskRequest", payload)
