"""Админ-панель внутри бота. Доступна только владельцу (ADMIN_USER_ID)."""
import os
import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

from admin import analytics

logger = logging.getLogger(__name__)
router = Router()

ADMIN_ID = int(os.getenv("ADMIN_USER_ID", "0") or "0")


def is_admin(user_id: int) -> bool:
    return ADMIN_ID and user_id == ADMIN_ID


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return  # молча игнорируем

    try:
        data = analytics.business()
    except Exception as e:
        logger.exception("admin overview failed")
        await message.answer(f"Ошибка получения статистики: {e}")
        return

    text = (
        "📊 <b>Админ-панель</b>\n\n"
        f"👥 Пользователей: <b>{data.get('users_total', 0)}</b>\n"
        f"   сегодня: +{data.get('users_today', 0)} · за 7 дней: +{data.get('users_week', 0)}\n\n"
        f"🔥 Активны сегодня: <b>{data.get('active_today', 0)}</b>\n"
        f"   за 7 дней: {data.get('active_week', 0)}\n\n"
        f"💠 Платящих сейчас: <b>{data.get('paying_now', 0)}</b>\n"
        f"   конверсия: {data.get('conversion_pct', 0)}%\n\n"
        f"⭐ Выручка всего: <b>{data.get('revenue_total', 0)}</b> ⭐\n"
        f"   за 30 дней: {data.get('revenue_30d', 0)} ⭐\n"
        f"   сегодня: {data.get('revenue_today', 0)} ⭐\n\n"
        f"📨 Новых обращений: <b>{data.get('feedback_new', 0)}</b>\n\n"
        f"<i>Команды:</i>\n"
        f"/admin — эта сводка\n"
        f"/users — последние пользователи\n"
        f"/revenue — выручка подробнее"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("users"))
async def cmd_users(message: Message):
    if not is_admin(message.from_user.id):
        return

    try:
        res = analytics.users_list(limit=15)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        return

    lines = ["👥 <b>Последние пользователи</b>\n"]
    for u in res.get("items", []):
        tier = u.get("tier") or "free"
        lines.append(
            f"<code>{u['user_id']}</code> · {u.get('username') or '—'} · {tier} · "
            f"{(u.get('created_at') or '')[:10]}"
        )
    if not res.get("items"):
        lines.append("Пока пусто")
    lines.append(f"\n<i>Всего: {res.get('total', 0)}</i>")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("revenue"))
async def cmd_revenue(message: Message):
    if not is_admin(message.from_user.id):
        return

    try:
        data = analytics.business()
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        return

    text = (
        "💰 <b>Выручка</b>\n\n"
        f"Всего: <b>{data.get('revenue_total', 0)}</b> ⭐\n"
        f"За 30 дней: {data.get('revenue_30d', 0)} ⭐\n"
        f"Сегодня: {data.get('revenue_today', 0)} ⭐\n\n"
        f"Подписки: {data.get('revenue_subs', 0)} ⭐\n"
        f"Донаты: {data.get('revenue_donations', 0)} ⭐ "
        f"({data.get('donations_count', 0)} шт.)\n\n"
        f"Средний чек: {data.get('avg_check', 0)} ⭐\n"
        f"Платящих сейчас: {data.get('paying_now', 0)}"
    )
    await message.answer(text, parse_mode="HTML")
