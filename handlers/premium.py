"""Тарифные планы и оплата Telegram Stars."""
from __future__ import annotations

import datetime as dt

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from db import Database
from keyboards import main_menu_kb, premium_kb
from plans import LIMITS, PLAN_NAMES, PLUS_DAYS, PLUS_STARS, PREMIUM_DAYS, PREMIUM_STARS

router = Router()

CURRENCY = "XTR"  # Telegram Stars


def _fmt_left(expires_at: str | None) -> str:
    if not expires_at:
        return "∞"
    exp = dt.datetime.fromisoformat(expires_at)
    days = max((exp - dt.datetime.now(dt.timezone.utc)).days, 0)
    return f"{days} дн."


def pricing_text(plan: str, expires_at: str | None) -> str:
    lines = [f"🎫 Твой текущий план: <b>{PLAN_NAMES[plan]}</b>"]
    if plan != "free":
        lines.append(f"⏳ Действует ещё: {_fmt_left(expires_at)}")
    lines += [
        "",
        "<b>🆓 Free</b>",
        "• Словарь: только уровень Beginner",
        f"• {LIMITS.free_words_per_day} новых слов/день, квиз {LIMITS.free_quizzes_per_day} вопроса/день",
        f"• Темы: {LIMITS.open_topics_free} из 12, разговор текстом "
        f"({LIMITS.free_chat_messages_per_day} сообщ./день)",
        "• ❌ Голосовые сообщения недоступны",
        "",
        f"<b>💠 Plus — {PLUS_STARS} ⭐ / {PLUS_DAYS} дней</b>",
        "• Полный словарь всех уровней, квизы и повторения без лимитов",
        "• 🤖 Бот сам присылает слова на повторение (авто-карточки)",
        "• 🎙 Голосовые сообщения с разумными лимитами",
        "• Все 12 тем раскрыты полностью",
        "",
        f"<b>👑 Premium — {PREMIUM_STARS} ⭐ / {PREMIUM_DAYS} дней</b>",
        "• Всё включено и без каких-либо ограничений",
        "• Приоритетная модель диалога и неограниченный голос",
        "",
        "Оплата прямо в Telegram через Stars 👇",
    ]
    return "\n".join(lines)


LIMIT_TXT_WORDS = str(LIMITS.free_words_per_day)
LIMIT_TXT_QUIZ = str(LIMITS.free_quizzes_per_day)
LIMIT_TXT_TOPICS = str(LIMITS.open_topics_free)
LIMIT_TXT_CHAT = str(LIMITS.free_chat_messages_per_day)


@router.message(F.text == "💎 Premium")
@router.message(Command("premium"))
async def show_premium(message: Message, db: Database) -> None:
    plan, expires_at = await db.get_plan(message.from_user.id)
    await message.answer(pricing_text(plan, expires_at), parse_mode="HTML", reply_markup=premium_kb())


@router.callback_query(F.data.startswith("buy:"))
async def checkout(call: CallbackQuery, db: Database) -> None:
    tier = call.data.split(":")[1]
    if tier == "plus":
        title, payload, stars, days = f"English Bot — Plus ({PLUS_DAYS} дней)", "plus", PLUS_STARS, PLUS_DAYS
    elif tier == "premium":
        title, payload, stars, days = f"English Bot — Premium ({PREMIUM_DAYS} дней)", "premium", PREMIUM_STARS, PREMIUM_DAYS
    else:
        await call.answer("Неизвестный план 😅", show_alert=True)
        return

    await call.message.answer_invoice(
        title=title,
        description="Спасибо за поддержку проекта! ❤️",
        payload=payload,
        currency=CURRENCY,
        prices=[LabeledPrice(label="Подписка", amount=stars)],
    )
    await call.answer()


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    # XTR требует, чтобы сумма была кратна 10 звёздам
    if query.invoice_payload in {"plus", "premium"} and query.amount % 10 == 0:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Что-то пошло не так, попробуйте позже.")


@router.message(F.successful_payment)
async def successful_payment(message: Message, db: Database, state: FSMContext) -> None:
    tp = message.successful_payment
    days = PLUS_DAYS if tp.invoice_payload == "plus" else PREMIUM_DAYS
    new_plan = tp.invoice_payload
    await db.set_plan(message.from_user.id, new_plan, days)
    await state.update_data(chat_tier=new_plan)
    await message.answer(
        f"🎉 Оплата прошла успешно! Добро пожаловать на план <b>{PLAN_NAMES[new_plan]}</b> "
        f"({tp.total_amount} ⭐ на {days} дней).\n\n"
        "Все функции уже разблокированы 👇",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )
