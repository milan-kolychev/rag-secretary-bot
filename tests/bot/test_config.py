import pytest
from pydantic import ValidationError

from bot.config import Settings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", set()),
        ("123", {123}),
        (" 123, 456", {123, 456}),
        ("123,,456,", {123, 456}),
    ],
)
def test_secretary_ids_parsing(raw: str, expected: set[int]) -> None:
    settings = Settings(_env_file=None, bot_token="42:TEST", secretary_ids=raw)
    assert settings.secretary_ids == expected


def test_secretary_ids_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "42:TEST")
    monkeypatch.setenv("SECRETARY_IDS", "1, 2")
    assert Settings(_env_file=None).secretary_ids == {1, 2}


def test_secretary_ids_not_a_number() -> None:
    with pytest.raises(ValidationError, match="SECRETARY_IDS must be comma-separated"):
        Settings(_env_file=None, bot_token="42:TEST", secretary_ids="123, abc")


def test_missing_bot_token() -> None:
    with pytest.raises(ValidationError, match="BOT_TOKEN is not set"):
        Settings(_env_file=None)


def test_empty_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "  ")
    with pytest.raises(ValidationError, match="BOT_TOKEN is not set"):
        Settings(_env_file=None)


def test_token_is_hidden_in_repr() -> None:
    settings = Settings(_env_file=None, bot_token="42:SECRET")
    assert "SECRET" not in repr(settings)
