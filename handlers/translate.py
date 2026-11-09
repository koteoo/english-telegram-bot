"""Хендлер для перевода слов через меню или команду /tr."""
import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import dictionary_api
from data.vocabulary import VOCABULARY
from keyboards import main_menu_kb, translate_menu_kb

logger = logging.getLogger(__name__)
router = Router()


class TranslateState(StatesGroup):
    waiting_for_text = State()


# 1. Обработка нажатия кнопки "🔄 Translate" в меню
@router.message(F.text == "🔄 Translate")
async def cmd_translate_menu(message: Message, state: FSMContext):
    await state.set_state(TranslateState.waiting_for_text)
    await message.answer(
        "🔄 <b>Режим перевода активен</b>\n\n"
        "✍️ Введите слово или фразу для перевода.\n"
        "Можете переводить несколько слов подряд!\n\n"
        "Для выхода нажмите 🏠 Main menu или /cancel",
        parse_mode="HTML",
        reply_markup=translate_menu_kb()
    )


# 2. Обработка текста ТОЛЬКО когда пользователь находится в режиме перевода
@router.message(TranslateState.waiting_for_text)
async def process_translate_input(message: Message, state: FSMContext):
    # Если пользователь нажал кнопку выхода, пропускаем (обработает start.py)
    if "Main menu" in message.text or "Отмена" in message.text:
        return
        
    text = message.text.strip()
    await process_translation(message, text)


# 3. Ручная команда /tr (работает из любого состояния)
@router.message(Command("tr"))
async def cmd_translate_manual(message: Message, state: FSMContext):
    text = message.text.replace("/tr", "", 1).strip()
    if not text:
        await state.set_state(TranslateState.waiting_for_text)
        await message.answer(
            "🔄 <b>Режим перевода активен</b>\n\n"
            "✍️ Введите слово или фразу для перевода.\n"
            "Можете переводить несколько слов подряд!\n\n"
            "Для выхода нажмите 🏠 Main menu или /cancel",
            parse_mode="HTML",
            reply_markup=translate_menu_kb()
        )
        return
    
    await state.clear()
    await process_translation(message, text)


# 4. Команда /cancel для выхода из режима перевода
@router.message(Command("cancel"), TranslateState.waiting_for_text)
async def cmd_cancel_translate(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "✅ Режим перевода завершён.",
        reply_markup=main_menu_kb()
    )


async def process_translation(message: Message, text: str):
    """Основная функция перевода."""
    # 1. Пробуем внешний API
    api_data = await dictionary_api.fetch_word_details(text)

    if api_data:
        response = api_data["translation"]
        if api_data["example"]:
            response += f"\n\n💬 <i>{api_data['example']}</i>"
        response += "\n\n<i>➡️ Введите следующее слово или нажмите 🏠 Main menu</i>"
        await message.answer(response, parse_mode="HTML", reply_markup=translate_menu_kb())
        return

    # 2. Fallback: ищем во встроенном словаре
    word_lower = text.lower()
    found_in_local = False
    for level_words in VOCABULARY.values():
        for w, t, e in level_words:
            if w.lower() == word_lower:
                response = f"🇬🇧 <b>{w.capitalize()}</b>\n\n🇷🇺 {t.capitalize()}"
                if e:
                    response += f"\n\n💬 <i>{e}</i>"
                response += "\n\n<i>➡️ Введите следующее слово или нажмите 🏠 Main menu</i>"
                await message.answer(response, parse_mode="HTML", reply_markup=translate_menu_kb())
                found_in_local = True
                break
        if found_in_local:
            break

    # 3. Если ничего не найдено
    if not found_in_local:
        await message.answer(
            f"❌ Не удалось найти перевод для '{text}'.\n"
            f"Проверьте правильность написания.\n\n"
            f"<i>➡️ Попробуйте другое слово или нажмите 🏠 Main menu</i>",
            parse_mode="HTML",
            reply_markup=translate_menu_kb()
        )
