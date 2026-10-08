import pytest
from pydantic import ValidationError

from bot.config import Settings, format_errors


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


@pytest.mark.parametrize("raw", ["", "  "])
def test_empty_api_url_means_stub(raw: str) -> None:
    assert Settings(_env_file=None, bot_token="42:TEST", api_url=raw).api_url is None


def test_api_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "42:TEST")
    monkeypatch.setenv("API_URL", "http://api:8000")
    monkeypatch.setenv("API_TOKEN", "t")
    monkeypatch.setenv("ANSWER_TIMEOUT", "15")
    settings = Settings(_env_file=None)
    assert str(settings.api_url) == "http://api:8000/"
    assert settings.answer_timeout == 15


def test_api_url_requires_token() -> None:
    with pytest.raises(ValidationError, match="API_TOKEN is required when API_URL is set"):
        Settings(_env_file=None, bot_token="42:TEST", api_url="http://api:8000")


@pytest.mark.parametrize("url", ["api:8000", "ftp://api", "not a url"])
def test_invalid_api_url(url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, bot_token="42:TEST", api_url=url, api_token="t")


@pytest.mark.parametrize("length", [0, 1001])
def test_question_length_bounds(length: int) -> None:
    # 1000 is the maximum POST /ask accepts.
    with pytest.raises(ValidationError):
        Settings(_env_file=None, bot_token="42:TEST", max_question_length=length)


def test_api_token_hidden_in_repr() -> None:
    settings = Settings(
        _env_file=None, bot_token="42:TEST", api_url="http://api", api_token="APISECRET"
    )
    assert "APISECRET" not in repr(settings)


def test_format_errors_hides_values() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, bot_token="42:hunter2", api_url="http://api", secretary_ids="1, x")
    text = format_errors(exc_info.value)
    assert "hunter2" not in text
    assert "SECRETARY_IDS: Value error, SECRETARY_IDS must be comma-separated" in text


def test_format_errors_model_level() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, bot_token="42:SECRET", api_url="http://api")
    text = format_errors(exc_info.value)
    assert text == "- Value error, API_TOKEN is required when API_URL is set"
