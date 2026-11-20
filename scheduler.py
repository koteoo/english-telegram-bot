"""Авто-повторения слов: бот сам присылает карточки пользователям Plus/Premium.

Простой фоновый цикл (без внешних зависимостей): каждые AUTO_REVIEW_INTERVAL
секунд ищет пользователей с истёкшими карточками и отправляет им до 3 слов
на повторение. Управляется env-переменной AUTO_REVIEWS_ENABLED (on/off).
"""
from __future__ import annotations

import asyncio
import logging
import os

from datetime import datetime, timezone

from aiogram import Bot

from db import Database
from keyboards import level_select_cb

logger = logging.getLogger(__name__)

AUTO_REVIEWS_ENABLED = os.getenv("AUTO_REVIEWS_ENABLED", "on") == "on"
AUTO_REVIEW_INTERVAL = int(os.getenv("AUTO_REVIEW_INTERVAL", "900"))  # проверка раз в 15 мин
NOTIFY_HOUR_FROM = int(os.getenv("NOTIFY_HOUR_FROM", "9"))   # начало окна, местное время
NOTIFY_HOUR_TO = int(os.getenv("NOTIFY_HOUR_TO", "21"))      # конец окна (не включительно)
NOTIFY_TZ_OFFSET = int(os.getenv("NOTIFY_TZ_OFFSET", "3"))   # смещение от UTC, по умолчанию МСК
MAX_WORDS_PER_PING = 3
# если человек сегодня уже занимался — напоминание не нужно
ACTIVITY_KINDS = ("words", "quiz", "chat", "review")


async def _ping_user(bot: Bot, db: Database, user_id: int, local_hour: int) -> None:
    enabled, hour = await db.get_notify_prefs(user_id)
    if not enabled or hour != local_hour:
        return
    # не чаще одного напоминания в сутки (счётчик обнуляется каждый день)
    if await db.get_usage(user_id, "notify") >= 1:
        return
    for kind in ACTIVITY_KINDS:
        if await db.get_usage(user_id, kind) > 0:
            return
    level = await db.get_level(user_id)
    tier, _ = await db.get_plan(user_id)
    from plans import LIMITS
    cap = MAX_WORDS_PER_PING if tier == "plus" else LIMITS.free_reviews_per_day
    due = await db.due_cards(user_id, level, limit=cap)
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
    # отмечаем попытку в любом случае: заблокированного бота не долбим каждые 15 минут
    await db.incr_usage(user_id, "notify")


async def auto_review_loop(bot: Bot, db: Database) -> None:
    """Фоновая задача: периодические авто-повторения для платных планов."""
    if not AUTO_REVIEWS_ENABLED:
        return
    logger.info("Auto-reviews: check every %ss, send once a day %02d:00-%02d:00 (UTC%+d)",
                AUTO_REVIEW_INTERVAL, NOTIFY_HOUR_FROM, NOTIFY_HOUR_TO, NOTIFY_TZ_OFFSET)
    while True:
        try:
            utc_hour = datetime.now(timezone.utc).hour
            users = await db.users_with_due_cards(limit=200)
            for uid in users:
                tz = await db.get_notify_tz(uid)   # пояс каждого пользователя
                hour = (utc_hour + tz) % 24
                if NOTIFY_HOUR_FROM <= hour < NOTIFY_HOUR_TO:
                    await _ping_user(bot, db, uid, hour)
                    await asyncio.sleep(0.5)  # мягкий rate-limit
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Auto-review loop error")
        await asyncio.sleep(AUTO_REVIEW_INTERVAL)
