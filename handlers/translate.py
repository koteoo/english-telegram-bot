"""Хендлер для перевода слов по команде /tr."""
import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
import dictionary_api

logger = logging.getLogger(__name__)
router = Router()

# Реагируем только на команду /tr
@router.message(Command("tr"))
async def cmd_translate(message: Message):
    # Извлекаем слово из сообщения
    text = message.text.strip()
    word = text.replace("/tr", "", 1).strip()

    if not word:
        await message.answer("🔤 Пожалуйста, укажите слово для перевода.\nПример: `/tr hello`", parse_mode="Markdown")
        return

    await message.answer(f"🔍 Ищу перевод для: **{word}**...", parse_mode="Markdown")

    # Используем надёжный MyMemory API
    api_data = await dictionary_api.fetch_word_details(word)

    if api_data:
        response = (
            f"🇬🇧 **{api_data['word'].capitalize()}**\n\n"
            f"🇷🇺 {api_data['translation']}\n\n"
            f"💬 *{api_data['example']}*"
        )
        await message.answer(response, parse_mode="Markdown")
    else:
        await message.answer(
            f"❌ Не удалось найти перевод для '{word}'.\n"
            f"Проверьте правильность написания или попробуйте позже."
        )
