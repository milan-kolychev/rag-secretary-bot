from bot import texts
from bot.formatting import MESSAGE_LIMIT, format_answer, split_message
from bot.services.answer_client import Answer, Source


def make_answer(sources: list[Source]) -> Answer:
    return Answer(answer_id="a1", text="Ответ.", sources=sources, status="answered")


def test_answer_without_sources() -> None:
    assert format_answer(make_answer([])) == "Ответ."


def test_answer_with_one_source() -> None:
    text = format_answer(make_answer([Source(title="Положение о практике", section="п. 3.2")]))
    assert text == f"Ответ.\n\n{texts.SOURCES_HEADER}\n• Положение о практике, п. 3.2"


def test_answer_with_several_sources() -> None:
    sources = [Source(title="Устав"), Source(title="Приказ № 12", section="п. 1")]
    text = format_answer(make_answer(sources))
    assert text.endswith(f"{texts.SOURCES_HEADER}\n• Устав\n• Приказ № 12, п. 1")


def test_split_short_text() -> None:
    assert split_message("Короткий ответ") == ["Короткий ответ"]


def test_split_exactly_limit() -> None:
    text = "a" * MESSAGE_LIMIT
    assert split_message(text) == [text]


def test_split_by_paragraphs() -> None:
    paragraphs = ["а" * 3000, "б" * 3000, "в" * 100]
    parts = split_message("\n\n".join(paragraphs))
    assert parts == ["а" * 3000, "б" * 3000 + "\n\n" + "в" * 100]


def test_split_long_paragraph_by_lines() -> None:
    lines = ["строка " * 50] * 30
    text = "\n".join(lines)
    parts = split_message(text)
    assert len(parts) > 1
    assert all(len(part) <= MESSAGE_LIMIT for part in parts)
    assert "\n".join(parts) == text


def test_split_without_newlines() -> None:
    text = "x" * (MESSAGE_LIMIT * 2 + 10)
    parts = split_message(text)
    assert [len(part) for part in parts] == [MESSAGE_LIMIT, MESSAGE_LIMIT, 10]
    assert "".join(parts) == text
