"""Авто-повторения слов: бот сам присылает карточки пользователям Plus/Premium.

Простой фоновый цикл (без внешних зависимостей): каждые AUTO_REVIEW_INTERVAL
секунд ищет пользователей с истёкшими карточками и отправляет им до 3 слов
на повторение. Управляется env-переменной AUTO_REVIEWS_ENABLED (on/off).
"""
from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot

from db import Database
from keyboards import level_select_cb

logger = logging.getLogger(__name__)

AUTO_REVIEWS_ENABLED = os.getenv("AUTO_REVIEWS_ENABLED", "on") == "on"
AUTO_REVIEW_INTERVAL = int(os.getenv("AUTO_REVIEW_INTERVAL", "1800"))  # 30 минут
MAX_WORDS_PER_PING = 3


async def _ping_user(bot: Bot, db: Database, user_id: int) -> None:
    level = await db.get_level(user_id)
    due = await db.due_cards(user_id, level, limit=MAX_WORDS_PER_PING)
    if not due:
        return
    lines = ["🤖 <b>Время повторить слова!</b> Нажми кнопку под каждым словом 👇", ""]
    for item in due:
        lines.append(f"🃏 <b>{item.word}</b> — как переводится?")
    try:
        await bot.send_message(user_id, "\n".join(lines), parse_mode="HTML",
                               reply_markup=level_select_cb(level))
    except Exception as exc:  # noqa: BLE001 (пользователь мог заблокировать бота)
        logger.info("Auto-review ping skipped for %s: %s", user_id, exc)


async def auto_review_loop(bot: Bot, db: Database) -> None:
    """Фоновая задача: периодические авто-повторения для платных планов."""
    if not AUTO_REVIEWS_ENABLED:
        return
    logger.info("Auto-reviews enabled (every %ss)", AUTO_REVIEW_INTERVAL)
    while True:
        try:
            users = await db.users_with_due_cards(limit=200)
            for uid in users:
                await _ping_user(bot, db, uid)
                await asyncio.sleep(0.5)  # мягкий rate-limit
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Auto-review loop error")
        await asyncio.sleep(AUTO_REVIEW_INTERVAL)
