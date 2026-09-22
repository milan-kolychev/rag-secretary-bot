"""Нажатия inline-кнопок под ответом."""

import logging

from aiogram.types import CallbackQuery, Message

from bot import texts
from bot.keyboards import AnswerCallback, secretary_keyboard

logger = logging.getLogger(__name__)


async def rate_answer(callback: CallbackQuery, callback_data: AnswerCallback) -> None:
    """Кнопки 👍 и 👎: записывает оценку в лог и убирает кнопки оценки."""
    logger.info(
        "answer rated: answer_id=%s rating=%s user_id=%s",
        callback_data.answer_id,
        callback_data.action,
        callback.from_user.id,
    )
    await callback.answer(texts.RATING_THANKS)
    # Messages older than 48 hours come as InaccessibleMessage and can't be edited.
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(
            reply_markup=secretary_keyboard(callback_data.answer_id)
        )


async def call_secretary(callback: CallbackQuery, callback_data: AnswerCallback) -> None:
    """Кнопка «Позвать секретаря». В прототипе только сообщает пользователю о запросе."""
    logger.info(
        "secretary requested: answer_id=%s user_id=%s",
        callback_data.answer_id,
        callback.from_user.id,
    )
    await callback.answer()
    if callback.message:
        await callback.message.answer(texts.SECRETARY_REQUESTED)
