"""Обработка вопросов пользователя."""

import logging
import time
import traceback

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from bot import texts
from bot.config import Settings
from bot.formatting import format_answer, split_message
from bot.keyboards import answer_keyboard, secretary_keyboard
from bot.services.answer_client import AnswerClient, AnswerClientError
from bot.validation import validate_question

logger = logging.getLogger(__name__)


async def handle_question(
    message: Message,
    state: FSMContext,
    bot: Bot,
    answer_client: AnswerClient,
    settings: Settings,
) -> None:
    """Отправляет вопрос в сервис ответов и присылает ответ пользователю.

    При ошибке валидации или ошибке сервиса состояние диалога не меняется,
    чтобы пользователь мог сразу отправить вопрос ещё раз.
    """
    text = message.text or ""
    error = validate_question(text, settings.max_question_length)
    if error:
        await message.answer(error)
        return

    question = text.strip()
    user_id = message.from_user.id if message.from_user else message.chat.id
    started = time.perf_counter()
    try:
        # The typing status disappears after 5 seconds; the sender repeats it
        # while a slow model is generating the answer.
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            answer = await answer_client.ask(question, user_id)
    except AnswerClientError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        logger.warning(
            "answer failed: error=%s user_id=%s latency=%.0fms detail=%s",
            type(exc).__name__,
            user_id,
            latency_ms,
            exc,
        )
        await message.answer(texts.ANSWER_ERROR)
        return
    except Exception as exc:
        # format_tb() leaves out the exception message: unlike AnswerClientError,
        # an arbitrary error may carry the question text in it.
        logger.error(
            "unexpected error while answering: error=%s user_id=%s\n%s",
            type(exc).__name__,
            user_id,
            "".join(traceback.format_tb(exc.__traceback__)),
        )
        await message.answer(texts.ANSWER_ERROR)
        return

    if answer.status == "answered":
        *head, last = split_message(format_answer(answer))
        for part in head:
            await message.answer(part)
        await message.answer(last, reply_markup=answer_keyboard(answer.answer_id))
    elif answer.status == "no_answer":
        await message.answer(texts.NO_ANSWER, reply_markup=secretary_keyboard(answer.answer_id))
    else:
        await message.answer(texts.ESCALATED)
    await state.clear()


async def ask_for_text(message: Message) -> None:
    """Фото, стикер, голосовое и прочие нетекстовые сообщения."""
    await message.answer(texts.TEXT_ONLY)
