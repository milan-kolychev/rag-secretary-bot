import pytest

from bot.services.answer_client import Answer, AnswerUnavailableError, StubAnswerClient


@pytest.fixture
def stub() -> StubAnswerClient:
    return StubAnswerClient(delay=0)


async def test_stub_answers(stub: StubAnswerClient) -> None:
    answer = await stub.ask("Когда сессия?", user_id=1)
    assert isinstance(answer, Answer)
    assert answer.status == "answered"
    assert "Когда сессия?" in answer.text
    assert len(answer.sources) == 1


async def test_stub_answer_id_is_deterministic(stub: StubAnswerClient) -> None:
    first = await stub.ask("вопрос", user_id=1)
    second = await stub.ask("вопрос", user_id=1)
    other_user = await stub.ask("вопрос", user_id=2)
    assert first.answer_id == second.answer_id != other_user.answer_id


@pytest.mark.parametrize(
    ("question", "status"),
    [("Тут нет ответа", "no_answer"), ("Нужен Секретарь", "escalated")],
)
async def test_stub_triggers(stub: StubAnswerClient, question: str, status: str) -> None:
    answer = await stub.ask(question, user_id=1)
    assert answer.status == status
    assert answer.sources == []


async def test_stub_error_does_not_contain_question(stub: StubAnswerClient) -> None:
    with pytest.raises(AnswerUnavailableError) as exc_info:
        await stub.ask("Ошибка в моём личном вопросе", user_id=1)
    assert "личном" not in str(exc_info.value)
