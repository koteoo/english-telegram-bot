"""Обработчики команд и сообщений."""
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from keyboards import main_menu_kb
from db import Database

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database) -> None:
    await db.register_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "👋 Hello! I'm your English learning bot.\n\n"
        "Я помогу тебе учить английский: каждое новое слово, карточки с повторением, "
        "мини-тесты и прогресс.\n\n"
        "💡 Бесплатный план: словарь Beginner, 5 слов в день, 4 темы и разговор текстом. "
        "Голосовые сообщения, все темы, авто-повторения слов и полный словарь — "
        "на планах 💠 Plus и 👑 Premium (оплата звёздами ⭐): /premium\n\n"
        "Выбери действие в меню ниже 👇",
        reply_markup=main_menu_kb(),
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
