"""Тарифные планы и оплата Telegram Stars."""
from __future__ import annotations

import datetime as dt

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from db import Database
from keyboards import main_menu_kb, premium_kb, donate_kb
from plans import LIMITS, PLAN_NAMES, PLUS_DAYS, PLUS_STARS, DONATE_MIN, DONATE_MAX

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
        f"• 🎙 Голос: {LIMITS.free_voice_replies_per_day} озвучек и "
        f"{LIMITS.free_voice_inputs_per_day} распознаваний в день",
        "",
        f"<b>💠 Plus — {PLUS_STARS} ⭐ / {PLUS_DAYS} дней</b>",
        "• Полный словарь всех уровней, квизы и повторения без лимитов",
        "• 🤖 Бот сам присылает слова на повторение (авто-карточки)",
        "• 🎙 Голосовые сообщения без лимитов",
        "• Все 12 тем раскрыты полностью",
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
    await message.answer(pricing_text(plan, expires_at), parse_mode="HTML",
                         reply_markup=premium_kb())


@router.callback_query(F.data.startswith("buy:"))
async def checkout(call: CallbackQuery, db: Database) -> None:
    tier = call.data.split(":")[1]
    if tier == "plus":
        title, payload, stars, days = f"English Bot — Plus ({PLUS_DAYS} дней)", "plus", PLUS_STARS, PLUS_DAYS
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
    """XTR: сумма в целых звёздах, один элемент цены. Кратность 10 не требуется."""
    payload = query.invoice_payload
    if payload == "plus" and query.amount == PLUS_STARS:
        await query.answer(ok=True)
        return
    if payload.startswith("donate:"):
        try:
            expected = int(payload.split(":", 1)[1])
        except ValueError:
            await query.answer(ok=False, error_message="Некорректная сумма.")
            return
        if expected == query.amount and DONATE_MIN <= query.amount <= DONATE_MAX:
            await query.answer(ok=True)
        else:
            await query.answer(ok=False, error_message="Сумма не совпадает с инвойсом.")
        return
    await query.answer(ok=False, error_message="Что-то пошло не так, попробуйте позже.")


@router.message(F.successful_payment)
async def successful_payment(message: Message, db: Database, state: FSMContext) -> None:
    tp = message.successful_payment
    if tp.invoice_payload.startswith("donate:"):
        await db.add_payment(message.from_user.id, "donate", tp.total_amount, 0,
                             getattr(tp, "telegram_payment_charge_id", None))
        await message.answer(
            f"❤️ Спасибо за поддержку! Получено {tp.total_amount} ⭐.\n"
            "Донат не меняет тариф — он помогает оплачивать сервер и API.",
            parse_mode="HTML", reply_markup=main_menu_kb(),
        )
        return
    days = PLUS_DAYS
    new_plan = tp.invoice_payload
    await db.add_payment(message.from_user.id, new_plan, tp.total_amount, days,
                         getattr(tp, "telegram_payment_charge_id", None))
    await db.set_plan(message.from_user.id, new_plan, days)
    await state.update_data(chat_tier=new_plan)
    await message.answer(
        f"🎉 Оплата прошла успешно! Добро пожаловать на план <b>{PLAN_NAMES[new_plan]}</b> "
        f"({tp.total_amount} ⭐ на {days} дней).\n\n"
        "Все функции уже разблокированы 👇",
        parse_mode="HTML",
    )


class DonateState(StatesGroup):
    waiting_amount = State()


DONATE_TEXT = (
    "❤️ <b>Поддержать проект</b>\n\n"
    "Бот бесплатный, но сервер и API стоят денег. Донат добровольный "
    "и <b>не меняет тариф</b> — просто поддержка.\n\n"
    f"Выберите сумму или введите свою: целое число звёзд от {DONATE_MIN} до {DONATE_MAX}."
)


async def _send_donate_invoice(message: Message, amount: int) -> None:
    await message.answer_invoice(
        title="Поддержка English Bot",
        description="Спасибо! Это добровольный донат, тариф не меняется.",
        payload=f"donate:{amount}",
        currency=CURRENCY,
        prices=[LabeledPrice(label="Поддержка проекта", amount=amount)],
    )


@router.message(Command("donate"))
async def show_donate(message: Message) -> None:
    await message.answer(DONATE_TEXT, parse_mode="HTML", reply_markup=donate_kb())


@router.callback_query(F.data.startswith("donate:"))
async def donate_action(call: CallbackQuery, state: FSMContext) -> None:
    action = call.data.split(":", 1)[1]
    if action == "menu":
        await call.answer()
        await call.message.answer(DONATE_TEXT, parse_mode="HTML", reply_markup=donate_kb())
        return
    if action == "custom":
        await state.set_state(DonateState.waiting_amount)
        await call.answer()
        await call.message.answer(
            f"Введите сумму доната целым числом звёзд ({DONATE_MIN}–{DONATE_MAX}).\n"
            "Отмена: /cancel"
        )
        return
    if action.isdigit():
        amount = int(action)
        if not (DONATE_MIN <= amount <= DONATE_MAX):
            await call.answer("Сумма вне диапазона", show_alert=True)
            return
        await call.answer()
        await _send_donate_invoice(call.message, amount)
        return
    await call.answer()


@router.message(DonateState.waiting_amount, Command("cancel"))
async def donate_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu_kb())


@router.message(DonateState.waiting_amount)
async def donate_custom_amount(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужно целое число звёзд, например 150. Отмена: /cancel")
        return
    amount = int(raw)
    if not (DONATE_MIN <= amount <= DONATE_MAX):
        await message.answer(f"Сумма должна быть от {DONATE_MIN} до {DONATE_MAX} ⭐.")
        return
    await state.clear()
    await _send_donate_invoice(message, amount)
