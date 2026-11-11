"""Хендлер для интерактивного чата на английском."""
import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Импорт зависимостей
from keyboards import chat_menu_kb, main_menu_kb

logger = logging.getLogger(__name__)
router = Router()


class ChatStates(StatesGroup):
    in_chat = State()


async def cmd_chat(message: Message, state: FSMContext):
    """Основная логика запуска чата."""
    await state.set_state(ChatStates.in_chat)
    
    # Приветственное сообщение
    text = (
        "🗣 <b>Давай попрактикуем английский!</b>\n\n"
        "Просто пиши мне на английском, и я буду поддерживать разговор.\n"
        "Если не знаешь, как сказать что-то — напиши по-русски, я подскажу.\n\n"
        "Выбери тему ниже или просто начни писать!\n"
        "Для выхода нажмите 🏠 Main menu."
    )
    
    reply_markup = chat_menu_kb()
    
    await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


@router.message(Command("chat"))
async def handle_chat_command(message: Message, state: FSMContext):
    """Обработка команды /chat"""
    await cmd_chat(message, state)


@router.message(F.text == "🗣 Chat with me")
async def btn_chat(message: Message, state: FSMContext):
    """Обработка нажатия кнопки 'Chat with me'"""
    logger.info("BTN CHAT TRIGGERED for user %s", message.from_user.id)
    
    # Сбрасываем любые другие состояния, чтобы избежать конфликтов
    await state.clear()
    
    # Запускаем чат
    await cmd_chat(message, state)


@router.message(ChatStates.in_chat, F.text & ~F.text.in_({"🏠 Main menu", "❌ Отмена"}))
async def chat_message(message: Message, state: FSMContext):
    """Обработка сообщений в режиме чата."""
    # Здесь должна быть логика отправки ответа через LLM или rule-based engine
    # Для теста просто эхо-ответ
    await message.answer(f"💬 Вы написали: {message.text}\n(Здесь будет ответ бота)")


@router.message(ChatStates.in_chat, F.text == "🏠 Main menu")
async def exit_chat(message: Message, state: FSMContext):
    """Выход из режима чата."""
    await state.clear()
    await message.answer("✅ Вернулись в главное меню.", reply_markup=main_menu_kb())
