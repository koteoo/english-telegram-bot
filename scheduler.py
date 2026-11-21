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
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    lines = ["🤖 <b>Время повторить слова!</b>", ""]
    for item in due:
        lines.append(f"🃏 <b>{item.word}</b>")
    lines += ["", "Нажмите «Повторить» — пришлю карточки по одной, с переводом и примером."]
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🃏 Повторить", callback_data="card:start")]])
    try:
        await bot.send_message(user_id, "\n".join(lines), parse_mode="HTML", reply_markup=kb)
    except Exception as exc:  # noqa: BLE001 (пользователь мог заблокировать бота)
        logger.info("Auto-review ping skipped for %s: %s", user_id, exc)
    # отмечаем попытку в любом случае: заблокированного бота не долбим каждые 15 минут
    await db.incr_usage(user_id, "notify")


async def _notify_referrals(bot: Bot, db: Database) -> None:
    """Благодарности за приглашения. Блокировка бота не роняет цикл."""
    import os
    inv_days = int(os.getenv("REFERRAL_INVITER_DAYS", "7"))
    inv_ee = int(os.getenv("REFERRAL_INVITEE_DAYS", "3"))
    for r in await db.pending_referral_notifications(limit=20):
        try:
            await bot.send_message(
                r["invitee"],
                f"🎁 Первое слово в колоде — вам +{inv_ee} дня Plus!\n"
                "Все лимиты сняты на это время. Тарифы: /premium")
        except Exception as exc:  # noqa: BLE001
            logger.info("Referral thanks to %s skipped: %s", r["invitee"], exc)
        if r["rewarded"]:
            try:
                await bot.send_message(
                    r["inviter"],
                    f"🎉 Ваш друг дошёл до дела — вам +{inv_days} дней Plus!\n"
                    "Пригласить ещё: /invite")
            except Exception as exc:  # noqa: BLE001
                logger.info("Referral thanks to %s skipped: %s", r["inviter"], exc)
        await db.mark_referral_notified(r["id"])
        await asyncio.sleep(0.3)


async def auto_review_loop(bot: Bot, db: Database) -> None:
    """Фоновая задача: периодические авто-повторения для платных планов."""
    if not AUTO_REVIEWS_ENABLED:
        logger.info("Auto-reviews выключены; награды за приглашения рассылаются всё равно")
    else:
        logger.info("Auto-reviews: check every %ss, send once a day %02d:00-%02d:00 (UTC%+d)",
                    AUTO_REVIEW_INTERVAL, NOTIFY_HOUR_FROM, NOTIFY_HOUR_TO, NOTIFY_TZ_OFFSET)
    while True:
        try:
            if AUTO_REVIEWS_ENABLED:
                utc_hour = datetime.now(timezone.utc).hour
                users = await db.users_with_due_cards(limit=200)
                for uid in users:
                    tz = await db.get_notify_tz(uid)   # пояс каждого пользователя
                    hour = (utc_hour + tz) % 24
                    if NOTIFY_HOUR_FROM <= hour < NOTIFY_HOUR_TO:
                        await _ping_user(bot, db, uid, hour)
                        await asyncio.sleep(0.5)  # мягкий rate-limit
            await _notify_referrals(bot, db)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Auto-review loop error")
        await asyncio.sleep(AUTO_REVIEW_INTERVAL)
