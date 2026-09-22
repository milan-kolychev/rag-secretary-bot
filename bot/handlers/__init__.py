"""Обработчики сообщений и нажатий кнопок."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart

from bot import texts
from bot.handlers import common, feedback, question
from bot.keyboards import Action, AnswerCallback
from bot.states import QuestionFlow


def create_router() -> Router:
    """Создаёт роутер со всеми обработчиками бота.

    Порядок регистрации важен: команды, затем кнопки основной клавиатуры, затем
    вопрос в состоянии ожидания, затем любой текст в личном чате как вопрос и в конце
    нетекстовые сообщения. Так «Помощь» и /cancel не попадают в обработчик вопросов.
    """
    # A new router per call: aiogram can't attach one router to two dispatchers,
    # and tests build several dispatchers.
    router = Router(name="handlers")
    private = F.chat.type == "private"

    router.message.register(common.start, CommandStart())
    router.message.register(common.show_help, Command("help"))
    router.message.register(common.ask, Command("ask"))
    router.message.register(common.cancel, Command("cancel"))
    router.message.register(common.unknown_command, private, F.text.startswith("/"))

    router.message.register(common.ask, F.text == texts.ASK_BUTTON)
    router.message.register(common.show_help, F.text == texts.HELP_BUTTON)

    router.message.register(question.handle_question, QuestionFlow.waiting_question, F.text)
    router.message.register(question.handle_question, private, F.text)
    router.message.register(question.ask_for_text, private)

    router.callback_query.register(
        feedback.rate_answer,
        AnswerCallback.filter(F.action.in_({Action.LIKE, Action.DISLIKE})),
    )
    router.callback_query.register(
        feedback.call_secretary, AnswerCallback.filter(F.action == Action.SECRETARY)
    )
    return router
