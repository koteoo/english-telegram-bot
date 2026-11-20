"""Обработчики команд и сообщений."""
from aiogram import Router, F
from aiogram.filters import Command, CommandStart, Command
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

    parts = (message.text or "").split(maxsplit=1)
    source = "direct"
    if len(parts) == 2:
        tag = re.sub(r"[^A-Za-z0-9_-]", "", parts[1])[:32]
        if tag:
            source = tag
    is_new = not await db.user_exists(message.from_user.id)
    await db.register_user(message.from_user.id, message.from_user.username, source=source)
    if not is_new:
        await message.answer("🏠 Главное меню:", reply_markup=main_menu_kb())
        return
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
        "🦎 Привет! Я <b>Gecko</b> — ваш репетитор английского.\n\n"
        "Нажмите 🎯 <b>Level</b>: тест за 2 минуты подберёт слова под ваш уровень.\n"
        "Ошибаться можно и нужно — поправлю мягко и объясню.\n\n"
        "🆓 Каждый день бесплатно · 💠 без лимитов: /premium · 🎁 друг в подарок: /invite",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text.in_({"🏠 Main menu", "❌ Отмена", "❌Отмена"}))
@router.message(Command("menu"))
async def cmd_global_menu(message: Message, state: FSMContext):
    await state.clear()
    # Локальный импорт гарантирует, что функция будет найдена
    from keyboards import main_menu_kb
    await message.answer("🏠 Главное меню:", reply_markup=main_menu_kb())
