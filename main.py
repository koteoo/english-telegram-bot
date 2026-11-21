"""Точка входа: запуск Telegram-бота для изучения английского языка."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from db import Database
import dictionary
from handlers import start, learning, chat, premium, translate, feedback, referral
from scheduler import auto_review_loop
from aiogram.types import BotCommand

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Укажите токен бота: экспортируйте переменную окружения BOT_TOKEN")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(start.router)
    dp.include_router(premium.router)
    dp.include_router(feedback.router)
    dp.include_router(referral.router)
    dp.include_router(learning.router)  # ВАЖНО: learning ПЕРЕД chat, чтобы кнопки меню работали
    dp.include_router(chat.router)  # чат
    dp.include_router(translate.router)  # перевод — в самом конце

    # команды не регистрируем: список в меню дублирует нижнюю клавиатуру,
    # а пустой список скрывает кнопку у строки ввода
    await bot.delete_my_commands()

    database = Database()
    await database.connect()

    review_task = asyncio.create_task(auto_review_loop(bot, database))
    dict_task = asyncio.create_task(dictionary.preload())
    try:
        await dp.start_polling(bot, db=database)
    finally:
        review_task.cancel()
        dict_task.cancel()
        await database.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
