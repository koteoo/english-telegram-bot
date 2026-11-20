"""Обработчики команд и сообщений."""
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards import main_menu_kb, translate_menu_kb
from db import Database

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state == "TranslateState:waiting_for_text":
        await message.answer(
            "🔄 <b>Режим перевода активен</b>\n\n"
            "✍️ Введите слово или фразу для перевода.\n"
            "Можете переводить несколько слов подряд.\n\n"
            "Для выхода нажмите 🏠 Main menu или /cancel",
            parse_mode="HTML",
            reply_markup=translate_menu_kb(),
        )
        return

    import re
    from keyboards import main_menu_kb
    from plans import LIMITS

    parts = (message.text or "").split(maxsplit=1)
    source = "direct"
    if len(parts) == 2:
        tag = re.sub(r"[^A-Za-z0-9_-]", "", parts[1])[:32]
        if tag:
            source = tag
    await db.register_user(message.from_user.id, message.from_user.username, source=source)

    await message.answer(
        "👋 Hello! I'm your English learning bot.\n\n"
        "Слова с интервальным повторением, квизы, разговор с ИИ-тьютором "
        "голосом и текстом, перевод и тест уровня CEFR.\n\n"
        f"🆓 <b>Free</b>: словари всех уровней, {LIMITS.free_words_per_day} новых слов "
        f"и {LIMITS.free_quizzes_per_day} квизов в день, {LIMITS.free_translate_per_day} переводов, "
        f"{LIMITS.free_chat_messages_per_day} сообщений чата, "
        f"{LIMITS.free_voice_replies_per_day} озвучек и {LIMITS.free_voice_inputs_per_day} голосовых, "
        f"{LIMITS.free_reviews_per_day} слова на авто-повторение.\n"
        "💠 <b>Plus</b> — всё без ограничений: /premium\n\n"
        "Начните с 🎯 <b>Level</b>: тест определит ваш уровень, "
        "и слова будут подобраны под него 👇",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text.in_({"🏠 Main menu", "❌ Отмена", "❌Отмена"}))
async def cmd_global_menu(message: Message, state: FSMContext):
    await state.clear()
    # Локальный импорт гарантирует, что функция будет найдена
    from keyboards import main_menu_kb
    await message.answer("🏠 Главное меню:", reply_markup=main_menu_kb())
