"""Точка входа: `python -m bot`."""

import asyncio
import contextlib
import logging
import sys

from pydantic import ValidationError

from bot.app import create_bot, create_dispatcher
from bot.config import get_settings
from bot.services.answer_client import StubAnswerClient


def main() -> None:
    """Читает настройки и запускает long polling."""
    try:
        settings = get_settings()
    except ValidationError as exc:
        sys.exit(f"Invalid configuration, check .env:\n{exc}")

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # LoggingMiddleware already logs every update with latency.
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)

    client = StubAnswerClient()
    bot = create_bot(settings)
    dp = create_dispatcher(settings, client)

    # On Windows aiogram can't install signal handlers, so Ctrl+C arrives as
    # KeyboardInterrupt; polling still stops and closes the bot session.
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(dp.start_polling(bot))


if __name__ == "__main__":
    main()
