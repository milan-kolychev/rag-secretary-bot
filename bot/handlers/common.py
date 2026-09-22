"""Команды и кнопки основной клавиатуры."""

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot import texts
from bot.keyboards import main_keyboard
from bot.states import QuestionFlow


async def start(message: Message, state: FSMContext) -> None:
    """Команда /start: приветствие и основная клавиатура."""
    await state.clear()
    await message.answer(texts.START, reply_markup=main_keyboard())


async def show_help(message: Message) -> None:
    """Команда /help и кнопка «Помощь»."""
    await message.answer(texts.HELP)


async def ask(message: Message, state: FSMContext) -> None:
    """Команда /ask и кнопка «Задать вопрос»: переводит в ожидание вопроса."""
    await state.set_state(QuestionFlow.waiting_question)
    await message.answer(texts.ASK_PROMPT)


async def cancel(message: Message, state: FSMContext) -> None:
    """Команда /cancel: сбрасывает состояние."""
    await state.clear()
    await message.answer(texts.CANCELLED, reply_markup=main_keyboard())


async def unknown_command(message: Message) -> None:
    """Любая другая команда."""
    await message.answer(texts.UNKNOWN_COMMAND)
