"""Обращения пользователей: вопросы, предложения, жалобы, ошибки.

Хранятся в таблице feedback и видны в админ-панели (вкладка «Обращения»).
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from db import Database
from keyboards import main_menu_kb

logger = logging.getLogger(__name__)
router = Router()

KINDS = {
    "question": "❓ Вопрос",
    "idea": "💡 Предложение",
    "complaint": "⚠️ Жалоба",
    "bug": "🐞 Ошибка",
}

HELP_TEXT = (
    "❓ <b>Справка и обратная связь</b>\n\n"
    "<b>Основные команды</b>\n"
    "📚 Word of the Day — новое слово в колоду\n"
    "🃏 Flashcards — повторение и добавление слов\n"
    "✍️ Quiz — грамматика\n"
    "🗣 Chat with me — разговор с тьютором, голос\n"
    "🔄 Translate — перевод RU↔EN\n"
    "🎯 Level — тест CEFR и цель обучения\n"
    "📊 Progress — прогресс, /export — выгрузка\n"
    "🔔 Напоминания — час и часовой пояс\n"
    "💎 Тарифы — Free и Plus, /donate — поддержка\n\n"
    "<b>Написать нам</b> — выберите тип обращения ниже. "
    "Мы читаем все сообщения и отвечаем по возможности."
)


class FeedbackState(StatesGroup):
    waiting_text = State()


def feedback_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=KINDS["question"], callback_data="fb:question"),
         InlineKeyboardButton(text=KINDS["idea"], callback_data="fb:idea")],
        [InlineKeyboardButton(text=KINDS["complaint"], callback_data="fb:complaint"),
         InlineKeyboardButton(text=KINDS["bug"], callback_data="fb:bug")],
    ])


@router.message(F.text == "❓ Help")
@router.message(Command("help"))
async def show_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(HELP_TEXT, parse_mode="HTML", reply_markup=feedback_kb())


@router.callback_query(F.data.startswith("fb:"))
async def pick_kind(call: CallbackQuery, state: FSMContext) -> None:
    kind = call.data.split(":", 1)[1]
    if kind not in KINDS:
        await call.answer()
        return
    await state.set_state(FeedbackState.waiting_text)
    await state.update_data(fb_kind=kind)
    await call.answer()
    await call.message.answer(
        f"{KINDS[kind]}\n\nОпишите одним сообщением (до 2000 символов). "
        "Если это ошибка — укажите, что нажали и что произошло.\n\nОтмена: /cancel"
    )


@router.message(FeedbackState.waiting_text, Command("cancel"))
async def fb_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu_kb())


@router.message(FeedbackState.waiting_text, F.text)
async def receive_feedback(message: Message, state: FSMContext, db: Database) -> None:
    text = (message.text or "").strip()
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
        parse_mode="HTML", reply_markup=main_menu_kb(),
    )
