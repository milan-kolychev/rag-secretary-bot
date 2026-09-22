"""Состояния диалога."""

from aiogram.fsm.state import State, StatesGroup


class QuestionFlow(StatesGroup):
    """Диалог «Задать вопрос»: бот ждёт текст вопроса."""

    waiting_question = State()
