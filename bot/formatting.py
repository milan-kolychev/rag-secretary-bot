"""Сборка текста сообщений из ответа сервиса."""

from bot import texts
from bot.services.answer_client import Answer, Source

# Telegram counts the limit in UTF-16 code units, len() counts code points. The difference
# only matters for characters outside the BMP (emoji), which answers rarely contain.
MESSAGE_LIMIT = 4096


def format_source(source: Source) -> str:
    """Возвращает строку с названием документа и разделом, если он есть."""
    if source.section:
        return f"{source.title}, {source.section}"
    return source.title


def format_answer(answer: Answer) -> str:
    """Собирает текст ответа и список источников.

    Если источников нет, блок «Источники:» не добавляется.
    """
    if not answer.sources:
        return answer.text
    lines = [answer.text, "", texts.SOURCES_HEADER]
    lines.extend(f"• {format_source(source)}" for source in answer.sources)
    return "\n".join(lines)


def split_message(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Разбивает текст на части не длиннее `limit` символов.

    Сначала режет по абзацам, затем по строкам и только потом посреди строки.
    Соседние короткие куски склеиваются обратно, пока влезают в лимит.

    Args:
        text: Исходный текст.
        limit: Максимальная длина одной части.

    Returns:
        Список частей; для короткого текста — список из одного элемента.
    """
    return _split(text, limit, ("\n\n", "\n"))


def _split(text: str, limit: int, separators: tuple[str, ...]) -> list[str]:
    if len(text) <= limit:
        return [text]
    if not separators:
        return [text[i : i + limit] for i in range(0, len(text), limit)]

    separator, rest = separators[0], separators[1:]
    parts: list[str] = []
    current = ""
    for piece in text.split(separator):
        candidate = f"{current}{separator}{piece}" if current else piece
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        if len(piece) <= limit:
            current = piece
        else:
            # Keep the tail of an oversized piece open so the next pieces can join it.
            *head, current = _split(piece, limit, rest)
            parts.extend(head)
    if current:
        parts.append(current)
    return parts
