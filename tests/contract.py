"""Загрузка контракта `api/openapi.yaml` и проверка JSON по его схемам."""

from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

SPEC_PATH = Path(__file__).resolve().parents[1] / "api" / "openapi.yaml"
SPEC_URI = "urn:fpi-rag:openapi"


@cache
def load_spec() -> dict[str, Any]:
    with SPEC_PATH.open(encoding="utf-8") as file:
        spec: dict[str, Any] = yaml.safe_load(file)
    return spec


@cache
def _registry() -> Registry:
    resource = Resource.from_contents(load_spec(), default_specification=DRAFT202012)
    return Registry().with_resource(SPEC_URI, resource)


def validator(schema_name: str) -> Draft202012Validator:
    """Валидатор для `components/schemas/<schema_name>` с проверкой форматов (uuid)."""
    return Draft202012Validator(
        {"$ref": f"{SPEC_URI}#/components/schemas/{schema_name}"},
        registry=_registry(),
        format_checker=FormatChecker(),
    )


def assert_matches(schema_name: str, instance: Any) -> None:
    """Падает с перечнем ошибок, если `instance` не соответствует схеме."""
    errors = sorted(validator(schema_name).iter_errors(instance), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


def is_valid(schema_name: str, instance: Any) -> bool:
    return validator(schema_name).is_valid(instance)
