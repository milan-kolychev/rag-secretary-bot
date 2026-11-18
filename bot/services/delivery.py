"""Telegram message replacement with bounded flood-control retry and fallback."""

import asyncio
import logging

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter


async def replace_progress(progress, original, text, **kwargs):
    for attempt in range(2):
        try:
            await progress.edit_text(text, **kwargs)
            return
        except TelegramRetryAfter as exc:
            if attempt == 0 and exc.retry_after <= 10:
                await asyncio.sleep(exc.retry_after)
                continue
            break
        except TelegramBadRequest as exc:
            if "message is not modified" in exc.message.lower():
                return
            break
        except TelegramAPIError:
            break
    try:
        await progress.delete()
    except TelegramAPIError:
        logging.getLogger(__name__).warning("progress_delete_failed")
    await original.answer(text, **kwargs)
