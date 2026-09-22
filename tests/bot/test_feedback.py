from aiogram import Bot, Dispatcher
from aiogram.methods import AnswerCallbackQuery, EditMessageReplyMarkup

from bot import texts
from bot.keyboards import Action, AnswerCallback, secretary_keyboard
from tests.bot.helpers import FakeSession, callback_update


async def test_rating_removes_rating_buttons(
    dp: Dispatcher, bot: Bot, session: FakeSession
) -> None:
    data = AnswerCallback(answer_id="a1", action=Action.LIKE).pack()

    await dp.feed_update(bot, callback_update(data))

    answer, edit = session.requests
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.text == texts.RATING_THANKS
    assert isinstance(edit, EditMessageReplyMarkup)
    assert edit.reply_markup == secretary_keyboard("a1")


async def test_call_secretary(dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
    data = AnswerCallback(answer_id="a1", action=Action.SECRETARY).pack()

    await dp.feed_update(bot, callback_update(data))

    assert isinstance(session.requests[0], AnswerCallbackQuery)
    assert session.sent_texts() == [texts.SECRETARY_REQUESTED]
