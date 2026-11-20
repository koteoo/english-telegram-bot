"""Справка и обращения пользователей: вопросы, предложения, жалобы, ошибки.

Обращения хранятся в таблице feedback и видны в админ-панели («Обращения»).
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from db import Database
from keyboards import help_menu_kb, main_menu_kb

logger = logging.getLogger(__name__)
router = Router()

KINDS = {
    "question": "❓ Вопрос",
    "idea": "💡 Предложение",
    "complaint": "⚠️ Жалоба",
    "bug": "🐞 Ошибка",
}

BUTTON_KIND = {
    "❓ Задать вопрос": "question",
    "💡 Предложение": "idea",
    "⚠️ Жалоба": "complaint",
    "🐞 Ошибка": "bug",
}

MENU_TEXT = (
    "❓ <b>Справка и обратная связь</b>\n\n"
    "Выберите, что хотите сделать:\n"
    "• 📖 Инструкция — как пользоваться ботом\n"
    "• ❓ Вопрос, 💡 Предложение, ⚠️ Жалоба, 🐞 Ошибка — написать нам\n\n"
    "Мы читаем все обращения. Ответ придёт в этот чат, если он потребуется."
)

GUIDE_TEXT = (
    "📖 <b>Как пользоваться ботом</b>\n\n"
    "📚 <b>Word of the Day</b> — слово вашего уровня, сразу попадает в колоду\n"
    "🃏 <b>Flashcards</b> — повторение по интервалам; там же ➕ Add word\n"
    "✍️ <b>Quiz</b> — грамматика с кнопками\n"
    "🗣 <b>Chat with me</b> — разговор с тьютором, голос, помощь с фразой\n"
    "🔄 <b>Translate</b> — перевод RU↔EN\n"
    "🎯 <b>Level</b> — тест CEFR A1–C2 и цель обучения\n"
    "📊 <b>Progress</b> — прогресс; /export — выгрузка в JSON\n"
    "🔔 <b>Напоминания</b> — час и часовой пояс\n"
    "💎 <b>Тарифы</b> — Free и Plus; /donate — поддержка проекта\n\n"
    "Совет: повторяйте слова каждый день — интервалы подобраны так, "
    "чтобы слово всплывало перед тем, как вы его забудете."
)


class FeedbackState(StatesGroup):
    waiting_text = State()


@router.message(F.text == "❓ Help")
@router.message(Command("help"))
async def show_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(MENU_TEXT, parse_mode="HTML", reply_markup=help_menu_kb())


@router.message(F.text == "📖 Инструкция")
async def show_guide(message: Message) -> None:
    await message.answer(GUIDE_TEXT, parse_mode="HTML", reply_markup=help_menu_kb())


@router.message(F.text.in_(set(BUTTON_KIND)))
async def pick_kind_text(message: Message, state: FSMContext) -> None:
    kind = BUTTON_KIND[message.text]
    await state.set_state(FeedbackState.waiting_text)
    await state.update_data(fb_kind=kind)
    await message.answer(
        f"{KINDS[kind]}\n\nОпишите одним сообщением (до 2000 символов). "
        "Если это ошибка — укажите, что нажали и что произошло.\n\nОтмена: /cancel"
    )


@router.callback_query(F.data.startswith("fb:"))
async def pick_kind_cb(call: CallbackQuery, state: FSMContext) -> None:
    """Совместимость со старыми сообщениями, где кнопки были inline."""
    kind = call.data.split(":", 1)[1]
    if kind not in KINDS:
        await call.answer()
        return
    await state.set_state(FeedbackState.waiting_text)
    await state.update_data(fb_kind=kind)
    await call.answer()
    await call.message.answer(
        f"{KINDS[kind]}\n\nОпишите одним сообщением. Отмена: /cancel"
    )


@router.message(FeedbackState.waiting_text, Command("cancel"))
async def fb_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu_kb())


@router.message(FeedbackState.waiting_text, F.text)
async def receive_feedback(message: Message, state: FSMContext, db: Database) -> None:
    text = (message.text or "").strip()
    if text in BUTTON_KIND or text in ("📖 Инструкция", "🏠 Main menu", "❓ Help"):
        await state.clear()
        return  # кнопку меню не считаем обращением
    if len(text) < 3:
        await message.answer("Слишком коротко — опишите подробнее. Отмена: /cancel")
        return
    data = await state.get_data()
    kind = data.get("fb_kind") or "question"
    tier, _ = await db.get_plan(message.from_user.id)
    fid = await db.add_feedback(message.from_user.id, kind, text[:2000], tier)
    await state.clear()
    logger.info("feedback #%s %s from %s", fid, kind, message.from_user.id)
    await message.answer(
        f"✅ Обращение <b>#{fid}</b> принято ({KINDS.get(kind, kind)}).\n"
        "Спасибо — оно попало к нам в панель. Номер пригодится, если захотите уточнить.",
        parse_mode="HTML", reply_markup=help_menu_kb(),
    )
