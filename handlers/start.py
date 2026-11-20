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
        "🦎 Привет! Я <b>Gecko</b> — ваш репетитор английского.\n\n"
        "Нажмите 🎯 <b>Level</b>: тест за 2 минуты подберёт слова под ваш уровень.\n"
        "Ошибаться можно и нужно — поправлю мягко и объясню.\n\n"
        "🆓 Каждый день бесплатно · 💠 без лимитов: /premium · 🎁 друг в подарок: /invite",
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
    is_new = not await db.user_exists(message.from_user.id)
    await db.register_user(message.from_user.id, message.from_user.username, source=source)
    if is_new and source.startswith("ref_"):
        try:
            inviter = int(source[4:])
        except ValueError:
            inviter = 0
        if inviter and await db.add_referral(inviter, message.from_user.id):
            await message.answer(
                "🎁 Вы пришли по приглашению. Добавьте первое слово в колоду "
                "(📚 Word of the Day или 🃏 Flashcards → ➕ Add word) — "
                "и получите несколько дней Plus в подарок."
            )

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
