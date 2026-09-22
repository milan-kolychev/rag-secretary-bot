import pytest

from bot import texts
from bot.validation import validate_question


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_empty_question(text: str) -> None:
    assert validate_question(text, max_length=10) == texts.EMPTY_QUESTION


def test_too_long_question() -> None:
    error = validate_question("a" * 11, max_length=10)
    assert error == texts.QUESTION_TOO_LONG.format(length=11, limit=10)


@pytest.mark.parametrize("text", ["a", "a" * 10, "  " + "a" * 10 + "  "])
def test_valid_question(text: str) -> None:
    assert validate_question(text, max_length=10) is None
