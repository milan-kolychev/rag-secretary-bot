"""Клавиатуры и данные inline-кнопок."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from bot import texts


class Action(StrEnum):
    """Действие inline-кнопки под ответом."""

    LIKE = "like"
    DISLIKE = "dislike"
    SECRETARY = "secretary"


class AnswerCallback(CallbackData, prefix="answer"):
    """Данные inline-кнопки под ответом.

    Attributes:
        answer_id: Идентификатор ответа.
        action: Что нажал пользователь.
    """

    answer_id: str
    action: Action


def main_keyboard() -> ReplyKeyboardMarkup:
    """Возвращает основную клавиатуру: «Задать вопрос» и «Помощь»."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=texts.ASK_BUTTON), KeyboardButton(text=texts.HELP_BUTTON)]],
        resize_keyboard=True,
    )


def answer_keyboard(answer_id: str) -> InlineKeyboardMarkup:
    """Возвращает кнопки под ответом: оценка и вызов секретаря."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button(texts.LIKE_BUTTON, answer_id, Action.LIKE),
                _button(texts.DISLIKE_BUTTON, answer_id, Action.DISLIKE),
            ],
            [_button(texts.SECRETARY_BUTTON, answer_id, Action.SECRETARY)],
        ]
    )


def secretary_keyboard(answer_id: str) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру с одной кнопкой «Позвать секретаря»."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[_button(texts.SECRETARY_BUTTON, answer_id, Action.SECRETARY)]]
    )


def _button(text: str, answer_id: str, action: Action) -> InlineKeyboardButton:
    callback_data = AnswerCallback(answer_id=answer_id, action=action).pack()
    return InlineKeyboardButton(text=text, callback_data=callback_data)
