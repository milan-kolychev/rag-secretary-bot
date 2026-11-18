"""Сборка текста сообщений из ответа сервиса."""

from bot import texts
from bot.services.answer_client import Answer, Source

# Telegram counts UTF-16 code units, including surrogate pairs for emoji.
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
    if limit < 2:
        raise ValueError("Message limit must be at least two UTF-16 code units")
    return _split(text, limit, ("\n\n", "\n"))


def _units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _split(text: str, limit: int, separators: tuple[str, ...]) -> list[str]:
    if _units(text) <= limit:
        return [text]
    if not separators:
        parts, current, size = [], [], 0
        for character in text:
            width = 2 if ord(character) > 0xFFFF else 1
            if size + width > limit:
                parts.append("".join(current))
                current, size = [], 0
            current.append(character)
            size += width
        if current:
            parts.append("".join(current))
        return parts

    separator, rest = separators[0], separators[1:]
    parts: list[str] = []
    current = ""
    for piece in text.split(separator):
        candidate = f"{current}{separator}{piece}" if current else piece
        if _units(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        if _units(piece) <= limit:
            current = piece
        else:
            # Keep the tail of an oversized piece open so the next pieces can join it.
            *head, current = _split(piece, limit, rest)
            parts.extend(head)
    if current:
        parts.append(current)
    return parts
