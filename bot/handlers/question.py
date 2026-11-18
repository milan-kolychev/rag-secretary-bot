"""Question admission, busy guard and replacement of the progress message."""

import asyncio
import logging
import traceback
from contextlib import suppress

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot import texts
from bot.config import Settings
from bot.formatting import format_answer, split_message
from bot.keyboards import answer_keyboard, secretary_keyboard
from bot.services.answer_client import (
    AnswerBusyError,
    AnswerClient,
    AnswerClientError,
    AnswerQueueFullError,
)
from bot.services.delivery import replace_progress

logger = logging.getLogger(__name__)
# No await between checking and inserting: atomic within the bot's event loop.
# PostgreSQL additionally protects admission across API/bot instances.
_busy: dict[tuple[int, int, int], bool] = {}


async def handle_question(
    message: Message, state: FSMContext, bot: Bot, answer_client: AnswerClient, settings: Settings
) -> None:
    from bot.validation import validate_question

    user_id = message.from_user.id if message.from_user else message.chat.id
    key = (bot.id, message.chat.id, user_id)
    if key in _busy:
        if not _busy[key]:
            _busy[key] = True
            await message.answer(texts.BUSY)
        return
    error = validate_question(message.text or "", settings.max_question_length)
    if error:
        await message.answer(error)
        return
    _busy[key] = False
    progress = None
    try:
        progress = await message.answer(texts.PROCESSING)
        contextual = getattr(answer_client, "ask_in_chat", None)
        question = message.text.strip()
        answer = (
            await contextual(question, user_id, message.chat.id)
            if contextual
            else await answer_client.ask(question, user_id)
        )
        if answer.status == "answered":
            parts = split_message(format_answer(answer))
            await replace_progress(
                progress,
                message,
                parts[0],
                **({"reply_markup": answer_keyboard(answer.answer_id)} if len(parts) == 1 else {}),
            )
            for index, part in enumerate(parts[1:], 1):
                await message.answer(
                    part,
                    **(
                        {"reply_markup": answer_keyboard(answer.answer_id)}
                        if index == len(parts) - 1
                        else {}
                    ),
                )
        elif answer.status == "no_answer":
            await replace_progress(
                progress,
                message,
                texts.NO_ANSWER,
                reply_markup=secretary_keyboard(answer.answer_id),
            )
        else:
            await replace_progress(progress, message, texts.ESCALATED)
        await state.clear()
    except asyncio.CancelledError:
        if progress:
            with suppress(Exception):
                await replace_progress(progress, message, texts.ANSWER_ERROR)
        raise
    except Exception as exc:
        if isinstance(exc, AnswerBusyError):
            notification = texts.BUSY
        elif isinstance(exc, AnswerQueueFullError):
            notification = texts.QUEUE_FULL
        else:
            notification = texts.ANSWER_ERROR
        logger.warning("answer failed: error=%s user_id=%s", type(exc).__name__, user_id)
        if not isinstance(exc, AnswerClientError):
            logger.error(
                "unexpected error user_id=%s\n%s",
                user_id,
                "".join(traceback.format_tb(exc.__traceback__)),
            )
        if progress:
            await replace_progress(progress, message, notification)
    finally:
        try:
            finish = getattr(answer_client, "finish_in_chat", None)
            if finish:
                await finish(message.chat.id, user_id)
        finally:
            _busy.pop(key, None)


async def ask_for_text(message: Message) -> None:
    await message.answer(texts.TEXT_ONLY)
