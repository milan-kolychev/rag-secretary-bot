"""Проверка вопроса перед отправкой в сервис ответов."""

from bot import texts


def validate_question(text: str, max_length: int) -> str | None:
    """Проверяет вопрос пользователя.

    Пробелы по краям не учитываются.

    Args:
        text: Текст сообщения.
        max_length: Максимальная длина вопроса.

    Returns:
        Текст ошибки для пользователя или `None`, если вопрос подходит.
    """
    question = text.strip()
    if not question:
        return texts.EMPTY_QUESTION
    if len(question) > max_length:
        return texts.QUESTION_TOO_LONG.format(length=len(question), limit=max_length)
    return None
