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

    await db.register_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "👋 Hello! I'm your English learning bot.\n\n"
        "Я помогу тебе учить английский: каждое новое слово, карточки с повторением, "
        "мини-тесты и прогресс.\n\n"
        "💡 Бесплатный план: словарь Beginner, 5 слов в день, 4 темы и разговор текстом. "
        "Голосовые сообщения, все темы, авто-повторения слов и полный словарь — "
        "на планах 💠 Plus и 👑 Premium (оплата звёздами ⭐): /premium\n\n"
        "Выбери действие в меню ниже 👇",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "📖 <b>Как пользоваться ботом:</b>\n\n"
        "📚 <b>Word of the Day</b> — случайное слово с переводом и примером\n"
        "🃏 <b>Flashcards</b> — повторение выученных слов (интервальная методика)\n"
        "✍️ <b>Quiz</b> — мини-тест на грамматику (5 вопросов)\n"
        "➕ <b>Add word</b> — отправь английское слово текстом, и я добавлю его в твою колоду\n"
        "📊 <b>Progress</b> — твоя статистика\n"
        "🎯 <b>Level</b> — выбрать уровень: Beginner / Intermediate / Advanced\n"
        "📚 <b>Topics</b> (/topics) — идеи и лексика по 12 темам: путешествия, еда, работа и др.\n"
        "🗣 <b>Chat with me</b> (/chat) — интерактивный разговор на английском по выбранной теме\n\n"
        "Совет: регулярно повторяй слова — бот сам подберёт, что пора вспомнить!",
        parse_mode="HTML",
    )




# === ЕДИНЫЙ глобальный обработчик кнопки "🏠 Main menu" и "❌ Отмена" ===
@router.message(F.text.in_({"🏠 Main menu", "❌ Отмена", "❌Отмена"}))
async def cmd_global_menu(message: Message, state: FSMContext):
    await state.clear()
    # Локальный импорт гарантирует, что функция будет найдена
    from keyboards import main_menu_kb
    await message.answer("🏠 Главное меню:", reply_markup=main_menu_kb())
